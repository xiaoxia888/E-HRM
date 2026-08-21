from pathlib import Path
from shutil import copyfile

import pytest

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.settings import load_settings, select_ai_model
from ehrm.modules.ai.models import AiModelProfile


def test_single_namespaced_configuration_loads_all_modules(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)

    assert settings.browser.action_timeout_ms == 30_000
    assert settings.site.rights_statement_url.endswith("/unit/rightsBill")
    assert settings.erp.base_url == "https://erp.njncc.com"
    assert settings.erp.headless is True
    assert settings.ai.model == "qwen3.8:27b"
    assert settings.ai.profile_id == "qwen3_8_27b"
    assert settings.ai.default_reasoning_mode == "off"
    assert settings.ai.reasoning_modes == ("off", "low", "medium", "max")
    assert {item.profile_id for item in settings.ai_models} == {
        AiModelProfile.QWEN3_5_9B,
        AiModelProfile.QWEN3_8_27B,
    }
    assert settings.ai.prompt_path == (
        Path("config/prompts/erp_task_extraction_system.txt").resolve()
    )
    assert settings.browser.user_data_dir == tmp_path / "data/browser-profile"
    assert settings.erp.user_data_dir == tmp_path / "data/erp-browser-profile"


def test_qwen_3_5_profile_has_independent_runtime_and_sampling() -> None:
    settings = load_settings(Path("config/settings.toml"))

    selected = select_ai_model(settings, "qwen3_5_9b", reasoning_mode="on")

    assert selected.ai.model == "qwen3.5:9b"
    assert selected.ai.display_name == "Qwen3.5-9B"
    assert selected.ai.native_context_length == 262_144
    assert selected.ai.num_ctx == 32_768
    assert selected.ai.num_predict == 8_192
    assert selected.ai.reasoning_modes == ("off", "on")
    assert selected.ai.default_reasoning_mode == "on"
    assert selected.ai.non_thinking.temperature == 0.7
    assert selected.ai.thinking.top_p == 0.95


def test_model_rejects_an_unsupported_reasoning_mode() -> None:
    settings = load_settings(Path("config/settings.toml"))

    with pytest.raises(ConfigurationError, match="不支持推理模式 max"):
        select_ai_model(settings, "qwen3_5_9b", reasoning_mode="max")


def test_missing_module_section_does_not_fall_back_to_python_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.toml"
    config_path.write_text("[common]\naction_timeout_ms = 30000\n", encoding="utf-8")
    copyfile("config/error_messages.toml", tmp_path / "error_messages.toml")

    with pytest.raises(ConfigurationError, match=r"\[rights_statement\]"):
        load_settings(config_path, data_root=tmp_path)
