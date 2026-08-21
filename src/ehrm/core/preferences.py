from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ehrm.modules.ai.models import AiModelProfile


@dataclass(frozen=True, slots=True)
class UserPreferences:
    output_path: str = ""
    export_mode: str = "individual"
    batch_size: int = 50
    upload_to_erp: bool = False
    open_output_folder: bool = False
    erp_username: str = ""
    rights_credit_code: str = ""
    rights_mobile: str = ""
    ai_model_profile: str = ""
    ai_reasoning_mode: str = ""
    execution_speed: str = "standard"
    no_result_confirm_seconds: int = 10
    preview_download_delay_ms: int = 1500
    download_timeout_seconds: int = 20


class UserPreferencesStore:
    """Persists non-sensitive desktop preferences outside installation files."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UserPreferences:
        if not self.path.is_file():
            return UserPreferences()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return UserPreferences()
        defaults = asdict(UserPreferences())
        values = {key: payload.get(key, value) for key, value in defaults.items()}
        try:
            values["batch_size"] = max(1, min(100, int(values["batch_size"])))
            values["no_result_confirm_seconds"] = max(
                1, int(values["no_result_confirm_seconds"])
            )
            values["preview_download_delay_ms"] = max(
                0, int(values["preview_download_delay_ms"])
            )
            values["download_timeout_seconds"] = max(
                1, int(values["download_timeout_seconds"])
            )
        except (TypeError, ValueError):
            return UserPreferences()
        for key in ("upload_to_erp", "open_output_folder"):
            if not isinstance(values[key], bool):
                values[key] = defaults[key]
        for key in (
            "output_path",
            "erp_username",
            "rights_credit_code",
            "rights_mobile",
            "ai_model_profile",
        ):
            if not isinstance(values[key], str):
                values[key] = defaults[key]
        valid_model_profiles = {"", *(item.value for item in AiModelProfile)}
        if values["ai_model_profile"] not in valid_model_profiles:
            values["ai_model_profile"] = ""
        if not isinstance(values["ai_reasoning_mode"], str) or values[
            "ai_reasoning_mode"
        ] not in {"", "off", "on", "low", "medium", "max"}:
            values["ai_reasoning_mode"] = ""
        if not isinstance(values["export_mode"], str) or values[
            "export_mode"
        ] not in {"individual", "batch"}:
            values["export_mode"] = "individual"
        if not isinstance(values["execution_speed"], str) or values[
            "execution_speed"
        ] not in {"fast", "standard", "stable"}:
            values["execution_speed"] = "standard"
        return UserPreferences(**values)

    def save(self, preferences: UserPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(preferences), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
