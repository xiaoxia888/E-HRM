from pathlib import Path
from shutil import copyfile, copytree
import tomllib
from uuid import uuid4

import pytest

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.settings import load_settings, select_ai_model
from ehrm.modules.ai.models import AiModelProfile


def test_single_namespaced_configuration_loads_all_modules(tmp_path: Path) -> None:
    config_path = Path("config/settings.toml")
    settings = load_settings(config_path, data_root=tmp_path)
    with config_path.open("rb") as stream:
        configured = tomllib.load(stream)

    assert settings.browser.engine in {"chromium", "firefox", "webkit"}
    if settings.browser.engine != "chromium":
        assert settings.browser.channel == ""
    assert settings.browser.action_timeout_ms == 30_000
    assert settings.site.rights_statement_url.endswith("/unit/rightsBill")
    assert settings.rights_credentials.credit_code_env == "EHRM_RIGHTS_CREDIT_CODE"
    assert settings.login.mobile == 'role=textbox[name="证件号码/移动电话"]'
    assert settings.login.unit_login_tab == 'text="单位登录"'
    assert settings.login.account_password_tab == 'text="账号密码" >> nth=1'
    assert settings.captcha.enabled is True
    assert settings.captcha.stealth_enabled is True
    assert settings.captcha.allowed_hosts
    assert settings.captcha.verify_path.startswith("/")
    assert settings.captcha.max_attempts == 3
    assert settings.captcha.click_delay_min_ms == 1000
    assert settings.captcha.click_delay_max_ms == 2000
    assert settings.captcha.click_offset_max_px >= 0
    assert settings.erp.base_url
    assert settings.erp.headless is True
    assert settings.ai.model == "qwen3.5:9b"
    assert settings.ai.profile_id == "qwen3_5_9b"
    assert settings.ai.default_reasoning_mode == "off"
    assert settings.ai.reasoning_modes == ("off", "on")
    assert {item.profile_id for item in settings.ai_models} == {
        AiModelProfile.QWEN3_5_9B,
        AiModelProfile.QWEN3_8_27B,
    }
    assert settings.ai.prompt_path == (
        Path("config/prompts/erp_task_extraction_v2_system.txt").resolve()
    )
    assert settings.browser.user_data_dir == tmp_path / configured[
        "rights_statement"
    ]["browser"]["user_data_dir"]
    assert settings.erp.user_data_dir == tmp_path / configured["erp"]["browser"][
        "user_data_dir"
    ]
    assert settings.browser.user_data_dir != settings.erp.user_data_dir


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


def test_captcha_allowed_hosts_rejects_embedded_port(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    copytree("config", config_dir)
    config_path = config_dir / "settings.toml"
    source = config_path.read_text(encoding="utf-8")
    configured_host = load_settings(
        Path("config/settings.toml")
    ).captcha.allowed_hosts[0]
    minimum_unprivileged_port = 1024
    maximum_tcp_port = 65535
    available_port_count = maximum_tcp_port - minimum_unprivileged_port + 1
    port = minimum_unprivileged_port + uuid4().int % available_port_count
    config_path.write_text(
        source.replace(
            f'"{configured_host}",',
            f'"{configured_host}:{port}",',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="不能包含端口"):
        load_settings(config_path, data_root=tmp_path)


def test_non_chromium_engine_rejects_a_browser_channel(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    copytree("config", config_dir)
    config_path = config_dir / "settings.toml"
    source = config_path.read_text(encoding="utf-8")
    configured = load_settings(Path("config/settings.toml")).browser
    source = source.replace(
        f'engine = "{configured.engine}"',
        'engine = "firefox"',
        1,
    ).replace(
        f'channel = "{configured.channel}"',
        'channel = "msedge"',
        1,
    )
    config_path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="仅能与 engine=chromium"):
        load_settings(config_path, data_root=tmp_path)
