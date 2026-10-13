from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from ehrm.entrypoints.cli import _parser, _record


def test_record_accepts_har_and_uses_active_python_environment(tmp_path: Path) -> None:
    profile = tmp_path / "data" / "medical-codegen"
    script = tmp_path / "artifacts" / "medical-submit.py"
    har = tmp_path / "artifacts" / "medical-submit.har"
    url = "https://www.jszwfw.gov.cn/jsjis/front/login.do?uuid=example"
    arguments = _parser().parse_args([
        "record", "--url", url, "--profile", str(profile),
        "--output", str(script), "--har", str(har),
    ])
    assert arguments.har == har

    with patch(
        "ehrm.entrypoints.cli.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as run:
        assert _record(url, profile, script, har) == 0

    command = run.call_args.args[0]
    assert command[:4] == [sys.executable, "-m", "playwright", "codegen"]
    assert f"--user-data-dir={profile.resolve()}" in command
    assert f"--output={script.resolve()}" in command
    assert f"--save-har={har.resolve()}" in command
    assert command[-1] == url
    assert profile.is_dir() and script.parent.is_dir() and har.parent.is_dir()


def test_record_rejects_same_script_and_har_path_without_launching(tmp_path: Path) -> None:
    path = tmp_path / "capture"
    with patch("ehrm.entrypoints.cli.subprocess.run") as run:
        assert _record("https://example.org", tmp_path / "profile", path, path) == 2
    run.assert_not_called()


def test_record_without_har_keeps_existing_codegen_mode(tmp_path: Path) -> None:
    with patch(
        "ehrm.entrypoints.cli.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as run:
        assert _record(
            "https://example.org", tmp_path / "profile", tmp_path / "flow.py",
        ) == 0
    assert not any(arg.startswith("--save-har=") for arg in run.call_args.args[0])
