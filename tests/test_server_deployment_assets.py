from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_server_environment_declares_runtime_dependencies() -> None:
    environment = _read("environment.server.yml")

    assert "python=3.11.15" in environment
    assert "nodejs>=22.12,<23" in environment
    assert "pyodbc=5.3.0" in environment
    assert "requirements/backend.lock.txt" in environment


def test_macos_scripts_use_resolved_environment_and_project_browser_cache() -> None:
    setup = _read("scripts/setup_server_macos.sh")
    runner = _read("scripts/run_server_macos.sh")

    assert 'EHRM_PYTHON="$EHRM_PREFIX/bin/python"' in setup
    assert '"$EHRM_PYTHON" -m playwright install chromium' in setup
    assert 'PLAYWRIGHT_BROWSERS_PATH="$PROJECT_ROOT/runtime/playwright-browsers"' in setup
    assert 'exec "$EHRM_PREFIX/bin/ehrm-web"' in runner
    assert 'PLAYWRIGHT_BROWSERS_PATH="$PROJECT_ROOT/runtime/playwright-browsers"' in runner


def test_windows_scripts_use_resolved_environment_and_project_browser_cache() -> None:
    setup = _read("scripts/setup_server_windows.ps1")
    runner = _read("scripts/run_server_windows.ps1")
    builder = _read("scripts/build_windows.ps1")

    assert '$EhrmPython = Join-Path $EhrmPrefix "python.exe"' in setup
    assert 'runtime\\playwright-browsers' in setup
    assert 'Scripts\\ehrm-web.exe' in runner
    assert 'runtime\\playwright-browsers' in runner
    assert '$Python = Join-Path $EhrmPrefix "python.exe"' in builder
    assert '& $Python -m PyInstaller' in builder


def test_server_docs_route_users_through_platform_scripts() -> None:
    macos = _read("docs/MACOS_SETUP_AND_RUN.md")
    windows = _read("docs/WINDOWS_SETUP_AND_RUN.md")
    windows_packaging = _read("packaging/windows/README.md")

    assert "./scripts/setup_server_macos.sh" in macos
    assert "./scripts/run_server_macos.sh" in macos
    assert "setup_server_windows.ps1" in windows
    assert "run_server_windows.ps1" in windows
    assert "构建 Windows EXE 安装包" in windows
    assert "迁移旧" not in macos
    assert "迁移旧" not in windows
    assert "LaunchAgent" not in macos
    assert "环境排错" not in macos
    assert "任务计划程序" not in windows
    assert "环境排错" not in windows
    assert "打包问题" not in windows
    assert '$EhrmPython = Join-Path $EhrmPrefix "python.exe"' in windows_packaging
    assert "python scripts/check_windows_build_environment.py" not in windows_packaging
