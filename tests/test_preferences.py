from __future__ import annotations

import json
from pathlib import Path

from ehrm.core.preferences import UserPreferences, UserPreferencesStore


def test_preferences_round_trip(tmp_path: Path) -> None:
    store = UserPreferencesStore(tmp_path / "data" / "preferences.json")
    preferences = UserPreferences(
        output_path=str(tmp_path / "downloads"),
        export_mode="batch",
        batch_size=25,
        upload_to_erp=True,
        open_output_folder=True,
        erp_username="tester",
        execution_speed="stable",
        no_result_confirm_seconds=15,
        preview_download_delay_ms=2000,
        download_timeout_seconds=60,
    )

    store.save(preferences)

    assert store.load() == preferences
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert "password" not in payload


def test_invalid_preferences_fall_back_to_safe_values(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(
        json.dumps(
            {
                "export_mode": ["batch"],
                "batch_size": 999,
                "upload_to_erp": "false",
                "execution_speed": {"value": "fast"},
            }
        ),
        encoding="utf-8",
    )

    preferences = UserPreferencesStore(path).load()

    assert preferences.export_mode == "individual"
    assert preferences.batch_size == 100
    assert preferences.upload_to_erp is False
    assert preferences.execution_speed == "standard"
