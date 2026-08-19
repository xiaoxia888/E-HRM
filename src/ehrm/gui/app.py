from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from ehrm.core.logging import configure_logging
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.gui.view_model import DesktopViewModel


def _resource_path(relative: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative
    return Path(relative)


def _default_config_path() -> Path:
    return _resource_path(str(DEFAULT_SETTINGS_PATH))


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
        logger = configure_logging(runtime_root / "logs")
        settings = load_settings(args.config, data_root=runtime_root)
        logger.info("系统配置已加载 path=%s", args.config.expanduser().resolve())
        backend = DesktopViewModel(
            settings,
            logger,
        )
        # The application owns the Python bridge. This guarantees that QML
        # bindings cannot outlive the backend during interpreter teardown.
        backend.setParent(application)
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 2
    engine = QQmlApplicationEngine()
    # Child pages use a context property during teardown. Unlike a binding
    # passed through Main.qml, it remains valid until all QML objects have been
    # destroyed and prevents spurious "property of null" errors on exit.
    engine.rootContext().setContextProperty("appBackend", backend)
    # Keep the Python/QML boundary explicit. Main.qml declares this as a
    # required property, so a missing bridge fails at startup instead of
    # producing a half-working window.
    engine.setInitialProperties({"backend": backend})
    qml_file = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        backend.shutdown()
        return 2
    exit_code = 0
    try:
        exit_code = application.exec()
    finally:
        # Stop background automation, then synchronously destroy every QML
        # object while the backend and QGuiApplication are both still alive.
        # Relying on Python's local-variable cleanup order can release the
        # backend first and make child-page bindings evaluate against null.
        backend.shutdown()
        del engine
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
