from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
import json

import pytest

from ehrm.core.settings import load_settings
from ehrm.core.exceptions import QueryValidationError
from ehrm.modules.employment_enrollment.models import EmploymentEnrollmentItem
from ehrm.modules.person_information_collection.models import PersonInformationItem
from ehrm.modules.social_submission import (
    COLLECTION_PATH, COMPLETE_PATH, ENROLLMENT_PATH, SAVE_PATH,
    SocialSubmissionError, SocialSubmissionMonitor,
)

IDENTITY = '320101199001011234'


def collection_item():
    return PersonInformationItem(IDENTITY, '测试人员', '13800000000', '汉族', '本省城镇', ('江苏省', '南京市', '测试区', '测试街道', '测试社区')).normalized()


def enrollment_item():
    return EmploymentEnrollmentItem(IDENTITY, '新签', '固定期限', '2026-10-01', '2029-09-30', '专业技术人员', '5000', management='0').normalized()


def enrollment_payload():
    return {'idNumber': IDENTITY, 'personId': 123, 'personUniqueId': '123', 'applyId': 'current-application',
            'contractAddReasons': '1', 'contractAddType': '41', 'positionType': '03', 'insuredIdentity': '101',
            'wages': '5000.0', 'management': '0',
            'contractBDate': int(datetime(2026, 10, 1, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() * 1000),
            'contractEDate': int(datetime(2029, 9, 30, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() * 1000)}


def response(path, payload, data, *, status=200):
    return SimpleNamespace(url='https://rs.jshrss.jiangsu.gov.cn' + path, status=status,
                           request=SimpleNamespace(method='POST', resource_type='xhr', post_data=json.dumps(payload)),
                           json=lambda: data, text=lambda: '' if data is None else json.dumps(data))


def monitor(tmp_path, operation='enrollment'):
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    return SocialSubmissionMonitor(Mock(), settings, collection_item() if operation == 'information_collection' else enrollment_item(), operation=operation)


def populate(monitor, *, body=None, success=True):
    payload = enrollment_payload()
    body = body if body is not None else {'appcode': -1, 'errmsg': '未提供错误信息', 'personUniqueId': 123, 'personUniqId': 123, 'ok': success}
    monitor.capture(response(SAVE_PATH, payload, None))
    monitor.capture(response(ENROLLMENT_PATH, payload, body, status=201))
    # The actual site saves both before and after the business submission.
    monitor.capture(response(SAVE_PATH, payload, None))
    monitor.capture(response(COMPLETE_PATH, {'encryptData': 'not-replayed'}, {'appcode': '0', 'map': {'data': {'busiId': payload['applyId'], 'complete': False, 'message': None}}}))


def test_enrollment_requires_current_success_page_and_accepts_recorded_placeholder_codes(tmp_path):
    observed = monitor(tmp_path)
    populate(observed)
    assert observed.receipt(success_visible=False) is None
    receipt = observed.receipt(success_visible=True)
    assert receipt.outcome == 'submitted'
    assert receipt.application_id == 'current-application'


@pytest.mark.parametrize('missing', [ENROLLMENT_PATH, SAVE_PATH, COMPLETE_PATH])
def test_success_page_alone_or_incomplete_network_never_counts_as_success(tmp_path, missing):
    observed = monitor(tmp_path)
    populate(observed)
    observed.responses[missing].clear()
    assert observed.receipt(success_visible=True) is None


def test_already_collected_http_400_preserves_platform_message(tmp_path):
    observed = monitor(tmp_path, 'information_collection')
    message = f'证件号为{IDENTITY}的人员信息已采集,人员编号为123456789'
    observed.capture(response(COLLECTION_PATH, {'personBasicInfoDTO': {'certificateNumber': IDENTITY, 'name': '测试人员', 'mobile': '13800000000', 'applyId': 'collection-1'}},
                              {'status': 400, 'code': '1111', 'message': message}, status=400))
    receipt = observed.receipt(success_visible=False)
    assert receipt.outcome == 'existing'
    assert receipt.message == message


@pytest.mark.parametrize('body', [
    {'appcode': -1, 'errmsg': '业务冲突', 'ok': True, 'personUniqueId': 123, 'personUniqId': 123},
    {'appcode': 0},
    {'appcode': -1, 'errmsg': '未提供错误信息', 'ok': True, 'personUniqueId': 124, 'personUniqId': 123},
    {'appcode': -1, 'errmsg': '未提供错误信息', 'ok': True, 'personUniqueId': 123},
])
def test_conflicting_or_unrecognized_responses_are_uncertain(tmp_path, body):
    observed = monitor(tmp_path)
    populate(observed, body=body)
    with pytest.raises(SocialSubmissionError) as error:
        observed.receipt(success_visible=True)
    assert error.value.outcome == 'unknown'


def test_explicit_rejection_returns_real_message_and_failed_state(tmp_path):
    observed = monitor(tmp_path)
    populate(observed, body={'ok': False, 'errmsg': '当前人员不能办理参保'})
    with pytest.raises(SocialSubmissionError, match='当前人员不能办理参保') as error:
        observed.receipt(success_visible=True)
    assert error.value.outcome == 'failed'


@pytest.mark.parametrize('key,value', [
    ('idNumber', '320101199002021235'), ('applyId', ''), ('contractAddType', '42'),
    ('wages', '1'), ('contractBDate', 0), ('management', '1'),
])
def test_request_person_and_contract_must_match_current_row(tmp_path, key, value):
    observed = monitor(tmp_path)
    populate(observed)
    payload = {**enrollment_payload(), key: value}
    observed.responses[ENROLLMENT_PATH][0].request.post_data = json.dumps(payload)
    with pytest.raises(SocialSubmissionError):
        observed.receipt(success_visible=True)


def test_wrong_completion_and_duplicate_submissions_are_never_success(tmp_path):
    observed = monitor(tmp_path)
    populate(observed)
    observed.responses[COMPLETE_PATH] = [response(COMPLETE_PATH, {}, {'appcode': '0', 'map': {'data': {'busiId': 'previous-person'}}})]
    with pytest.raises(SocialSubmissionError, match='收尾'):
        observed.receipt(success_visible=True)
    observed.responses[ENROLLMENT_PATH].append(observed.responses[ENROLLMENT_PATH][0])
    with pytest.raises(SocialSubmissionError, match='重复'):
        observed.receipt(success_visible=True)


def test_already_collected_for_another_person_is_uncertain(tmp_path):
    observed = monitor(tmp_path, 'information_collection')
    observed.capture(response(COLLECTION_PATH, {'personBasicInfoDTO': {'certificateNumber': IDENTITY, 'name': '测试人员', 'mobile': '13800000000', 'applyId': 'collection-1'}},
                              {'code': '1111', 'message': '证件号为320101199002021235的人员信息已采集,人员编号为123456789'}, status=400))
    with pytest.raises(SocialSubmissionError, match='其他人员'):
        observed.receipt(success_visible=False)


def test_management_is_validated_before_browser_entry():
    assert enrollment_item().management == '0'
    with pytest.raises(QueryValidationError, match='管理技术岗'):
        replace(enrollment_item(), management='wrong').normalized()
