# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the Windows desktop distribution."""

from __future__ import annotations

import os
from pathlib import Path

import playwright
from PyInstaller.utils.hooks import collect_all
from PySide6.QtCore import QLibraryInfo


SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
GENERATED_DIR = SPEC_DIR / "generated"

playwright_root = Path(playwright.__file__).resolve().parent
browser_root = playwright_root / "driver" / "package" / ".local-browsers"
if not browser_root.is_dir():
    raise SystemExit(
        "没有找到随包 Chromium。请先在 PowerShell 中执行：\n"
        '$env:PLAYWRIGHT_BROWSERS_PATH="0"\n'
        "python -m playwright install chromium"
    )

qt_qml_root = Path(
    QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
).resolve()
qtquick_pdf_qml_root = qt_qml_root / "QtQuick" / "Pdf"
qtquick_pdf_qmldir = qtquick_pdf_qml_root / "qmldir"
if not qtquick_pdf_qmldir.is_file():
    raise SystemExit(
        "当前 PySide6 安装缺少 QtQuick.Pdf QML 模块：\n"
        f"{qtquick_pdf_qmldir}\n"
        "请确认 PySide6-Addons 与 PySide6 版本一致并安装完整。"
    )

pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")
# Add the browser explicitly so hidden directories are handled consistently.
pw_datas = [
    item for item in pw_datas if ".local-browsers" not in Path(item[0]).parts
]

datas = pw_datas + [
    (str(PROJECT_ROOT / "config" / "settings.toml"), "config"),
    (str(PROJECT_ROOT / "config" / "error_messages.toml"), "config"),
    (str(PROJECT_ROOT / "config" / "models"), "config/models"),
    (str(GENERATED_DIR / "build_version.txt"), "ehrm"),
    (
        str(
            PROJECT_ROOT
            / "config"
            / "prompts"
            / "erp_task_extraction_v2_system.txt"
        ),
        "config/prompts",
    ),
    (str(SOURCE_ROOT / "ehrm" / "gui" / "qml"), "ehrm/gui/qml"),
    (str(SOURCE_ROOT / "ehrm" / "gui" / "assets"), "ehrm/gui/assets"),
    # PyInstaller's Qt hook may collect the Qt PDF plugin DLL without copying
    # all QML metadata on Windows. Copy the complete module explicitly because
    # PdfPreviewDialog.qml imports QtQuick.Pdf at runtime.
    (str(qtquick_pdf_qml_root), "PySide6/Qt/qml/QtQuick/Pdf"),
    (
        str(browser_root),
        "playwright/driver/package/.local-browsers",
    ),
]

hiddenimports = pw_hiddenimports + [
    "PySide6.QtPdf",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtSvg",
]

icon_path = GENERATED_DIR / "app.ico"
version_path = GENERATED_DIR / "version_info.txt"
console_enabled = os.environ.get("EHRM_BUILD_CONSOLE") == "1"

a = Analysis(
    [str(PROJECT_ROOT / "scripts" / "run_gui.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=pw_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="E-HRM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=console_enabled,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.is_file() else None,
    version=str(version_path) if version_path.is_file() else None,
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="E-HRM",
)
