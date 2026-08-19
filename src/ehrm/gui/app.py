from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from ehrm.core.logging import configure_logging
from ehrm.core.settings import load_settings
from ehrm.gui.view_model import DesktopViewModel


def _resource_path(relative: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative
    return Path(relative)


def _default_config_path() -> Path:
    # An external config beside the executable remains user-editable. The
    # bundled resource is the fallback used by development and future builds.
    executable_config = Path(sys.executable).parent / "config" / "settings.toml"
    if getattr(sys, "frozen", False) and executable_config.is_file():
        return executable_config
    bundled = _resource_path("config/settings.toml")
    if bundled.is_file():
        return bundled
    return _resource_path("config/settings.example.toml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="信息化人力桌面工作台")
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    application = QGuiApplication(sys.argv[:1])
    application.setApplicationName("信息化人力工作台")
    application.setOrganizationName("NJNCC")
    try:
        runtime_root = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
        )
        runtime_root.mkdir(parents=True, exist_ok=True)
        settings = load_settings(args.config, data_root=runtime_root)
        backend = DesktopViewModel(
            settings,
            configure_logging(runtime_root / "logs"),
        )
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 2
    engine = QQmlApplicationEngine()
    # Keep the Python/QML boundary explicit. Main.qml declares this as a
    # required property, so a missing bridge fails at startup instead of
    # producing a half-working window.
    engine.setInitialProperties({"backend": backend})
    qml_file = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        backend.shutdown()
        return 2
    application.aboutToQuit.connect(backend.shutdown)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
