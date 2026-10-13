from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from ehrm.entrypoints.medical_collection_record_cli import Capture, _ACTION_SCRIPT, _record, _snapshot


def test_enrollment_recording_has_separate_profile_and_output(monkeypatch) -> None:
    from ehrm.entrypoints import medical_collection_record_cli as recorder

    selected = {}

    def fake_record(profile, output_dir, url, *, flow):
        selected.update(profile=profile, output_dir=output_dir, url=url, flow=flow)
        return 0

    monkeypatch.setattr(recorder, "_record", fake_record)
    assert recorder.main(["--flow", "enrollment"]) == 0
    assert selected["flow"] == "enrollment"
    assert selected["profile"].name == "medical-enrollment-record-profile"
    assert selected["output_dir"].name.startswith("medical-enrollment-full-")
    assert "uuid=Q5mxXFYhCnUh" in selected["url"]


def test_recording_summary_requires_medical_mutation_after_pre_submit(tmp_path: Path) -> None:
    capture = Capture(tmp_path)
    try:
        capture.requests.extend([
            {"phase": "login_and_fill", "method": "POST", "url": "https://wb.njybjyybz.org.cn:9091/login", "status": 200},
            {"phase": "submit_and_post", "method": "GET", "url": "https://wb.njybjyybz.org.cn:9091/query?token=secret", "status": 200},
        ])
        summary = capture.summary()
        assert summary["non_get_api_after_pre_submit"] == 0
        assert "未捕获" in summary["warning"]
        assert "secret" not in str(summary)

        capture.requests.append({
            "phase": "login_and_fill", "method": "POST",
            "url": "https://wb.njybjyybz.org.cn:9091/hsa-pss-cw-local-nj/api/dwctbbl/rycbdj/saveInfo?token=secret",
            "status": 200,
        })
        summary = capture.summary()
        assert summary["non_get_api_after_pre_submit"] == 0
        assert summary["warning"] == ""
        assert summary["medical_business_submissions_all_phases"][0]["phase"] == "login_and_fill"
        assert summary["medical_business_submissions_all_phases"][0]["path"].endswith("/api/dwctbbl/rycbdj/saveInfo")
        assert "secret" not in str(summary)
    finally:
        capture.close()


def test_recorder_refuses_to_overwrite_previous_artifacts_or_wrong_entry(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    profile = tmp_path / "profile"
    assert _record(profile, output, "https://www.jszwfw.gov.cn/jsjis/front/login.do") == 2
    assert _record(profile, tmp_path / "new", "https://example.com") == 2
    assert not profile.exists()


def test_recorder_captures_mock_browser_actions_api_and_state(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("本地录制回归测试需要已安装的 Playwright Chromium")
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), headless=True,
            record_har_path=str(tmp_path / "recording.har"),
            record_har_content="embed",
        )
        capture = Capture(tmp_path)
        try:
            context.expose_binding("__ehrmMedicalCollectionCaptureV1", capture.action)
            context.add_init_script(_ACTION_SCRIPT)
            context.on("requestfinished", capture.request_finished)

            def route_handler(route):
                if route.request.url.endswith("/api/ryda/saveRydainfo"):
                    route.fulfill(status=200, content_type="application/json; charset=utf-8", body='{"code":0,"message":"提交成功"}')
                else:
                    route.fulfill(content_type="text/html; charset=utf-8", body="""
                        <label for="identity">证件号码</label><input id="identity" value="TEST-ID">
                        <button>提交</button>
                        <p id="result"></p>
                        <script>
                          document.querySelector('button').addEventListener('click', () => {
                            fetch('/hsa-pss-cw-local-nj/api/ryda/saveRydainfo', {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify({identity:'TEST-ID'})})
                              .then(r => r.json()).then(r => document.querySelector('#result').textContent=r.message)
                          })
                        </script>
                    """)

            context.route("**/*", route_handler)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://wb.njybjyybz.org.cn:9091/hsa-local-nj/web/hallUnit/")
            _snapshot(context, tmp_path, "before-submit")
            capture.phase = "submit_and_post"
            page.get_by_role("button", name="提交").click()
            page.get_by_text("提交成功").wait_for()
            _snapshot(context, tmp_path, "after-submit")
            summary = capture.summary()
            assert summary["actions"] >= 1
            assert summary["non_get_api_after_pre_submit"] == 1
            assert summary["endpoints_after_pre_submit"][0]["status"] == 200
            assert '"identity":"TEST-ID"' in str(capture.requests[0]["request_body"])
            assert '"message":"提交成功"' in str(capture.requests[0]["response_body"])
            assert (tmp_path / "after-submit.png").exists()
            assert "提交成功" in (tmp_path / "after-submit-frame-0.html").read_text()
        finally:
            context.close()
            capture.close()
        assert (tmp_path / "recording.har").exists()
