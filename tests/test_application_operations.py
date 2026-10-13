from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from ehrm.core.settings import load_settings
from ehrm.core.auth_repository import SystemType
from ehrm.core.exceptions import EmployeeNotFoundError, TaskCancelledError
from ehrm.modules.employment_termination.models import EmploymentTerminationItem
from ehrm.modules.employment_termination.service import EmploymentTerminationService
from ehrm.modules.employment_termination.submission import TerminationSubmissionError
from ehrm.modules.medical_enrollment.models import MedicalPreSubmitItem, MedicalStage
from ehrm.modules.medical_enrollment.page import MedicalPreSubmitBlockedError
from ehrm.modules.medical_enrollment.submission import MedicalEnrollmentSubmissionUncertainError
from ehrm.modules.medical_termination.models import MedicalTerminationItem
from ehrm.modules.medical_termination.page import MedicalSubmissionUncertainError
from ehrm.modules.nocobase.models import NocoBaseRightsApplicationDetail
from ehrm.web.application_operations import ApplicationOperationRepository, ApplicationOperationService, person_key
from ehrm.web.app import create_app
from ehrm.web.tasks import TaskCoordinator, TaskKind, TaskStatus

IDENTITIES = ['320101199001011234', '320101199002021235', '320101199003031236']


def account(id=10):
    return SimpleNamespace(id=id, display_name='测试单位', account='test', password='secret')


def people():
    return tuple((EmploymentTerminationItem(identity, '6304').normalized(), f'测试人员{i}') for i, identity in enumerate(IDENTITIES))


def test_persistent_partial_success_and_unknown_are_not_resubmitted_even_with_new_account(tmp_path):
    repo = ApplicationOperationRepository(tmp_path / 'operations.sqlite3')
    run_id, items = repo.reserve(1, 'termination', people(), account())
    repo.mark(run_id, items[0], 'succeeded', '提交成功')
    repo.mark(run_id, items[1], 'unknown', '结果待确认')
    repo.finish(run_id)
    restarted = ApplicationOperationRepository(repo.path)
    _, retry = restarted.reserve(1, 'termination', people(), account(11))
    assert [item.identity_number for item in retry] == [IDENTITIES[2]]
    state = restarted.state(1)
    assert state['people'][0]['status'] == 'succeeded'
    assert state['people'][1]['status'] == 'unknown'


def test_restart_releases_unexecuted_but_blocks_inflight_submission(tmp_path):
    repo = ApplicationOperationRepository(tmp_path / 'operations.sqlite3')
    run_id, items = repo.reserve(1, 'termination', people(), account())
    repo.mark(run_id, items[0], 'submitting', '提交中')
    repo.recover()
    assert [row['status'] for row in repo.state(1)['people']] == ['unknown', 'not_processed', 'not_processed']
    _, retry = repo.reserve(1, 'termination', people(), account())
    assert len(retry) == 2


def test_concurrent_admission_allows_only_one_batch(tmp_path):
    repo = ApplicationOperationRepository(tmp_path / 'operations.sqlite3')
    def reserve(_):
        try:
            repo.reserve(1, 'termination', people(), account())
            return True
        except HTTPException as exc:
            assert exc.status_code == 409
            return False
    with ThreadPoolExecutor(4) as executor:
        assert sum(executor.map(reserve, range(4))) == 1


def test_all_successful_people_are_blocked_and_other_operation_is_independent(tmp_path):
    repo = ApplicationOperationRepository(tmp_path / 'operations.sqlite3')
    run_id, items = repo.reserve(1, 'termination', people(), account())
    for item in items:
        repo.mark(run_id, item, 'succeeded', '已办理')
    repo.finish(run_id)
    with pytest.raises(HTTPException, match='人员均已成功'):
        repo.reserve(1, 'termination', people(), account())
    assert len(repo.reserve(1, 'information_collection', people(), account())[1]) == 3
    assert person_key(' 32010119900101123x ') == person_key('32010119900101123X')


def test_service_records_success_before_progress_callback_can_cancel(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    events = []
    def progress(_):
        raise TaskCancelledError('停止')
    with patch('ehrm.modules.employment_termination.service.EmploymentTerminationPage', return_value=Mock()):
        with pytest.raises(TaskCancelledError):
            EmploymentTerminationService(settings, Mock(), progress_callback=progress).submit_with_page(
                Mock(), [people()[0][0]], before_submit_callback=lambda item: events.append('submitting'),
                result_callback=lambda result: events.append(result.status))
    assert events == ['submitting', 'submitted']


def test_web_run_reuses_login_and_submission_and_records_step_logs(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    settings_service = SimpleNamespace(runtime_root=tmp_path, runtime_settings=Mock(return_value=settings))
    service = ApplicationOperationService(settings_service, Mock(), Mock())
    run_id, items = service.repository.reserve(1, 'termination', people()[:1], account())
    browser = MagicMock()
    context = SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    with patch('ehrm.web.application_operations.BrowserManager', return_value=browser), \
         patch('ehrm.web.application_operations.LoginService') as login, \
         patch('ehrm.modules.employment_termination.service.EmploymentTerminationPage', return_value=Mock()) as automation:
        result = service._run(context, run_id, account(), items)
    login.return_value.ensure_authenticated.assert_called_once()
    automation.return_value.submit_item.assert_called_once()
    assert result['submitted_count'] == 1
    assert service.repository.state(1)['people'][0]['status'] == 'succeeded'
    assert service.repository.logs(run_id)


def test_api_requires_confirmation_and_valid_business_and_data(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator()
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    query = app.state.nocobase_query_service
    query.get_application = Mock(return_value=SimpleNamespace(problem_type='social_security_rights'))
    client = TestClient(app)
    try:
        response = client.post('/api/v1/nocobase/applications/1/termination', json={'account_id': 10})
        assert response.status_code == 400
        query.get_application.assert_not_called()
        response = client.post('/api/v1/nocobase/applications/1/termination', json={'account_id': 10, 'confirmed': True})
        assert response.status_code == 400
        query.get_application.return_value = SimpleNamespace(problem_type='social_security_termination', termination_person=[])
        assert client.post('/api/v1/nocobase/applications/1/termination', json={'account_id': 10, 'confirmed': True}).status_code == 400
        assert coordinator.list() == ()
    finally:
        coordinator.close()


def test_detail_api_adds_chinese_reason_label_and_preserves_submission_code(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator()
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    person = {'id': 2, 'user_name': '测试人员', 'id_card_no': IDENTITIES[0], 'termination_reason': '6304'}
    detail = NocoBaseRightsApplicationDetail(
        application_id=1, code='TEST', status='NEW', title='退保测试', problem_type='social_security_termination',
        created_at=None, initiation_date=None, estimate_time=0, actual_time=0,
        estimate_date=None, actual_date=None, created_by_name='', initiator_name='',
        problem_description='', handling_method='', related_persons=(), attachment_names=(),
        allowed_actions={}, termination_person=(person,),
    )
    app.state.nocobase_query_service.get_application = Mock(return_value=detail)
    try:
        response = TestClient(app).get('/api/v1/nocobase/applications/1')
        assert response.status_code == 200
        row = response.json()['termination_person'][0]
        assert row['termination_reason'] == '6304'
        assert row['termination_reason_label'] == '双方协商一致解除'
        assert 'termination_reason_label' not in person
        assert coordinator.list() == ()
    finally:
        coordinator.close()


def test_uncertain_web_submission_returns_row_results_and_never_retries(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    service = ApplicationOperationService(SimpleNamespace(runtime_root=tmp_path, runtime_settings=Mock(return_value=settings)), Mock(), Mock())
    run_id, items = service.repository.reserve(1, 'termination', people(), account())
    automation = Mock()
    automation.submit_item.side_effect = TerminationSubmissionError('未能确认结果', outcome='unknown')
    context = SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.modules.employment_termination.service.EmploymentTerminationPage', return_value=automation):
        result = service._run(context, run_id, account(), items)
    assert result['unknown_count'] == 1
    assert automation.submit_item.call_count == 1
    assert [row['status'] for row in service.repository.state(1)['people']] == ['unknown', 'not_processed', 'not_processed']
    assert len(service.repository.reserve(1, 'termination', people(), account(11))[1]) == 2


def test_queued_cancellation_releases_reservation_and_uses_print_account_queue(tmp_path):
    import threading
    coordinator = TaskCoordinator(max_workers=2)
    settings_service = SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=account()))
    service = ApplicationOperationService(settings_service, coordinator, Mock())
    release = threading.Event()
    coordinator.submit(title='打印', operation='rights_statement.acquire', kind=TaskKind.JSHRSS_BROWSER,
                               resource_key='10', runner=lambda context: release.wait(3))
    detail = SimpleNamespace(application_id=1, code='TEST', problem_type='social_security_termination', termination_person=[
        {'user_name': '测试', 'id_card_no': IDENTITIES[0], 'termination_reason': '双方协商一致解除'}])
    try:
        queued = service.submit_termination(detail, 10)
        assert queued.status == TaskStatus.QUEUED
        assert service.repository.state(1)['runs'][0]['task_id'] == queued.task_id
        with pytest.raises(HTTPException):
            service.submit_termination(detail, 10)
        coordinator.cancel(queued.task_id)
        assert service.repository.state(1)['people'][0]['status'] == 'not_processed'
        assert service.repository.state(1)['runs'][0]['active'] == 0
    finally:
        release.set()
        coordinator.close()


def medical_detail(rows=None):
    return SimpleNamespace(
        application_id=23, code='MED-023', problem_type='medical_termination',
        med_ins_withdrawal_record=rows if rows is not None else [
            {'id': 1, 'user_name': '甲', 'id_card_no': IDENTITIES[0],
             'med_ins_stop_reason': '在职人员解除/终止劳动合同',
             'med_stop_date': '2026-10-12', 'med_ins_stop_month_fee': '否'},
            {'id': 2, 'user_name': '乙', 'id_card_no': IDENTITIES[1],
             'med_ins_stop_reason': '单位调动',
             'med_stop_date': '2026-10-12', 'med_ins_stop_month_fee': '是'},
        ],
    )


def test_medical_submission_reserves_all_eligible_people_in_medical_queue(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    medical_account = account(20)
    settings_service = SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=medical_account),
                                       runtime_settings=Mock(return_value=settings))
    coordinator = Mock()
    coordinator.submit.return_value = 'queued-task'
    service = ApplicationOperationService(settings_service, coordinator, Mock())

    assert service.submit_medical_termination(medical_detail(), 20) == 'queued-task'
    assert coordinator.submit.call_args.kwargs['kind'] is TaskKind.MEDICAL_BROWSER
    assert coordinator.submit.call_args.kwargs['resource_key'] == '20'
    state = service.repository.state(23)
    assert len(state['people']) == 2
    assert [row['status'] for row in state['people']] == ['queued', 'queued']
    assert all(row['operation'] == 'medical_termination' for row in state['people'])
    settings_service.account.assert_called_once_with(20, SystemType.MEDICAL)


def test_medical_batch_persists_success_then_stops_on_uncertain_result_without_retry(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    service = ApplicationOperationService(
        SimpleNamespace(runtime_root=tmp_path, runtime_settings=Mock(return_value=settings)), Mock(), Mock(),
    )
    first = MedicalTerminationItem(IDENTITIES[0], '人员中断缴费', date(2026, 10, 12), False)
    second = MedicalTerminationItem(IDENTITIES[1], '单位调动', date(2026, 10, 12), True)
    third = MedicalTerminationItem(IDENTITIES[2], '单位调动', date(2026, 10, 12), True)
    context = SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    browser = MagicMock()
    with patch('ehrm.web.application_operations.BrowserManager', return_value=browser), \
         patch('ehrm.web.application_operations.LoginService') as login, \
         patch('ehrm.web.application_operations.MedicalTerminationPage') as automation:
        login.return_value.ensure_external_government_authenticated.return_value = browser.page
        def submit(item, *, before_submit):
            before_submit()
            if item.identity_number == IDENTITIES[1]:
                raise MedicalSubmissionUncertainError('未取得明确结果')
            return '医保平台显示“提交成功”；最终办理结果请在医保平台查询'

        automation.return_value.submit_item.side_effect = submit
        people = ((first, '甲'), (second, '乙'), (third, '丙'))
        run_id, items = service.repository.reserve(23, 'medical_termination', people, account(20))
        result = service._run_medical(context, run_id, account(20), items)
        assert result['submitted_count'] == 1
        assert result['unknown_count'] == 1
        assert result['total'] == 3
        assert [row['status'] for row in result['results']] == ['succeeded', 'unknown', 'not_processed']
        assert [row['status'] for row in service.repository.state(23)['people']] == ['succeeded', 'unknown', 'not_processed']
        assert automation.return_value.submit_item.call_count == 2
        automation.return_value.prepare_next.assert_called_once()
        login.return_value.ensure_external_government_authenticated.assert_called_once()
        assert context.report.call_args.kwargs == {'current': 3, 'total': 3}
        _, retry = service.repository.reserve(23, 'medical_termination', people, account(21))
        assert [item.identity_number for item in retry] == [IDENTITIES[2]]


def test_medical_batch_keeps_success_if_next_form_cannot_be_opened(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    service = ApplicationOperationService(
        SimpleNamespace(runtime_root=tmp_path, runtime_settings=Mock(return_value=settings)), Mock(), Mock(),
    )
    first = MedicalTerminationItem(IDENTITIES[0], '人员中断缴费', date(2026, 10, 12), False)
    second = MedicalTerminationItem(IDENTITIES[1], '单位调动', date(2026, 10, 12), True)
    run_id, items = service.repository.reserve(23, 'medical_termination', ((first, '甲'), (second, '乙')), account(20))
    context = SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalTerminationPage') as automation:
        automation.return_value.submit_item.side_effect = lambda _item, *, before_submit: (
            before_submit(), '医保平台显示“提交成功”'
        )[1]
        automation.return_value.prepare_next.side_effect = ValueError('空白表单未出现')
        result = service._run_medical(context, run_id, account(20), items)
    assert [row['status'] for row in result['results']] == ['succeeded', 'not_processed']
    assert [row['status'] for row in service.repository.state(23)['people']] == ['succeeded', 'not_processed']
    assert result['submitted_count'] == 1
    assert automation.return_value.submit_item.call_count == 1


def test_medical_batch_continues_after_person_not_found_without_submitting_that_person(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    service = ApplicationOperationService(
        SimpleNamespace(runtime_root=tmp_path, runtime_settings=Mock(return_value=settings)), Mock(), Mock(),
    )
    first = MedicalTerminationItem(IDENTITIES[0], '人员中断缴费', date(2026, 10, 12), False)
    second = MedicalTerminationItem(IDENTITIES[1], '单位调动', date(2026, 10, 12), True)
    run_id, items = service.repository.reserve(23, 'medical_termination', ((first, '甲'), (second, '乙')), account(20))
    context = SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalTerminationPage') as automation:
        def fill(item):
            if item.identity_number == IDENTITIES[0]:
                raise EmployeeNotFoundError('不是本单位人员')
        automation.return_value.fill_item.side_effect = fill
        automation.return_value.submit_item.side_effect = lambda _item, *, before_submit: (
            before_submit(), '医保平台显示“提交成功”'
        )[1]
        result = service._run_medical(context, run_id, account(20), items)
    assert [row['status'] for row in result['results']] == ['failed', 'succeeded']
    assert [row['status'] for row in service.repository.state(23)['people']] == ['failed', 'succeeded']
    automation.return_value.prepare_next.assert_called_once()
    assert automation.return_value.submit_item.call_count == 1


def test_medical_input_must_be_complete_before_admission(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    account_service = SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=account(20)))
    service = ApplicationOperationService(account_service, Mock(), Mock())
    row = {**medical_detail().med_ins_withdrawal_record[0], 'med_ins_stop_month_fee': ''}
    with pytest.raises(ValueError, match='必须为“是”或“否”'):
        service.submit_medical_termination(medical_detail([row]), 20)
    assert service.repository.state(23)['people'] == []


def test_medical_admission_skips_previously_succeeded_person_even_if_old_form_fields_are_incomplete(tmp_path):
    repository = ApplicationOperationRepository(tmp_path / 'data' / 'application_operations.sqlite3')
    old = MedicalTerminationItem(IDENTITIES[0], '人员中断缴费', date(2026, 10, 12), False)
    run_id, items = repository.reserve(23, 'medical_termination', ((old, '甲'),), account(20))
    repository.mark(run_id, items[0], 'succeeded', '医保平台显示“提交成功”')
    repository.finish(run_id)
    settings_service = SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=account(20)))
    coordinator = Mock()
    service = ApplicationOperationService(settings_service, coordinator, Mock())
    rows = medical_detail().med_ins_withdrawal_record
    detail = medical_detail([{**rows[0], 'med_stop_date': None}, rows[1]])

    service.submit_medical_termination(detail, 20)

    state = service.repository.state(23)
    assert [row['status'] for row in state['people']] == ['succeeded', 'queued']


def test_medical_api_requires_confirmation_and_has_no_manual_verification_route(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator()
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    app.state.nocobase_query_service.get_application = Mock(return_value=medical_detail())
    client = TestClient(app)
    try:
        submit = f'/api/v1/nocobase/applications/23/medical-termination'
        assert client.post(submit, json={'account_id': 20}).status_code == 400
        verify = f'{submit}/verified'
        assert client.post(verify, json={'person_id': 1, 'confirmed': True}).status_code == 405
        assert coordinator.list() == ()
    finally:
        coordinator.close()


def medical_enrollment_detail(rows=None):
    return SimpleNamespace(
        application_id=24, code='MED-ENROLL-024', problem_type='medical_enrollment',
        med_ins_enrollee=rows if rows is not None else [
            {'id': 1, 'user_name': '甲', 'id_card_no': IDENTITIES[0], 'phone': '13800138000',
             'ethnicity': '汉族', 'arrive_unit_time': '2026-10-12'},
            {'id': 2, 'user_name': '乙', 'id_card_no': IDENTITIES[1], 'phone': '13800138001',
             'ethnicity': '汉族', 'arrive_unit_time': '2026-10-12'},
        ],
    )


def enrollment_service(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    return ApplicationOperationService(
        SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=account(20)),
                        runtime_settings=Mock(return_value=settings)), Mock(), Mock(),
    )


def test_medical_enrollment_admission_uses_medical_queue_and_skips_completed_people(tmp_path):
    service = enrollment_service(tmp_path)
    service.coordinator.submit.return_value = 'queued-task'
    assert service.submit_medical_enrollment(medical_enrollment_detail(), 20) == 'queued-task'
    kwargs = service.coordinator.submit.call_args.kwargs
    assert kwargs['kind'] is TaskKind.MEDICAL_BROWSER
    assert kwargs['resource_key'] == '20'
    assert len(service.repository.state(24)['people']) == 2
    service.settings_service.account.assert_called_once_with(20, SystemType.MEDICAL)

    run_id = service.repository.state(24)['runs'][0]['id']
    item = MedicalPreSubmitItem(IDENTITIES[0], enrollment_date=date(2026, 10, 12), mobile='13800138000')
    service.repository.mark(run_id, item, 'succeeded', '医保平台确认成功')
    service.repository.finish(run_id)
    changed = medical_enrollment_detail([
        {**medical_enrollment_detail().med_ins_enrollee[0], 'arrive_unit_time': None},
        medical_enrollment_detail().med_ins_enrollee[1],
    ])
    service.submit_medical_enrollment(changed, 20)
    state = service.repository.state(24)
    assert [row['status'] for row in state['people'] if row['operation'] == 'medical_enrollment'] == ['succeeded', 'queued']


def test_medical_enrollment_direct_submit_does_not_collect(tmp_path):
    service = enrollment_service(tmp_path)
    people = tuple((MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                         enrollment_date=date(2026, 10, 12)), row['user_name'])
                   for row in medical_enrollment_detail().med_ins_enrollee[:1])
    run_id, items = service.repository.reserve(24, 'medical_enrollment', people, account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    collection = Mock()
    enrollment.submit_enrollment.side_effect = lambda _item, *, before_submit: (
        before_submit(), '医保平台提示办理成功；结果列表已确认'
    )[1]
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage',
               side_effect=lambda _page, stage, **_kw: enrollment if stage is MedicalStage.ENROLLMENT else collection):
        result = service._run_medical_enrollment(context, run_id, account(20), items)
    assert result['submitted_count'] == 1
    assert result['existing_count'] == 0
    assert service.repository.state(24)['people'][0]['status'] == 'succeeded'
    enrollment.submit_enrollment.assert_called_once()
    collection.fill_item.assert_not_called()
    collection.submit_collection.assert_not_called()


@pytest.mark.parametrize('retained_previous', [False, True])
@pytest.mark.parametrize('form_active', [False, True])
def test_medical_enrollment_prepares_next_person_using_identity_field(tmp_path, retained_previous, form_active):
    service = enrollment_service(tmp_path)
    people = tuple((MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                         enrollment_date=date(2026, 10, 12)), row['user_name'])
                   for row in medical_enrollment_detail().med_ins_enrollee)
    run_id, items = service.repository.reserve(24, 'medical_enrollment', people, account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    enrollment._enrollment_form_is_active.return_value = form_active
    identity = enrollment._enrollment_identity.return_value
    if retained_previous:
        identity.input_value.side_effect = [items[0].identity_number, '']
        enrollment._perform.side_effect = lambda action: action()
    else:
        identity.input_value.return_value = ''
    enrollment.submit_enrollment.side_effect = lambda _item, *, before_submit: (
        before_submit(), '医保平台提示办理成功；结果列表已确认'
    )[1]
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.is_medical_portal_ready', return_value=not form_active), \
         patch('ehrm.web.application_operations.verify_existing_medical_session') as reload_check, \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage', return_value=enrollment):
        result = service._run_medical_enrollment(context, run_id, account(20), items)

    assert result['submitted_count'] == 2
    assert enrollment.open.call_count == 1
    enrollment._enrollment_identity.assert_called_once()
    if retained_previous:
        identity.fill.assert_called_once_with('')
    else:
        identity.fill.assert_not_called()
    assert enrollment.submit_enrollment.call_count == 2
    reload_check.assert_not_called()


@pytest.mark.parametrize('collection_result', ['existing', 'saved'])
def test_medical_enrollment_only_collects_after_archive_prompt_then_requeries(tmp_path, collection_result):
    service = enrollment_service(tmp_path)
    row = medical_enrollment_detail().med_ins_enrollee[0]
    item = MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                enrollment_date=date(2026, 10, 12))
    run_id, items = service.repository.reserve(24, 'medical_enrollment', ((item, row['user_name']),), account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    collection = Mock()
    enrollment.fill_item.side_effect = [MedicalPreSubmitBlockedError('请先给该人员建档!', outcome='需先建档'), None]
    collection.submit_collection.side_effect = lambda _item, *, before_submit: (before_submit(), collection_result)[1]
    enrollment.submit_enrollment.side_effect = lambda _item, *, before_submit: (before_submit(), '办理成功')[1]
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage',
               side_effect=lambda _page, stage, **_kw: enrollment if stage is MedicalStage.ENROLLMENT else collection):
        result = service._run_medical_enrollment(context, run_id, account(20), items)
    assert result['submitted_count'] == 1
    assert enrollment.fill_item.call_count == 2
    collection.fill_item.assert_called_once()
    collection.submit_collection.assert_called_once()
    states = {row['operation']: row for row in service.repository.state(24)['people']}
    assert states['medical_information_collection']['status'] == 'succeeded'
    assert ('已经建档' if collection_result == 'existing' else '建档成功') in states['medical_information_collection']['message']
    assert states['medical_enrollment']['status'] == 'succeeded'


def test_medical_collection_uncertain_result_blocks_enrollment_and_retry(tmp_path):
    service = enrollment_service(tmp_path)
    row = medical_enrollment_detail().med_ins_enrollee[0]
    item = MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                enrollment_date=date(2026, 10, 12))
    run_id, items = service.repository.reserve(24, 'medical_enrollment', ((item, row['user_name']),), account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    collection = Mock()
    enrollment.fill_item.side_effect = MedicalPreSubmitBlockedError('请先给该人员建档!', outcome='需先建档')
    def uncertain(_item, *, before_submit):
        before_submit()
        raise MedicalEnrollmentSubmissionUncertainError('建档提交结果不明确')
    collection.submit_collection.side_effect = uncertain
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage',
               side_effect=lambda _page, stage, **_kw: enrollment if stage is MedicalStage.ENROLLMENT else collection):
        result = service._run_medical_enrollment(context, run_id, account(20), items)
    assert result['unknown_count'] == 1
    enrollment.submit_enrollment.assert_not_called()
    states = {row['operation']: row for row in service.repository.state(24)['people']}
    assert states['medical_information_collection']['status'] == 'unknown'
    assert states['medical_enrollment']['status'] == 'unknown'
    with pytest.raises(HTTPException, match='人员均已成功办理或结果待确认'):
        service.repository.reserve(24, 'medical_enrollment', ((item, row['user_name']),), account(21))


def test_medical_enrollment_accepts_existing_archive_notice_before_collection_submit(tmp_path):
    service = enrollment_service(tmp_path)
    row = medical_enrollment_detail().med_ins_enrollee[0]
    item = MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                enrollment_date=date(2026, 10, 12))
    run_id, items = service.repository.reserve(24, 'medical_enrollment', ((item, row['user_name']),), account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    collection = Mock()
    enrollment.fill_item.side_effect = [MedicalPreSubmitBlockedError('请先给该人员建档!', outcome='需先建档'), None]
    collection.fill_item.side_effect = MedicalPreSubmitBlockedError('该人员已经建档!', outcome='已建档')
    enrollment.submit_enrollment.side_effect = lambda _item, *, before_submit: (before_submit(), '办理成功')[1]
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage',
               side_effect=lambda _page, stage, **_kw: enrollment if stage is MedicalStage.ENROLLMENT else collection):
        result = service._run_medical_enrollment(context, run_id, account(20), items)
    assert result['submitted_count'] == 1
    collection.submit_collection.assert_not_called()
    collection.dismiss_archive_notice.assert_called_once_with('已经建档')
    enrollment.dismiss_archive_notice.assert_called_once_with('请先给该人员建档')


def test_medical_enrollment_uncertain_submit_blocks_retry_and_later_people(tmp_path):
    service = enrollment_service(tmp_path)
    people = tuple((MedicalPreSubmitItem(row['id_card_no'], row['user_name'], row['phone'], row['ethnicity'],
                                         enrollment_date=date(2026, 10, 12)), row['user_name'])
                   for row in medical_enrollment_detail().med_ins_enrollee)
    run_id, items = service.repository.reserve(24, 'medical_enrollment', people, account(20))
    context = SimpleNamespace(report=Mock(), raise_if_cancelled=Mock())
    enrollment = Mock()
    collection = Mock()
    def uncertain(_item, *, before_submit):
        before_submit()
        raise MedicalEnrollmentSubmissionUncertainError('医保平台结果不明确')
    enrollment.submit_enrollment.side_effect = uncertain
    with patch('ehrm.web.application_operations.BrowserManager', return_value=MagicMock()), \
         patch('ehrm.web.application_operations.LoginService'), \
         patch('ehrm.web.application_operations.MedicalEnrollmentSubmissionPage',
               side_effect=lambda _page, stage, **_kw: enrollment if stage is MedicalStage.ENROLLMENT else collection):
        result = service._run_medical_enrollment(context, run_id, account(20), items)
    assert [row['status'] for row in result['results']] == ['unknown', 'not_processed']
    assert enrollment.submit_enrollment.call_count == 1
    _, retry = service.repository.reserve(24, 'medical_enrollment', people, account(21))
    assert [item.identity_number for item in retry] == [IDENTITIES[1]]


def test_medical_enrollment_api_requires_confirmation(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator()
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    query = app.state.nocobase_query_service
    query.get_application = Mock(return_value=medical_enrollment_detail())
    try:
        response = TestClient(app).post('/api/v1/nocobase/applications/24/medical-enrollment',
                                        json={'account_id': 20})
        assert response.status_code == 400
        query.get_application.assert_not_called()
        assert coordinator.list() == ()
    finally:
        coordinator.close()
