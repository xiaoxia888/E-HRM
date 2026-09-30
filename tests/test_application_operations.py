from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from ehrm.core.settings import load_settings
from ehrm.core.exceptions import TaskCancelledError
from ehrm.modules.employment_termination.models import EmploymentTerminationItem
from ehrm.modules.employment_termination.service import EmploymentTerminationService
from ehrm.modules.employment_termination.submission import TerminationSubmissionError
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
