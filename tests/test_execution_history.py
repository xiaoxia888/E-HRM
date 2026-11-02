from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ehrm.core.auth_repository import SystemType
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.excel_models import EmployeeRecord
from ehrm.web.app import create_app
from ehrm.web.execution_context import nocobase_context, rights_context
from ehrm.web.execution_history import ExecutionHistoryService
from ehrm.web.task_repository import TaskRepository
from ehrm.web.tasks import TaskCoordinator, TaskKind, TaskSnapshot, TaskStatus, wait_until


def snapshot(task_id='task1', **changes):
    task = TaskSnapshot(task_id=task_id, title='获取社保权益单', operation='rights_statement.acquire',
                        kind=TaskKind.JSHRSS_BROWSER, status=TaskStatus.SUCCEEDED, resource_label='执行时单位',
                        queue_position=0, message='结束', progress_current=1, progress_total=1,
                        created_at='2026-10-25T16:00:00+00:00', started_at=None, finished_at='2026-10-26T01:00:00Z',
                        result={'items': [{'row_number': 2, 'success': True, 'message': '成功'}, {'row_number': 3, 'success': False, 'message': '平台提示'}]}, error='')
    return replace(task, **changes)


def account():
    return SimpleNamespace(id=10, display_name='南化建社保账号', account='test-account-01', password='SECRET_PASSWORD',
                           secondary_account='SECRET_SECONDARY', api_key='SECRET_API_KEY', system_type=SystemType.JSHRSS,
                           profile={'login_method': 'government_sso', 'access_token': 'SECRET_TOKEN'})


def business_context():
    return {'account': {'id': 10, 'display_name': '执行时单位', 'masked_account': 'te****01'}, 'applications': [
        {'source': 'erp', 'transaction_type': '单位社保权益单', 'title': '申请甲', 'erp_code': 'ERP-001',
         'application_code': '', 'initiator': '发起人甲', 'initiated_at': '2026-10-20', 'problem_description': '问题描述甲',
         'handling_method': '处理方式甲', 'snapshot_origin': 'captured', 'people': [{'name': '人员甲', 'identity_number': '320101199001011234', 'row_number': '2'}]},
        {'source': 'erp', 'transaction_type': '社保咨询', 'title': '申请乙', 'erp_code': 'ERP-002',
         'application_code': '', 'initiator': '发起人乙', 'initiated_at': '2026-10-21', 'snapshot_origin': 'captured',
         'people': [{'name': '人员乙', 'identity_number': '320101199002021235', 'row_number': '3'}]},
    ]}


def history(repository, tmp_path, **kwargs):
    rights = kwargs.get('rights') or SimpleNamespace(artifacts=SimpleNamespace(resolve=lambda _: None), import_root=tmp_path)
    operations = kwargs.get('operations') or Mock()
    return ExecutionHistoryService(repository, SimpleNamespace(get=lambda _: None), rights, operations, Mock())


def test_recorded_context_is_atomic_immutable_and_does_not_expand_task_stream(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    coordinator = TaskCoordinator(max_workers=1, store=repository)
    metadata = business_context()
    observed = []

    def runner(context):
        saved = repository.execution_record(context.task_id, 0)
        assert saved['application']['title'] == '申请甲'
        mutable = context.business_context
        mutable['applications'][0]['title'] = 'worker changed'
        observed.append(context.business_context['applications'][0]['title'])
        return {'ok': True}

    try:
        task = coordinator.submit(title='获取社保权益单', operation='rights_statement.acquire', kind=TaskKind.JSHRSS_BROWSER,
                                  resource_key='10', runner=runner, business_context=metadata)
        metadata['applications'][0]['title'] = 'later edited'
        assert wait_until(lambda: coordinator.get(task.task_id).status.terminal)
        assert coordinator.get(task.task_id).status == TaskStatus.SUCCEEDED
        assert observed == ['申请甲']
        assert 'business_context' not in task.to_dict()
        assert 'identity_number' not in json.dumps(task.to_dict())
        assert TaskRepository(repository.database_path).execution_record(task.task_id, 0)['application']['title'] == '申请甲'
    finally:
        coordinator.close()


def test_registration_rolls_back_task_and_context_if_any_application_is_invalid(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    metadata = business_context()
    metadata['applications'][1]['title'] = {'invalid': 'SQL value'}
    with pytest.raises(sqlite3.ProgrammingError):
        repository.save_submission(snapshot(), metadata)
    assert repository.get('task1') is None
    assert repository.execution_records()['total'] == 0


def test_context_survives_progress_updates_and_same_registration_does_not_overwrite(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    repository.save_submission(snapshot(), business_context())
    changed = business_context()
    changed['applications'][0]['title'] = 'new title'
    repository.save_submission(snapshot(status=TaskStatus.FAILED), changed)
    repository.save(snapshot(status=TaskStatus.SUCCEEDED))
    assert repository.execution_record('task1', 0)['application']['title'] == '申请甲'
    assert repository.execution_records()['total'] == 2


def test_list_splits_batch_by_application_searches_and_scopes_each_result(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    repository.save_submission(snapshot(), business_context())
    service = history(repository, tmp_path)
    result = service.list(page=1, page_size=1)
    assert result['total'] == 2
    assert len(result['records']) == 1
    assert result['records'][0]['outcome'] == 'succeeded'
    assert 'identity_number' not in json.dumps(result)
    assert 'people' not in result['records'][0]
    selected = service.list(keyword='ERP-002', page=1, page_size=20)
    assert selected['total'] == 1
    assert selected['records'][0]['outcome'] == 'failed'
    assert service.list(keyword='发起人甲')['total'] == 1
    assert service.list(keyword='执行时单位')['total'] == 2
    assert service.list(keyword='%')['total'] == 0
    assert service.list(start_date=date(2026, 10, 26), end_date=date(2026, 10, 26))['total'] == 2
    assert service.list(end_date=date(2026, 10, 25))['total'] == 0
    detail = service.detail('task1', 1)
    assert detail['people'][0]['name'] == '人员乙'
    assert detail['people'][0]['message'] == '平台提示'
    assert detail['task']['result']['failed'] == 1
    assert detail['task']['result']['succeeded'] == 0
    assert len(detail['task']['result']['items']) == 1


def test_more_than_500_records_remain_searchable_and_paginated(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    for index in range(505):
        repository.save_submission(snapshot(f'task-{index}'), {'account': {}, 'applications': [business_context()['applications'][0]]})
    result = history(repository, tmp_path).list(page=26, page_size=20)
    assert result['total'] == 505
    assert len(result['records']) == 5


def test_context_builders_keep_explicit_erp_number_and_exclude_credentials_and_raw_data():
    detail = SimpleNamespace(application_id=1, code='NOCO-001', erp_code='ERP-001', problem_type='social_security_rights',
                             title='标题', initiator_name='发起人', initiation_date=datetime(2026, 10, 26, tzinfo=UTC),
                             problem_description='问题', handling_method='处理', erp_all_field_value={'Code': 'ERP-old', 'access_token': 'SECRET_RAW'},
                             related_persons=({'user_name': '人员', 'id_card_no': '320101199001011234', 'cookie': 'SECRET_COOKIE'},))
    context = nocobase_context(detail, account())
    assert context['applications'][0]['erp_code'] == 'ERP-001'
    assert context['applications'][0]['application_code'] == 'NOCO-001'
    assert context['account']['masked_account'] != account().account
    assert 'SECRET' not in json.dumps(context)
    records = [EmployeeRecord(row_number=2, unit='单位', department='部门', name='甲', identity_number='320101199001011234',
                              insurance_type='养老', start_month='202510', end_month='202609', task_number='ERP-001')]
    context = rights_context(records, account(), erp_state={'tasks': [{'task_number': 'ERP-001', 'title': 'ERP 标题', 'originator': 'ERP 发起人', 'application_date': '2026-10-20', 'transaction_type': '社保咨询'}]})
    assert context['applications'][0]['title'] == 'ERP 标题'
    assert context['applications'][0]['people'][0]['company'] == '单位'


def test_erp_upload_person_result_uses_upload_outcome_not_prior_pdf_success(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    repository.save_submission(snapshot(operation='erp.rights.upload', result={'items': [
        {'row_number': 2, 'success': True, 'message': 'PDF 下载成功', 'erp_success': False, 'erp_message': 'ERP 附件上传失败'}
    ]}), {'account': {}, 'applications': [business_context()['applications'][0]]})
    result = history(repository, tmp_path).detail('task1', 0)
    assert result['outcome'] == 'failed'
    assert result['people'][0]['status'] == 'failed'
    assert result['people'][0]['message'] == 'ERP 附件上传失败'


def test_legacy_context_recovery_never_overwrites_a_newer_task_result(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    repository.save(snapshot(status=TaskStatus.RUNNING, result=None))
    service = history(repository, tmp_path)
    original = service._legacy_context
    def recovered(task):
        repository.save(snapshot(status=TaskStatus.SUCCEEDED))
        return original(task)
    service._legacy_context = recovered
    service.restore_history()
    assert repository.get('task1').status == TaskStatus.SUCCEEDED
    assert repository.get('task1').result is not None
    assert repository.execution_record('task1', 0)['application']['snapshot_origin'] == 'unavailable'


def test_legacy_rights_record_recovers_erp_metadata_from_matching_local_file(tmp_path):
    repository = TaskRepository(tmp_path / 'tasks.sqlite3')
    repository.save(snapshot(result={'artifacts': [{'name': 'result.xlsx', 'url': '/api/v1/artifacts/token'}]}))
    import_id = 'a' * 32
    workbook = tmp_path / f'{import_id}_执行结果.xlsx'
    workbook.write_bytes(b'loader-mocked')
    (tmp_path / f'{import_id}.json').write_text(json.dumps({'tasks': [{'task_number': 'ERP-001', 'title': '原始标题', 'originator': '原始发起人', 'application_date': '2026-10-20'}]}))
    records = [EmployeeRecord(row_number=2, unit='单位', department='部门', name='甲', identity_number='320101199001011234', insurance_type='养老', start_month='202510', end_month='202609', task_number='ERP-001')]
    rights = SimpleNamespace(artifacts=SimpleNamespace(resolve=lambda _: workbook), import_root=tmp_path, loader=SimpleNamespace(load=lambda _: records))
    service = history(repository, tmp_path, rights=rights)
    rows = service.list()['records']
    assert rows[0]['title'] == '原始标题'
    assert rows[0]['erp_code'] == 'ERP-001'
    assert rows[0]['snapshot_origin'] == 'recovered'
    assert service.list()['total'] == 1


def test_execution_api_validates_filters_and_returns_detail_only_on_open(tmp_path):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    coordinator = TaskCoordinator(max_workers=1)
    app = create_app(settings=settings, logger=Mock(), coordinator=coordinator)
    app.state.task_repository.save_submission(snapshot(), business_context())
    try:
        client = TestClient(app)
        result = client.get('/api/v1/executions?keyword=ERP-001').json()
        assert result['total'] == 1
        assert 'identity_number' not in json.dumps(result)
        detail = client.get('/api/v1/executions/task1/0').json()
        assert detail['application']['problem_description'] == '问题描述甲'
        assert detail['application']['handling_method'] == '处理方式甲'
        assert detail['people'][0]['identity_number'] == '320101199001011234'
        assert client.get('/api/v1/executions/missing/0').status_code == 404
        assert client.get('/api/v1/executions?page=0').status_code == 422
        assert client.get('/api/v1/executions?page_size=101').status_code == 422
        assert client.get('/api/v1/executions?operation=bad').status_code == 400
        assert client.get('/api/v1/executions?start_date=2026-10-27&end_date=2026-10-26').status_code == 400
    finally:
        coordinator.close()
