from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ehrm.core.logging import configure_logging
from ehrm.core.runtime import (
    application_runtime_root,
    configure_application_identity,
    migrate_legacy_preferences,
)
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
    if getattr(sys, "frozen", False):
        # The Windows bundle contains Playwright's local Chromium directory.
        # Force the Node driver to resolve that bundled browser instead of the
        # current user's external ms-playwright cache.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    args = _parser().parse_args(argv)
    # Keep all application controls visually identical on macOS and Windows.
    # Native platform styles reject several QML customizations and can render
    # the same form as unrelated controls (for example, a ComboBox as a
    # macOS stepper). File dialogs remain native by design.
    QQuickStyle.setStyle("Basic")
    application = QGuiApplication(sys.argv[:1])
    configure_application_identity(application)
    try:
        runtime_root = application_runtime_root(args.config)
        logger = configure_logging(runtime_root / "logs")
        if migrate_legacy_preferences(runtime_root):
            logger.info(
                "旧版非敏感用户偏好已迁移到 runtime/data/preferences.json"
            )
        settings = load_settings(args.config, data_root=runtime_root)
        logger.info("系统配置已加载 path=%s", args.config.expanduser().resolve())
        logger.info("程序运行数据根目录 root=%s", runtime_root)
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
        for root in engine.rootObjects():
            root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()
        del engine
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
