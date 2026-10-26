from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ehrm.core.auth_repository import SystemType
from ehrm.core.exceptions import QueryValidationError, TaskCancelledError
from ehrm.core.settings import load_settings
from ehrm.modules.social_submission import SocialSubmissionError, SocialSubmissionReceipt
from ehrm.web.app import create_app
from ehrm.web.application_operations import ApplicationOperationService
from ehrm.web.tasks import TaskCoordinator, TaskKind, TaskStatus


def detail(rows=None):
    region = None
    for index, name in enumerate(('江苏省', '南京市', '测试区', '测试街道', '测试社区')):
        region = {'id': index + 1, 'name': name, 'parentId': index or None, 'parent': region}
    people = [{'id': index, 'user_name': f'测试人员{index}', 'id_card_no': identity, 'phone': '13800000000',
               'ethnicity': '汉族', 'household_type': '本省城镇', 'administrative_division_id': 5, 'household_region': region,
               'contract_add_reason': '新签', 'contract_type': '固定期限', 'contract_start_date': '2026-10-01',
               'contract_end_date': '2029-09-30', 'job_type': '专业技术人员', 'insurance_identity': '企业职工',
               'monthly_contribution_salary': 5000, 'is_technology': '0'}
              for index, identity in enumerate(('320101199001011234', '320101199002021235', '320101199003031236'), 1)]
    return SimpleNamespace(application_id=1, code='TEST-1', problem_type='social_security_enrollment', insurance_person=tuple(people if rows is None else rows))


def service(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    account = SimpleNamespace(id=10, display_name='测试社保单位', account='test', password='not-used')
    return ApplicationOperationService(SimpleNamespace(runtime_root=tmp_path, account=Mock(return_value=account),
                                                      runtime_settings=Mock(return_value=settings)), Mock(), Mock())


@pytest.mark.parametrize('operation', ['information_collection', 'enrollment'])
def test_social_admission_maps_fields_and_uses_the_selected_social_account_queue(tmp_path, operation):
    worker = service(tmp_path)
    worker.submit_social(detail(), 10, operation=operation)
    worker.settings_service.account.assert_called_once_with(10, SystemType.JSHRSS)
    submitted = worker.coordinator.submit.call_args.kwargs
    assert submitted['kind'] == TaskKind.JSHRSS_BROWSER
    assert submitted['resource_key'] == '10'
    assert submitted['operation'].startswith(f'application.{operation}:')
    run_id = worker.repository.state(1)['runs'][0]['id']
    with pytest.raises(HTTPException, match='正在执行'):
        worker.submit_social(detail(), 11, operation='enrollment' if operation == 'information_collection' else 'information_collection')
    assert worker.repository.state(1)['runs'][0]['active'] == 1
    with patch.object(worker, '_run_social') as runner:
        submitted['runner'](Mock())
    _, actual_run, _, items = runner.call_args.args
    assert actual_run == run_id
    if operation == 'information_collection':
        assert items[0].address == ('江苏省', '南京市', '测试区', '测试街道', '测试社区')
    else:
        assert items[0].management == '0'
        assert items[0].position_type.value == '03'


@pytest.mark.parametrize('operation,changes', [
    ('information_collection', {'household_region': None}),
    ('information_collection', {'phone': ''}),
    ('information_collection', {'household_region': {'id': 5, 'name': '社区', 'parentId': 4}}),
    ('enrollment', {'is_technology': ''}), ('enrollment', {'job_type': ''}),
    ('enrollment', {'contract_start_date': 'bad'}), ('enrollment', {'monthly_contribution_salary': None}),
])
def test_incomplete_data_is_rejected_before_task_or_browser_start(tmp_path, operation, changes):
    worker = service(tmp_path)
    row = {**detail().insurance_person[0], **changes}
    with pytest.raises((ValueError, QueryValidationError)):
        worker.submit_social(detail([row]), 10, operation=operation)
    worker.coordinator.submit.assert_not_called()
    assert worker.repository.state(1)['runs'] == []


def run_worker(worker, operation, outcomes, context=None):
    worker.submit_social(detail(), 10, operation=operation)
    submitted = worker.coordinator.submit.call_args.kwargs
    receipts = iter(outcomes)

    def submitter(*args, **kwargs):
        def run(*, before_submit):
            before_submit()
            outcome = next(receipts)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return SimpleNamespace(run=run)

    context = context or SimpleNamespace(cancelled=False, report=Mock(), raise_if_cancelled=Mock())
    with patch('ehrm.web.application_operations.BrowserManager'), patch('ehrm.web.application_operations.LoginService'), \
            patch('ehrm.web.application_operations.PersonInformationPage'), patch('ehrm.web.application_operations.EmploymentEnrollmentPage'), \
            patch('ehrm.web.application_operations.SocialSubmitter', side_effect=submitter) as submit:
        result = submitted['runner'](context)
    return result, submit


def test_existing_collection_is_distinct_and_preserves_platform_message_across_restart(tmp_path):
    worker = service(tmp_path)
    message = '证件号为320101199001011234的人员信息已采集,人员编号为123456789'
    result, submit = run_worker(worker, 'information_collection', [SocialSubmissionReceipt('existing', message)] * 3)
    assert result.status == TaskStatus.SUCCEEDED
    assert result.result['submitted_count'] == 0
    assert result.result['existing_count'] == 3
    assert submit.call_count == 3
    assert [row['status'] for row in worker.repository.state(1)['people']] == ['existing'] * 3
    assert worker.repository.state(1)['people'][0]['message'] == message
    restarted = service(tmp_path)
    with pytest.raises(HTTPException, match='平台已采集'):
        restarted.submit_social(detail(), 10, operation='information_collection')
    # Collection does not mark enrollment done or block its independent action.
    restarted.submit_social(detail(), 10, operation='enrollment')


def test_partial_enrollment_stops_after_unknown_preserves_prior_success_and_blocks_retry(tmp_path):
    worker = service(tmp_path)
    result, submit = run_worker(worker, 'enrollment', [SocialSubmissionReceipt('submitted', '业务办理成功'), SocialSubmissionError('等待加载超时；结果待确认')])
    assert result.status == TaskStatus.FAILED
    assert result.result['submitted_count'] == result.result['unknown_count'] == 1
    assert submit.call_count == 2
    assert [row['status'] for row in worker.repository.state(1)['people']] == ['succeeded', 'unknown', 'not_processed']
    worker.submit_social(detail(), 10, operation='enrollment')
    with patch.object(worker, '_run_social') as runner:
        worker.coordinator.submit.call_args.kwargs['runner'](Mock())
    assert len(runner.call_args.args[3]) == 1
    assert runner.call_args.args[3][0].source_index == 3


def test_known_business_rejection_is_failed_and_stops_later_people(tmp_path):
    result, submit = run_worker(service(tmp_path), 'enrollment', [SocialSubmissionError('当前人员不符合参保条件', outcome='failed')])
    assert result.status == TaskStatus.FAILED
    assert result.result['unknown_count'] == 0
    assert result.result['results'][0]['status'] == 'failed'
    assert submit.call_count == 1


def test_cancellation_after_mutation_recovers_unknown_and_does_not_repeat(tmp_path):
    worker = service(tmp_path)
    with pytest.raises(TaskCancelledError):
        run_worker(worker, 'enrollment', [TaskCancelledError('停止')])
    assert [row['status'] for row in worker.repository.state(1)['people']] == ['unknown', 'not_processed', 'not_processed']
    assert worker.repository.state(1)['runs'][0]['active'] == 0


@pytest.mark.parametrize('operation', ['information_collection', 'enrollment'])
def test_queued_cancellation_releases_each_social_operation_reservation(tmp_path, operation):
    worker = service(tmp_path)
    worker.submit_social(detail(), 10, operation=operation)
    submitted = worker.coordinator.submit.call_args.kwargs
    worker.repository.observe(SimpleNamespace(operation=submitted['operation'], task_id='cancelled-task', status=TaskStatus.CANCELLED))
    state = worker.repository.state(1)
    assert state['runs'][0]['active'] == 0
    assert state['runs'][0]['task_id'] == 'cancelled-task'
    assert all(row['status'] == 'not_processed' for row in state['people'])


@pytest.mark.parametrize('endpoint,operation', [('information-collection', 'information_collection'), ('enrollment', 'enrollment')])
def test_social_endpoints_require_confirmation_and_forward_selected_account(tmp_path, endpoint, operation):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    try:
        app.state.nocobase_query_service.get_application = Mock(return_value=detail())
        with TestClient(app) as client, patch.object(app.state.application_operations, 'submit_social') as submit:
            assert client.post(f'/api/v1/nocobase/applications/1/{endpoint}', json={'account_id': 10}).status_code == 400
            submit.assert_not_called()
            task = coordinator.submit(title='mock', operation=f'application.{operation}:test', kind=TaskKind.API_QUERY, runner=lambda _: {})
            submit.return_value = task
            response = client.post(f'/api/v1/nocobase/applications/1/{endpoint}', json={'account_id': 10, 'confirmed': True})
            assert response.status_code == 200
            assert response.json()['operation'] == task.operation
            submit.assert_called_once_with(app.state.nocobase_query_service.get_application.return_value, 10, operation=operation)
    finally:
        coordinator.close()
