from pathlib import Path
import sys

from ehrm.core.runtime import (
    application_runtime_root,
    migrate_legacy_preferences,
    resolve_runtime_path,
)


def test_source_runtime_root_is_beside_project_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application_dir = tmp_path / "source-app"
    config_path = application_dir / "config" / "settings.toml"
    config_path.parent.mkdir(parents=True)
    config_path.touch()
    monkeypatch.chdir(tmp_path)

    root = application_runtime_root(
        Path("source-app/config/settings.toml")
    )

    assert root == application_dir / "runtime"


def test_frozen_runtime_root_is_beside_executable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "installed" / "E-HRM.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    root = application_runtime_root(Path("ignored/config/settings.toml"))

    assert root == executable.parent / "runtime"


def test_relative_runtime_path_never_uses_process_working_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "application" / "runtime"
    unrelated_working_directory = tmp_path / "working-directory"
    unrelated_working_directory.mkdir()
    monkeypatch.chdir(unrelated_working_directory)

    path = resolve_runtime_path(Path("logs/ehrm.log"), runtime_root)

    assert path == runtime_root / "logs" / "ehrm.log"


def test_absolute_runtime_path_remains_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "external" / "result.json"

    assert resolve_runtime_path(explicit, tmp_path / "runtime") == explicit


def test_legacy_preferences_are_migrated_once(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy-user-data"
    source = legacy_root / "data" / "preferences.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"rights_credit_code": "test-account"}', encoding="utf-8")
    runtime_root = tmp_path / "application" / "runtime"

    migrated = migrate_legacy_preferences(
        runtime_root,
        legacy_root=legacy_root,
    )

    destination = runtime_root / "data" / "preferences.json"
    assert migrated is True
    assert destination.read_text(encoding="utf-8") == source.read_text(
        encoding="utf-8"
    )

    destination.write_text('{"current": true}', encoding="utf-8")
    migrated_again = migrate_legacy_preferences(
        runtime_root,
        legacy_root=legacy_root,
    )
    assert migrated_again is False
    assert destination.read_text(encoding="utf-8") == '{"current": true}'
