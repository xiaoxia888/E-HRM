from __future__ import annotations

from pathlib import Path
import shutil
import sys

from PySide6.QtCore import QCoreApplication, QStandardPaths


APPLICATION_NAME = "信息化人力工作台"
ORGANIZATION_NAME = "NJNCC"


def configure_application_identity(application: QCoreApplication) -> None:
    """Applies a stable application identity to every Qt entry point."""

    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)


def application_runtime_root(config_path: Path) -> Path:
    """Returns the app-local ``runtime`` directory, never a per-user path.

    A PyInstaller build uses ``runtime`` beside ``E-HRM.exe``. During source
    execution, the normal ``config/settings.toml`` layout resolves to
    ``<project>/runtime``. This makes relative paths identical in tests and
    installed builds, regardless of the process working directory.
    """

    if getattr(sys, "frozen", False):
        application_dir = Path(sys.executable).expanduser().resolve().parent
        return application_dir / "runtime"

    resolved_config = config_path.expanduser()
    if not resolved_config.is_absolute():
        resolved_config = Path.cwd() / resolved_config
    resolved_config = resolved_config.resolve()
    if resolved_config.parent.name.casefold() == "config":
        application_dir = resolved_config.parent.parent
    else:
        application_dir = resolved_config.parent
    return application_dir / "runtime"


def resolve_runtime_path(path: Path, runtime_root: Path) -> Path:
    """Resolves a user/config path relative to the application root."""

    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (runtime_root / expanded).resolve()


def migrate_legacy_preferences(
    runtime_root: Path,
    *,
    legacy_root: Path | None = None,
) -> bool:
    """Copies legacy non-secret preferences once into app-local runtime data.

    The old OS application-data location is read only for this migration. A
    pre-existing destination always wins, so current runtime preferences can
    never be overwritten by stale legacy values.
    """

    destination = runtime_root / "data" / "preferences.json"
    if destination.exists():
        return False
    if legacy_root is None:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if not location:
            return False
        legacy_root = Path(location)
    source = legacy_root / "data" / "preferences.json"
    if not source.is_file() or source.resolve() == destination.resolve():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.migrating")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True
