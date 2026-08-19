from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ehrm.core.error_catalog import configure_error_messages
from ehrm.core.exceptions import ConfigurationError


DEFAULT_SETTINGS_PATH = Path("config/settings.toml")


@dataclass(frozen=True, slots=True)
class BrowserSettings:
    headless: bool
    silent_session_check: bool
    slow_mo_ms: int
    action_timeout_ms: int
    navigation_timeout_ms: int
    manual_login_timeout_seconds: int
    user_data_dir: Path
    storage_state_path: Path


@dataclass(frozen=True, slots=True)
class SiteSettings:
    login_url: str
    rights_statement_url: str


@dataclass(frozen=True, slots=True)
class LoginSelectors:
    unit_login_tab: str
    username: str
    password: str
    submit: str
    authenticated_marker: str


@dataclass(frozen=True, slots=True)
class NavigationSelectors:
    province_entry: str
    city_entry: str
    rights_statement_menu: str


@dataclass(frozen=True, slots=True)
class RightsStatementSelectors:
    start_month: str
    end_month: str
    insurance_type: str
    insurance_option_template: str
    social_security_number: str
    employee_name: str
    query_button: str
    results_ready: str
    no_results: str
    loading_indicator: str
    query_result_timeout_ms: int
    no_result_confirm_ms: int
    transfer_result_timeout_ms: int
    step_delay_ms: int
    preview_ready_timeout_ms: int
    preview_download_delay_ms: int
    download_timeout_ms: int
    calendar_popup: str
    candidate_table: str
    selected_table: str
    transfer_left: str
    transfer_back: str
    generate_button: str
    download_ready: str
    download_button: str
    preview_dialog: str
    close_preview: str


@dataclass(frozen=True, slots=True)
class ErpLoginSelectors:
    username: str
    password: str
    submit: str


@dataclass(frozen=True, slots=True)
class ErpSettings:
    base_url: str
    login_url: str
    application_url: str
    user_data_dir: Path
    headless: bool
    login_timeout_ms: int
    request_timeout_ms: int
    business_keyword: str
    library_id: str
    storage_type: str
    chunk_size_bytes: int
    username_env: str
    password_env: str
    login: ErpLoginSelectors


@dataclass(frozen=True, slots=True)
class AppSettings:
    browser: BrowserSettings
    site: SiteSettings
    login: LoginSelectors
    navigation: NavigationSelectors
    rights_statement: RightsStatementSelectors
    erp: ErpSettings


def _required_section(
    data: dict[str, Any],
    name: str,
    *,
    parent: str = "",
) -> dict[str, Any]:
    qualified = f"{parent}.{name}" if parent else name
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"配置缺少 [{qualified}] 段")
    return value


def _required_value(section: dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigurationError(f"配置缺少 {section_name}.{key}")
    return section[key]


def _text(section: dict[str, Any], key: str, section_name: str) -> str:
    value = _required_value(section, key, section_name)
    if not isinstance(value, str):
        raise ConfigurationError(f"配置项 {section_name}.{key} 必须是字符串")
    return value.strip()


def _boolean(section: dict[str, Any], key: str, section_name: str) -> bool:
    value = _required_value(section, key, section_name)
    if not isinstance(value, bool):
        raise ConfigurationError(f"配置项 {section_name}.{key} 必须是布尔值")
    return value


def _integer(section: dict[str, Any], key: str, section_name: str) -> int:
    value = _required_value(section, key, section_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"配置项 {section_name}.{key} 必须是整数")
    if value < 0:
        raise ConfigurationError(f"配置项 {section_name}.{key} 不能小于 0")
    return value


def _resolved_path(value: str, relative_root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (relative_root / path).resolve()


def load_settings(path: Path, *, data_root: Path | None = None) -> AppSettings:
    """Loads the single authoritative, namespaced system configuration."""
    if not path.is_file():
        raise ConfigurationError(f"配置文件不存在：{path}")

    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError("配置文件 TOML 格式错误", details=str(exc)) from exc

    try:
        configure_error_messages(path.parent / "error_messages.toml")
    except ValueError as exc:
        raise ConfigurationError("异常文案配置错误", details=str(exc)) from exc

    common = _required_section(data, "common")

    rights_root = _required_section(data, "rights_statement")
    rights_browser = _required_section(
        rights_root, "browser", parent="rights_statement"
    )
    rights_site = _required_section(rights_root, "site", parent="rights_statement")
    rights_selectors = _required_section(
        rights_root, "selectors", parent="rights_statement"
    )
    rights_login = _required_section(
        rights_selectors, "login", parent="rights_statement.selectors"
    )
    rights_navigation = _required_section(
        rights_selectors, "navigation", parent="rights_statement.selectors"
    )
    rights_page = _required_section(
        rights_selectors, "page", parent="rights_statement.selectors"
    )

    erp_root = _required_section(data, "erp")
    erp_browser = _required_section(erp_root, "browser", parent="erp")
    erp_site = _required_section(erp_root, "site", parent="erp")
    erp_upload = _required_section(erp_root, "upload", parent="erp")
    erp_credentials = _required_section(erp_root, "credentials", parent="erp")
    erp_selectors = _required_section(erp_root, "selectors", parent="erp")
    erp_login = _required_section(
        erp_selectors, "login", parent="erp.selectors"
    )

    relative_root = data_root or Path.cwd()
    common_name = "common"
    rights_browser_name = "rights_statement.browser"
    rights_site_name = "rights_statement.site"
    rights_login_name = "rights_statement.selectors.login"
    rights_navigation_name = "rights_statement.selectors.navigation"
    rights_page_name = "rights_statement.selectors.page"
    erp_browser_name = "erp.browser"
    erp_site_name = "erp.site"
    erp_upload_name = "erp.upload"
    erp_credentials_name = "erp.credentials"
    erp_login_name = "erp.selectors.login"

    action_timeout_ms = _integer(common, "action_timeout_ms", common_name)
    login_url = _text(rights_site, "login_url", rights_site_name)
    page_url = _text(rights_site, "page_url", rights_site_name)
    if not login_url:
        raise ConfigurationError("配置项 rights_statement.site.login_url 不能为空")

    return AppSettings(
        browser=BrowserSettings(
            headless=_boolean(rights_browser, "headless", rights_browser_name),
            silent_session_check=_boolean(
                rights_browser, "silent_session_check", rights_browser_name
            ),
            slow_mo_ms=_integer(rights_browser, "slow_mo_ms", rights_browser_name),
            action_timeout_ms=action_timeout_ms,
            navigation_timeout_ms=_integer(
                rights_browser, "navigation_timeout_ms", rights_browser_name
            ),
            manual_login_timeout_seconds=_integer(
                rights_browser,
                "manual_login_timeout_seconds",
                rights_browser_name,
            ),
            user_data_dir=_resolved_path(
                _text(rights_browser, "user_data_dir", rights_browser_name),
                relative_root,
            ),
            storage_state_path=_resolved_path(
                _text(rights_browser, "storage_state_path", rights_browser_name),
                relative_root,
            ),
        ),
        site=SiteSettings(
            login_url=login_url,
            rights_statement_url=page_url,
        ),
        login=LoginSelectors(
            unit_login_tab=_text(rights_login, "unit_login_tab", rights_login_name),
            username=_text(rights_login, "username", rights_login_name),
            password=_text(rights_login, "password", rights_login_name),
            submit=_text(rights_login, "submit", rights_login_name),
            authenticated_marker=_text(
                rights_login, "authenticated_marker", rights_login_name
            ),
        ),
        navigation=NavigationSelectors(
            province_entry=_text(
                rights_navigation, "province_entry", rights_navigation_name
            ),
            city_entry=_text(
                rights_navigation, "city_entry", rights_navigation_name
            ),
            rights_statement_menu=_text(
                rights_navigation, "page_menu", rights_navigation_name
            ),
        ),
        rights_statement=RightsStatementSelectors(
            start_month=_text(rights_page, "start_month", rights_page_name),
            end_month=_text(rights_page, "end_month", rights_page_name),
            insurance_type=_text(rights_page, "insurance_type", rights_page_name),
            insurance_option_template=_text(
                rights_page, "insurance_option_template", rights_page_name
            ),
            social_security_number=_text(
                rights_page, "social_security_number", rights_page_name
            ),
            employee_name=_text(rights_page, "employee_name", rights_page_name),
            query_button=_text(rights_page, "query_button", rights_page_name),
            results_ready=_text(rights_page, "results_ready", rights_page_name),
            no_results=_text(rights_page, "no_results", rights_page_name),
            loading_indicator=_text(
                rights_page, "loading_indicator", rights_page_name
            ),
            query_result_timeout_ms=_integer(
                rights_page, "query_result_timeout_ms", rights_page_name
            ),
            no_result_confirm_ms=_integer(
                rights_page, "no_result_confirm_ms", rights_page_name
            ),
            transfer_result_timeout_ms=_integer(
                rights_page, "transfer_result_timeout_ms", rights_page_name
            ),
            step_delay_ms=_integer(rights_page, "step_delay_ms", rights_page_name),
            preview_ready_timeout_ms=_integer(
                rights_page, "preview_ready_timeout_ms", rights_page_name
            ),
            preview_download_delay_ms=_integer(
                rights_page, "preview_download_delay_ms", rights_page_name
            ),
            download_timeout_ms=_integer(
                rights_page, "download_timeout_ms", rights_page_name
            ),
            calendar_popup=_text(rights_page, "calendar_popup", rights_page_name),
            candidate_table=_text(rights_page, "candidate_table", rights_page_name),
            selected_table=_text(rights_page, "selected_table", rights_page_name),
            transfer_left=_text(rights_page, "transfer_left", rights_page_name),
            transfer_back=_text(rights_page, "transfer_back", rights_page_name),
            generate_button=_text(rights_page, "generate_button", rights_page_name),
            download_ready=_text(rights_page, "download_ready", rights_page_name),
            download_button=_text(rights_page, "download_button", rights_page_name),
            preview_dialog=_text(rights_page, "preview_dialog", rights_page_name),
            close_preview=_text(rights_page, "close_preview", rights_page_name),
        ),
        erp=ErpSettings(
            base_url=_text(erp_site, "base_url", erp_site_name),
            login_url=_text(erp_site, "login_url", erp_site_name),
            application_url=_text(
                erp_site, "application_url", erp_site_name
            ),
            user_data_dir=_resolved_path(
                _text(erp_browser, "user_data_dir", erp_browser_name),
                relative_root,
            ),
            headless=_boolean(erp_browser, "headless", erp_browser_name),
            login_timeout_ms=_integer(
                erp_browser, "login_timeout_ms", erp_browser_name
            ),
            request_timeout_ms=_integer(
                erp_browser, "request_timeout_ms", erp_browser_name
            ),
            business_keyword=_text(
                erp_upload, "business_keyword", erp_upload_name
            ),
            library_id=_text(erp_upload, "library_id", erp_upload_name),
            storage_type=_text(erp_upload, "storage_type", erp_upload_name),
            chunk_size_bytes=_integer(
                erp_upload, "chunk_size_bytes", erp_upload_name
            ),
            username_env=_text(
                erp_credentials, "username_env", erp_credentials_name
            ),
            password_env=_text(
                erp_credentials, "password_env", erp_credentials_name
            ),
            login=ErpLoginSelectors(
                username=_text(erp_login, "username", erp_login_name),
                password=_text(erp_login, "password", erp_login_name),
                submit=_text(erp_login, "submit", erp_login_name),
            ),
        ),
    )
