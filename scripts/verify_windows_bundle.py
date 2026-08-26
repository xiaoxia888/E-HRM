"""Performs non-interactive structural checks on a frozen Windows bundle."""

from __future__ import annotations

import argparse
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    return parser


def main() -> int:
    bundle = _parser().parse_args().bundle.resolve()
    internal = bundle / "_internal"
    resource_root = internal if internal.is_dir() else bundle
    required = [
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
        / "PySide6"
        / "Qt"
        / "qml"
        / "QtQuick"
        / "Pdf"
        / "qmldir",
        resource_root / "playwright" / "driver" / "node.exe",
        resource_root
        / "playwright"
        / "driver"
        / "package"
        / ".local-browsers",
    ]
    missing = [path for path in required if not path.exists()]
    browser_root = required[-1]
    browser_executables = (
        list(browser_root.rglob("chrome.exe"))
        + list(browser_root.rglob("headless_shell.exe"))
        if browser_root.is_dir()
        else []
    )
    if not browser_executables:
        missing.append(browser_root / "<chrome.exe>")
    pdf_runtime = list(resource_root.rglob("Qt6Pdf.dll"))
    if not pdf_runtime:
        missing.append(resource_root / "<Qt6Pdf.dll>")
    pdf_quick_plugin = list(resource_root.rglob("pdfquickplugin.dll"))
    if not pdf_quick_plugin:
        missing.append(resource_root / "<pdfquickplugin.dll>")
    if missing:
        print("Windows 打包结构校验失败：")
        for path in missing:
            print(f"- 缺少 {path}")
        return 1
    print(f"Windows 打包结构校验通过：{bundle}")
    print(f"已包含 Chromium：{browser_executables[0]}")
    print(f"已包含 Qt PDF：{pdf_runtime[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
