from __future__ import annotations

from pathlib import Path
import sys

from scripts import check_windows_build_environment
from scripts.verify_windows_bundle import main


def _write_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")


def _complete_bundle(tmp_path: Path, *, include_pyodbc: bool) -> Path:
    bundle = tmp_path / "E-HRM"
    resource_root = bundle / "_internal"
    required_files = (
        bundle / "E-HRM.exe",
        resource_root / "config" / "settings.toml",
        resource_root / "config" / "error_messages.toml",
        resource_root / "config" / "models" / "qwen3_5_9b.toml",
        resource_root / "config" / "models" / "qwen3_8_27b.toml",
        resource_root
        / "config"
        / "prompts"
        / "erp_task_extraction_v2_system.txt",
        resource_root / "ehrm" / "gui" / "qml" / "Main.qml",
        resource_root / "ehrm" / "gui" / "qml" / "PdfPreviewDialog.qml",
        resource_root / "ehrm" / "gui" / "qml" / "SystemSettingsPage.qml",
        resource_root
        / "ehrm"
        / "gui"
        / "qml"
        / "NocoBaseApplicationsPage.qml",
        resource_root
        / "ehrm"
        / "gui"
        / "qml"
        / "NocoBaseApplicationDetailDialog.qml",
        resource_root
        / "ehrm"
        / "gui"
        / "qml"
        / "NocoBasePrintProgressDialog.qml",
        resource_root / "ehrm" / "gui" / "qml" / "PaginationBar.qml",
        resource_root
        / "playwright_stealth"
        / "js"
        / "evasions"
        / "navigator.webdriver.js",
        resource_root
        / "PySide6"
        / "Qt"
        / "qml"
        / "QtQuick"
        / "Pdf"
        / "qmldir",
        resource_root / "PySide6" / "Qt6Pdf.dll",
        resource_root / "PySide6" / "pdfquickplugin.dll",
        resource_root / "playwright" / "driver" / "node.exe",
        resource_root
        / "playwright"
        / "driver"
        / "package"
        / ".local-browsers"
        / "chromium"
        / "chrome.exe",
    )
    for path in required_files:
        _write_file(path)
    if include_pyodbc:
        _write_file(resource_root / "pyodbc.cp311-win_amd64.pyd")
    return bundle


def test_windows_bundle_rejects_missing_pyodbc_runtime(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    bundle = _complete_bundle(tmp_path, include_pyodbc=False)
    monkeypatch.setattr(sys, "argv", ["verify_windows_bundle.py", str(bundle)])

    exit_code = main()

    assert exit_code == 1
    assert "pyodbc" in capsys.readouterr().out


def test_windows_bundle_accepts_pyodbc_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = _complete_bundle(tmp_path, include_pyodbc=True)
    monkeypatch.setattr(sys, "argv", ["verify_windows_bundle.py", str(bundle)])

    assert main() == 0


def test_windows_build_environment_does_not_require_database_connection(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_windows_build_environment.py"],
    )
    monkeypatch.setattr(
        check_windows_build_environment.pyodbc,
        "drivers",
        lambda: ["ODBC Driver 17 for SQL Server"],
    )

    def fail_if_connected(_settings):
        raise AssertionError("默认打包预检不应连接运行时数据库")

    monkeypatch.setattr(
        check_windows_build_environment,
        "_connect",
        fail_if_connected,
    )

    assert check_windows_build_environment.main() == 0


def test_windows_build_environment_can_optionally_check_database_connection(
    monkeypatch,
) -> None:
    class FakeConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_windows_build_environment.py", "--check-database"],
    )
    monkeypatch.setattr(
        check_windows_build_environment.pyodbc,
        "drivers",
        lambda: ["ODBC Driver 17 for SQL Server"],
    )
    monkeypatch.setattr(
        check_windows_build_environment,
        "_connect",
        lambda _settings: connection,
    )

    assert check_windows_build_environment.main() == 0
    assert connection.closed is True
