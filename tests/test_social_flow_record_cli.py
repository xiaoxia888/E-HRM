from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from ehrm.entrypoints import social_flow_record_cli as social_recorder
from ehrm.entrypoints.medical_collection_record_cli import (
    Capture,
    SOCIAL_LOGIN_URL,
    _ACTION_SCRIPT,
    _is_business_api_host,
    _is_business_page,
    _record,
    _snapshot,
)


@pytest.mark.parametrize("flow", ["information", "enrollment"])
def test_social_flow_selects_separate_profile_and_output(monkeypatch, flow: str) -> None:
    selected = {}

    def fake_record(profile, output_dir, url, *, flow, system):
        selected.update(profile=profile, output_dir=output_dir, url=url, flow=flow, system=system)
        return 0

    monkeypatch.setattr(social_recorder, "_record", fake_record)
    assert social_recorder.main(["--flow", flow]) == 0
    assert selected["profile"].name == f"bhj-social-{flow}-record-profile"
    assert selected["output_dir"].name.startswith(f"bhj-social-{flow}-full-")
    assert selected["url"] == SOCIAL_LOGIN_URL
    assert selected["system"] == "social"


def test_social_recorder_rejects_wrong_entry_and_recognizes_business_page(tmp_path: Path) -> None:
    assert _record(tmp_path / "profile", tmp_path / "output", "https://example.com", flow="information", system="social") == 2
    assert not (tmp_path / "profile").exists()
    assert _is_business_page("https://rs.jshrss.jiangsu.gov.cn/web/login", "social") is False
    assert _is_business_page("https://rs.jshrss.jiangsu.gov.cn/web/unitcenter/unitmain", "social") is True
    assert _is_business_api_host("https://rs.jshrss.jiangsu.gov.cn/api/enroll", "social") is True
    assert _is_business_api_host("https://www.jszwfw.gov.cn/api/enroll", "social") is False


def test_social_recorder_captures_mock_business_submission(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("本地录制回归测试需要已安装的 Playwright Chromium")
        context = playwright.chromium.launch_persistent_context(str(tmp_path / "profile"), headless=True)
        capture = Capture(tmp_path, system="social")
        try:
            context.expose_binding("__ehrmMedicalCollectionCaptureV1", capture.action)
            context.add_init_script(_ACTION_SCRIPT)
            context.on("requestfinished", capture.request_finished)

            def route_handler(route):
                if route.request.url.endswith("/api/enroll"):
                    route.fulfill(status=200, content_type="application/json", body='{"code":0,"message":"提交成功"}')
                else:
                    route.fulfill(content_type="text/html; charset=utf-8", body="""
                        <button>提交</button><p id="result"></p>
                        <script>
                          document.querySelector('button').onclick = () =>
                            fetch('/api/enroll', {method: 'POST', body: '{}'})
                              .then(r => r.json()).then(r => document.querySelector('#result').textContent = r.message)
                        </script>
                    """)

            context.route("**/*", route_handler)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://rs.jshrss.jiangsu.gov.cn/web/unitcenter/unitmain")
            _snapshot(context, tmp_path, "before-submit", system="social")
            capture.phase = "submit_and_post"
            page.get_by_role("button", name="提交").click()
            page.get_by_text("提交成功").wait_for()
            _snapshot(context, tmp_path, "after-submit", system="social")
            summary = capture.summary()
            assert summary["social_api_total"] == 1
            assert summary["non_get_api_after_pre_submit"] == 1
            assert summary["warning"] == ""
            assert (tmp_path / "social-network.jsonl").exists()
            assert "提交成功" in (tmp_path / "after-submit-frame-0.html").read_text()
        finally:
            context.close()
            capture.close()
