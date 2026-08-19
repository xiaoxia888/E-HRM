from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ehrm.core.error_catalog import configure_error_messages
from ehrm.core.exceptions import ConfigurationError


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
class AppSettings:
    browser: BrowserSettings
    site: SiteSettings
    login: LoginSelectors
    navigation: NavigationSelectors
    rights_statement: RightsStatementSelectors


def _required_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"配置缺少 [{name}] 段")
    return value


def _text(section: dict[str, Any], key: str) -> str:
    value = section.get(key, "")
    if not isinstance(value, str):
        raise ConfigurationError(f"配置项 {key} 必须是字符串")
    return value.strip()


def load_settings(path: Path, *, data_root: Path | None = None) -> AppSettings:
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

    browser = _required_section(data, "browser")
    site = _required_section(data, "site")
    selectors = _required_section(data, "selectors")
    login = _required_section(selectors, "login")
    navigation = _required_section(selectors, "navigation")
    rights = _required_section(selectors, "rights_statement")

    relative_root = data_root or Path.cwd()
    profile = Path(str(browser.get("user_data_dir", "data/browser-profile"))).expanduser()
    if not profile.is_absolute():
        profile = (relative_root / profile).resolve()
    storage_state = Path(
        str(browser.get("storage_state_path", "data/session-state.json"))
    ).expanduser()
    if not storage_state.is_absolute():
        storage_state = (relative_root / storage_state).resolve()

    login_url = _text(site, "login_url")
    rights_statement_url = _text(site, "rights_statement_url")
    if not login_url:
        raise ConfigurationError("login_url 不能为空")

    return AppSettings(
        browser=BrowserSettings(
            headless=bool(browser.get("headless", False)),
            silent_session_check=bool(browser.get("silent_session_check", True)),
            slow_mo_ms=int(browser.get("slow_mo_ms", 100)),
            action_timeout_ms=int(browser.get("action_timeout_ms", 30_000)),
            navigation_timeout_ms=int(browser.get("navigation_timeout_ms", 60_000)),
            manual_login_timeout_seconds=int(
                browser.get("manual_login_timeout_seconds", 300)
            ),
            user_data_dir=profile,
            storage_state_path=storage_state,
        ),
        site=SiteSettings(
            login_url=login_url,
            rights_statement_url=rights_statement_url,
        ),
        login=LoginSelectors(
            unit_login_tab=_text(login, "unit_login_tab"),
            username=_text(login, "username"),
            password=_text(login, "password"),
            submit=_text(login, "submit"),
            authenticated_marker=_text(login, "authenticated_marker"),
        ),
        navigation=NavigationSelectors(
            province_entry=_text(navigation, "province_entry"),
            city_entry=_text(navigation, "city_entry"),
            rights_statement_menu=_text(navigation, "rights_statement_menu"),
        ),
        rights_statement=RightsStatementSelectors(
            start_month=_text(rights, "start_month"),
            end_month=_text(rights, "end_month"),
            insurance_type=_text(rights, "insurance_type"),
            insurance_option_template=_text(rights, "insurance_option_template"),
            social_security_number=_text(rights, "social_security_number"),
            employee_name=_text(rights, "employee_name"),
            query_button=_text(rights, "query_button"),
            results_ready=_text(rights, "results_ready"),
            no_results=_text(rights, "no_results"),
            loading_indicator=_text(rights, "loading_indicator"),
            query_result_timeout_ms=int(rights.get("query_result_timeout_ms", 30_000)),
            no_result_confirm_ms=int(rights.get("no_result_confirm_ms", 20_000)),
            transfer_result_timeout_ms=int(
                rights.get("transfer_result_timeout_ms", 15_000)
            ),
            step_delay_ms=int(rights.get("step_delay_ms", 1_000)),
            preview_ready_timeout_ms=int(
                rights.get("preview_ready_timeout_ms", 30_000)
            ),
            preview_download_delay_ms=int(
                rights.get("preview_download_delay_ms", 1_500)
            ),
            download_timeout_ms=int(rights.get("download_timeout_ms", 60_000)),
            calendar_popup=_text(rights, "calendar_popup"),
            candidate_table=_text(rights, "candidate_table"),
            selected_table=_text(rights, "selected_table"),
            transfer_left=_text(rights, "transfer_left"),
            transfer_back=_text(rights, "transfer_back"),
            generate_button=_text(rights, "generate_button"),
            download_ready=_text(rights, "download_ready"),
            download_button=_text(rights, "download_button"),
            preview_dialog=_text(rights, "preview_dialog"),
            close_preview=_text(rights, "close_preview"),
        ),
    )
