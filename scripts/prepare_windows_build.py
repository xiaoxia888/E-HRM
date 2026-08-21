"""Generates Windows icon and version metadata used by PyInstaller."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = PROJECT_ROOT / "packaging" / "windows" / "generated"


def _source_version() -> str:
    from ehrm import __version__

    return __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 Windows 图标和版本资源",
    )
    parser.add_argument(
        "--version",
        help="本次构建版本，例如 0.2.0；不传时读取项目版本",
    )
    return parser


def _validated_version(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", normalized):
        raise ValueError("版本号必须为 0.2.0 或 0.2.0.0 格式")
    if any(int(part) > 65535 for part in normalized.split(".")):
        raise ValueError("版本号的每一段必须在 0–65535 之间")
    return normalized


def _generate_icon(target: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, QSize
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    application = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(
        str(PROJECT_ROOT / "src" / "ehrm" / "gui" / "assets" / "app.svg")
    )
    if not renderer.isValid():
        raise RuntimeError("应用 SVG 图标无法读取")
    image = QImage(QSize(256, 256), QImage.Format_ARGB32)
    image.fill(QColor("transparent"))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 256, 256))
    painter.end()
    if not image.save(str(target), "ICO"):
        raise RuntimeError("无法生成 Windows ICO 图标")
    del application


def _generate_version_file(target: Path, version: str) -> None:
    parts = [int(part) for part in version.split(".")]
    parts = (parts + [0, 0, 0, 0])[:4]
    tuple_text = ", ".join(str(part) for part in parts)
    content = f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tuple_text}),
    prodvers=({tuple_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'NJNCC'),
         StringStruct('FileDescription', '信息化人力工作台'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', 'E-HRM'),
         StringStruct('OriginalFilename', 'E-HRM.exe'),
         StringStruct('ProductName', '信息化人力工作台'),
         StringStruct('ProductVersion', '{version}')]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
'''
    target.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    version = _validated_version(args.version or _source_version())
    _generate_icon(GENERATED_DIR / "app.ico")
    _generate_version_file(GENERATED_DIR / "version_info.txt", version)
    (GENERATED_DIR / "build_version.txt").write_text(
        version,
        encoding="utf-8",
    )
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
