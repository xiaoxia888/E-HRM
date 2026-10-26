"""Exercise the recorded response contracts in a local, fully intercepted DOM."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from time import monotonic
from unittest.mock import Mock
import json

import pytest
from playwright.sync_api import sync_playwright

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.browser.smart_wait import SmartWait
from ehrm.core.settings import load_settings
from ehrm.modules.social_submission import (
    COLLECTION_PATH, COMPLETE_PATH, ENROLLMENT_PATH, SAVE_PATH, SocialSubmissionError, SocialSubmitter,
)
from test_social_submission import IDENTITY, collection_item, enrollment_item, enrollment_payload


@pytest.fixture
def browser_page(tmp_path):
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip('本地回归需要安装 Playwright Chromium')
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()


def arrange(page, tmp_path, *, operation='enrollment', mode='success', delay_ms=700):
    item = collection_item() if operation == 'information_collection' else enrollment_item()
    payload = ({'personBasicInfoDTO': {'certificateNumber': IDENTITY, 'name': '测试人员', 'mobile': '13800000000', 'applyId': 'current-application'}}
               if operation == 'information_collection' else enrollment_payload())
    apply_path = COLLECTION_PATH if operation == 'information_collection' else ENROLLMENT_PATH
    calls = []
    # Both calls and all DOM transitions stay inside this fake origin.
    script = '''
      window.clicks = 0;
      document.querySelector('button').onclick = async () => {
        window.clicks++;
        document.querySelector('#loading').hidden = false;
        const payload = PAYLOAD;
        const post = (path, body) => fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        await post(SAVE, payload);
        const response = await post(APPLY, payload);
        const data = await response.json();
        if (MODE === 'existing') {
          document.querySelector('#loading').hidden = true;
          document.querySelector('#result').innerHTML = '<div role="dialog"><h3>错误提示</h3><p>' + data.message + '</p><button>确定</button></div>';
          return;
        }
        document.querySelector('#result').innerHTML = '<h2>业务办理成功</h2><p>提交成功</p>';
        if (MODE === 'page-only') return;
        await post(SAVE, payload);
        setTimeout(async () => {
          await post(COMPLETE, {encryptData:'fake'});
          document.querySelector('#loading').hidden = true;
          if (MODE === 'detach') document.querySelector('iframe').remove();
        }, DELAY);
      };
    '''
    for key, value in {'PAYLOAD': payload, 'SAVE': SAVE_PATH, 'APPLY': apply_path, 'COMPLETE': COMPLETE_PATH, 'MODE': mode, 'DELAY': delay_ms}.items():
        script = script.replace(key, json.dumps(value))
    outer_html = '<button>确认提交</button><div id="loading" class="loading-mask" hidden>正在加载</div><div id="result"></div><iframe src="/form"></iframe><script>' + script + '</script>'
    input_html = f'<input id="idNumber" value="{IDENTITY}">' if operation == 'information_collection' else f'<sipub-person-quick-search><input value="{IDENTITY}"></sipub-person-quick-search>'

    def handle(route):
        path = route.request.url.split('jiangsu.gov.cn')[-1]
        if path == '/outer': route.fulfill(content_type='text/html; charset=utf-8', body=outer_html)
        elif path == '/form': route.fulfill(content_type='text/html; charset=utf-8', body=input_html)
        elif path == SAVE_PATH:
            calls.append(path)
            route.fulfill(status=200, headers={'Content-Length': '0'}, body='')
        elif path == apply_path:
            calls.append(path)
            if mode == 'existing':
                route.fulfill(status=400, content_type='application/json', body=json.dumps({'code': '1111', 'message': f'证件号为{IDENTITY}的人员信息已采集,人员编号为123456789'}))
            else:
                route.fulfill(status=201, content_type='application/json', body=json.dumps({'ok': True, 'appcode': -1, 'errmsg': '未提供错误信息', 'personUniqueId': 123, 'personUniqId': 123}))
        elif path == COMPLETE_PATH:
            calls.append(path)
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'appcode': '0', 'map': {'data': {'busiId': 'current-application', 'complete': False}}}))
        else: raise AssertionError('Unexpected request: ' + path)

    page.route('**/*', handle)
    page.goto('https://rs.jshrss.jiangsu.gov.cn/outer')
    frame = next(frame for frame in page.frames if frame.parent_frame is page.main_frame)
    frame.locator('input').wait_for()
    settings = load_settings(Path('config/settings.toml'), data_root=tmp_path)
    settings = replace(settings, browser=replace(settings.browser, pacing=replace(settings.browser.pacing, enabled=False)))
    automation = SimpleNamespace(page=page, settings=settings, waiter=SmartWait(page.wait_for_timeout, poll_interval_ms=50),
                                 pacer=BrowserInteractionPacer(settings.browser.pacing, page.wait_for_timeout), _progress=Mock())
    return SocialSubmitter(automation, frame, item, operation=operation, timeout_ms=4_000 if mode != 'page-only' else 900), calls


@pytest.mark.parametrize('mode', ['success', 'detach'])
def test_enrollment_waits_for_loading_and_correlated_completion_before_success(browser_page, tmp_path, mode):
    submitter, calls = arrange(browser_page, tmp_path, mode=mode)
    before = Mock()
    started = monotonic()
    receipt = submitter.run(before_submit=before)
    assert receipt.outcome == 'submitted'
    assert monotonic() - started >= 1.1  # delayed loading + stable final page
    before.assert_called_once()
    assert calls.count(ENROLLMENT_PATH) == 1
    assert browser_page.evaluate('window.clicks') == 1


def test_existing_collection_error_dialog_returns_the_platform_message(browser_page, tmp_path):
    submitter, calls = arrange(browser_page, tmp_path, operation='information_collection', mode='existing')
    receipt = submitter.run(before_submit=Mock())
    assert receipt.outcome == 'existing'
    assert '人员信息已采集' in receipt.message
    assert calls.count(COLLECTION_PATH) == 1
    assert browser_page.get_by_role('dialog').is_visible()


def test_incomplete_loading_or_missing_completion_is_unknown_without_retry(browser_page, tmp_path):
    submitter, calls = arrange(browser_page, tmp_path, mode='page-only')
    with pytest.raises(SocialSubmissionError) as error:
        submitter.run(before_submit=Mock())
    assert error.value.outcome == 'unknown'
    assert calls.count(ENROLLMENT_PATH) == 1
    assert browser_page.evaluate('window.clicks') == 1


def test_previous_success_page_is_rejected_before_click(browser_page, tmp_path):
    submitter, calls = arrange(browser_page, tmp_path)
    browser_page.locator('#result').evaluate('(node) => node.innerHTML = "<h2>业务办理成功</h2><p>提交成功</p>"')
    before = Mock()
    with pytest.raises(SocialSubmissionError, match='上一人'):
        submitter.run(before_submit=before)
    before.assert_not_called()
    assert not calls
