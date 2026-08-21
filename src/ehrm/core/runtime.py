from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths


APPLICATION_NAME = "信息化人力工作台"
ORGANIZATION_NAME = "NJNCC"


def configure_application_identity(application: QCoreApplication) -> None:
    """Keeps GUI and standalone tools on the same per-user data path."""

    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)


def application_data_root() -> Path:
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not location:
        raise OSError("操作系统没有返回可用的应用数据目录")
    root = Path(location)
    root.mkdir(parents=True, exist_ok=True)
    return root
