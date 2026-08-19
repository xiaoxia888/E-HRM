from pathlib import Path
from shutil import copyfile

import pytest

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.settings import load_settings


def test_single_namespaced_configuration_loads_all_modules(tmp_path: Path) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)

    assert settings.browser.action_timeout_ms == 30_000
    assert settings.site.rights_statement_url.endswith("/unit/rightsBill")
    assert settings.erp.base_url == "https://erp.njncc.com"
    assert settings.erp.headless is True
    assert settings.browser.user_data_dir == tmp_path / "data/browser-profile"
    assert settings.erp.user_data_dir == tmp_path / "data/erp-browser-profile"


def test_missing_module_section_does_not_fall_back_to_python_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.toml"
    config_path.write_text("[common]\naction_timeout_ms = 30000\n", encoding="utf-8")
    copyfile("config/error_messages.toml", tmp_path / "error_messages.toml")

    with pytest.raises(ConfigurationError, match=r"\[rights_statement\]"):
        load_settings(config_path, data_root=tmp_path)
