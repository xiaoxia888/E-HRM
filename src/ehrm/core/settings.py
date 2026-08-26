from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ehrm.core.error_catalog import configure_error_messages
from ehrm.core.exceptions import ConfigurationError
from ehrm.modules.ai.models import AiModelProfile


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
class RightsCredentialsSettings:
    credit_code_env: str
    mobile_env: str
    password_env: str
    credit_code: str = ""
    mobile: str = ""
    password: str = ""


@dataclass(frozen=True, slots=True)
class LoginSelectors:
    unit_login_tab: str
    account_password_tab: str
    credit_code: str
    mobile: str
    password: str
    submit: str
    authenticated_marker: str


@dataclass(frozen=True, slots=True)
class CaptchaSettings:
    enabled: bool
    allowed_hosts: tuple[str, ...]
    verify_path: str
    max_attempts: int
    click_delay_min_ms: int
    click_delay_max_ms: int
    click_offset_max_px: int
    frame_timeout_ms: int
    verify_timeout_ms: int
    image_change_timeout_ms: int


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
class AiSamplingSettings:
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    presence_penalty: float
    repeat_penalty: float


@dataclass(frozen=True, slots=True)
class OllamaSettings:
    profile_id: AiModelProfile
    display_name: str
    source_url: str
    native_context_length: int
    reasoning_modes: tuple[str, ...]
    base_url: str
    chat_path: str
    model: str
    prompt_path: Path
    default_reasoning_mode: str
    request_timeout_seconds: int
    keep_alive: str
    num_ctx: int
    num_predict: int
    retry_count: int
    retry_delay_ms: int
    non_thinking: AiSamplingSettings
    thinking: AiSamplingSettings


@dataclass(frozen=True, slots=True)
class AppSettings:
    browser: BrowserSettings
    site: SiteSettings
    rights_credentials: RightsCredentialsSettings
    login: LoginSelectors
    captcha: CaptchaSettings
    navigation: NavigationSelectors
    rights_statement: RightsStatementSelectors
    erp: ErpSettings
    ai: OllamaSettings
    ai_models: tuple[OllamaSettings, ...]


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


def _number(section: dict[str, Any], key: str, section_name: str) -> float:
    value = _required_value(section, key, section_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"配置项 {section_name}.{key} 必须是数字")
    return float(value)


def _string_list(
    section: dict[str, Any], key: str, section_name: str
) -> tuple[str, ...]:
    value = _required_value(section, key, section_name)
    if not isinstance(value, list) or not value:
        raise ConfigurationError(
            f"配置项 {section_name}.{key} 必须是非空字符串数组"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                f"配置项 {section_name}.{key} 只能包含非空字符串"
            )
        normalized = item.strip().lower()
        if normalized not in {"off", "on", "low", "medium", "max"}:
            raise ConfigurationError(
                f"配置项 {section_name}.{key} 包含不支持的推理模式：{item}"
            )
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _plain_string_list(
    section: dict[str, Any], key: str, section_name: str
) -> tuple[str, ...]:
    value = _required_value(section, key, section_name)
    if not isinstance(value, list) or not value:
        raise ConfigurationError(
            f"配置项 {section_name}.{key} 必须是非空字符串数组"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                f"配置项 {section_name}.{key} 只能包含非空字符串"
            )
        normalized = item.strip().lower().strip("[]")
        if "://" in normalized or "/" in normalized:
            raise ConfigurationError(
                f"配置项 {section_name}.{key} 只填写主机名或 IP，不填写协议、端口或路径"
            )
        try:
            ipaddress.ip_address(normalized)
        except ValueError:
            if ":" in normalized:
                raise ConfigurationError(
                    f"配置项 {section_name}.{key} 不能包含端口：{item}"
                )
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _resolved_path(value: str, relative_root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (relative_root / path).resolve()


def select_ai_model(
    settings: AppSettings,
    profile_id: str,
    *,
    reasoning_mode: str | None = None,
) -> AppSettings:
    """Returns settings with one configured model profile selected."""
    try:
        normalized_id = AiModelProfile(profile_id.strip())
    except ValueError as exc:
        available = "、".join(item.value for item in AiModelProfile)
        raise ConfigurationError(
            f"未定义的大模型枚举值：{profile_id}",
            details=f"可用模型枚举：{available}",
        ) from exc
    profile = next(
        (item for item in settings.ai_models if item.profile_id == normalized_id),
        None,
    )
    if profile is None:
        available = "、".join(
            item.profile_id.value for item in settings.ai_models
        )
        raise ConfigurationError(
            f"未找到大模型配置：{normalized_id}",
            details=f"可用模型配置：{available}",
        )
    selected_mode = (reasoning_mode or profile.default_reasoning_mode).strip().lower()
    if selected_mode not in profile.reasoning_modes:
        supported = "、".join(profile.reasoning_modes)
        raise ConfigurationError(
            f"模型 {profile.display_name} 不支持推理模式 {selected_mode}",
            details=f"支持的模式：{supported}",
        )
    return replace(
        settings,
        ai=replace(profile, default_reasoning_mode=selected_mode),
    )


def _load_ai_models(
    ai_root: dict[str, Any],
    *,
    config_dir: Path,
) -> tuple[tuple[OllamaSettings, ...], AiModelProfile]:
    ai_name = "ai"
    provider = _text(ai_root, "provider", ai_name).lower()
    if provider != "ollama":
        raise ConfigurationError("配置项 ai.provider 目前只支持 ollama")
    active_model_value = _text(ai_root, "active_model", ai_name)
    try:
        active_model = AiModelProfile(active_model_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"ai.active_model 不是已定义的模型枚举：{active_model_value}"
        ) from exc
    models_dir = _resolved_path(_text(ai_root, "models_dir", ai_name), config_dir)
    if not models_dir.is_dir():
        raise ConfigurationError(f"大模型配置目录不存在：{models_dir}")

    base_url = _text(ai_root, "base_url", ai_name).rstrip("/")
    chat_path = _text(ai_root, "chat_path", ai_name)
    prompt_path = _resolved_path(_text(ai_root, "prompt_path", ai_name), config_dir)
    profiles: list[OllamaSettings] = []
    seen_ids: set[AiModelProfile] = set()

    def sampling(
        section: dict[str, Any], section_name: str
    ) -> AiSamplingSettings:
        return AiSamplingSettings(
            temperature=_number(section, "temperature", section_name),
            top_p=_number(section, "top_p", section_name),
            top_k=_integer(section, "top_k", section_name),
            min_p=_number(section, "min_p", section_name),
            presence_penalty=_number(section, "presence_penalty", section_name),
            repeat_penalty=_number(section, "repeat_penalty", section_name),
        )

    for profile_path in sorted(models_dir.glob("*.toml")):
        try:
            with profile_path.open("rb") as stream:
                profile_data = tomllib.load(stream)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(
                f"大模型配置 TOML 格式错误：{profile_path.name}",
                details=str(exc),
            ) from exc
        model = _required_section(profile_data, "model")
        sampling_root = _required_section(profile_data, "sampling")
        non_thinking = _required_section(
            sampling_root, "non_thinking", parent="sampling"
        )
        thinking = _required_section(sampling_root, "thinking", parent="sampling")
        section_name = f"{profile_path.name}:model"
        profile_id_value = _text(model, "id", section_name)
        try:
            profile_id = AiModelProfile(profile_id_value)
        except ValueError as exc:
            raise ConfigurationError(
                f"模型配置使用了未定义的枚举值：{profile_id_value}"
            ) from exc
        if profile_id in seen_ids:
            raise ConfigurationError(f"大模型配置 ID 重复：{profile_id}")
        seen_ids.add(profile_id)
        reasoning_modes = _string_list(
            model, "reasoning_modes", section_name
        )
        default_mode = _text(
            model, "default_reasoning_mode", section_name
        ).lower()
        if default_mode not in reasoning_modes:
            raise ConfigurationError(
                f"配置项 {section_name}.default_reasoning_mode "
                "必须存在于 reasoning_modes 中"
            )
        request_timeout = _integer(
            model, "request_timeout_seconds", section_name
        )
        num_ctx = _integer(model, "num_ctx", section_name)
        num_predict = _integer(model, "num_predict", section_name)
        if request_timeout == 0 or num_ctx == 0 or num_predict == 0:
            raise ConfigurationError(
                f"配置 {profile_path.name} 的超时、num_ctx 和 num_predict 必须大于 0"
            )
        profiles.append(
            OllamaSettings(
                profile_id=profile_id,
                display_name=_text(model, "display_name", section_name),
                source_url=_text(model, "source_url", section_name),
                native_context_length=_integer(
                    model, "native_context_length", section_name
                ),
                reasoning_modes=reasoning_modes,
                base_url=base_url,
                chat_path=chat_path,
                model=_text(model, "ollama_name", section_name),
                prompt_path=prompt_path,
                default_reasoning_mode=default_mode,
                request_timeout_seconds=request_timeout,
                keep_alive=_text(model, "keep_alive", section_name),
                num_ctx=num_ctx,
                num_predict=num_predict,
                retry_count=_integer(model, "retry_count", section_name),
                retry_delay_ms=_integer(model, "retry_delay_ms", section_name),
                non_thinking=sampling(
                    non_thinking,
                    f"{profile_path.name}:sampling.non_thinking",
                ),
                thinking=sampling(
                    thinking,
                    f"{profile_path.name}:sampling.thinking",
                ),
            )
        )
    if not profiles:
        raise ConfigurationError(f"大模型配置目录中没有 TOML 文件：{models_dir}")
    missing_profiles = set(AiModelProfile) - seen_ids
    if missing_profiles:
        missing = "、".join(
            item.value
            for item in sorted(missing_profiles, key=lambda value: value.value)
        )
        raise ConfigurationError(f"模型枚举缺少对应配置文件：{missing}")
    if active_model not in seen_ids:
        raise ConfigurationError(f"ai.active_model 指定了不存在的模型：{active_model}")
    return tuple(profiles), active_model


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
    rights_credentials = _required_section(
        rights_root, "credentials", parent="rights_statement"
    )
    rights_selectors = _required_section(
        rights_root, "selectors", parent="rights_statement"
    )
    rights_login = _required_section(
        rights_selectors, "login", parent="rights_statement.selectors"
    )
    rights_captcha = _required_section(
        rights_root, "captcha", parent="rights_statement"
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

    ai_root = _required_section(data, "ai")

    relative_root = data_root or Path.cwd()
    common_name = "common"
    rights_browser_name = "rights_statement.browser"
    rights_site_name = "rights_statement.site"
    rights_credentials_name = "rights_statement.credentials"
    rights_login_name = "rights_statement.selectors.login"
    rights_captcha_name = "rights_statement.captcha"
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

    ai_models, active_ai_model = _load_ai_models(
        ai_root,
        config_dir=path.parent.resolve(),
    )
    active_ai = next(
        item for item in ai_models if item.profile_id == active_ai_model
    )

    captcha = CaptchaSettings(
        enabled=_boolean(rights_captcha, "enabled", rights_captcha_name),
        allowed_hosts=_plain_string_list(
            rights_captcha, "allowed_hosts", rights_captcha_name
        ),
        verify_path=_text(rights_captcha, "verify_path", rights_captcha_name),
        max_attempts=_integer(
            rights_captcha, "max_attempts", rights_captcha_name
        ),
        click_delay_min_ms=_integer(
            rights_captcha, "click_delay_min_ms", rights_captcha_name
        ),
        click_delay_max_ms=_integer(
            rights_captcha, "click_delay_max_ms", rights_captcha_name
        ),
        click_offset_max_px=_integer(
            rights_captcha, "click_offset_max_px", rights_captcha_name
        ),
        frame_timeout_ms=_integer(
            rights_captcha, "frame_timeout_ms", rights_captcha_name
        ),
        verify_timeout_ms=_integer(
            rights_captcha, "verify_timeout_ms", rights_captcha_name
        ),
        image_change_timeout_ms=_integer(
            rights_captcha, "image_change_timeout_ms", rights_captcha_name
        ),
    )
    if captcha.max_attempts < 1:
        raise ConfigurationError(
            "配置项 rights_statement.captcha.max_attempts 必须大于 0"
        )
    if not captcha.verify_path.startswith("/"):
        raise ConfigurationError(
            "配置项 rights_statement.captcha.verify_path 必须以 / 开头"
        )
    if captcha.click_delay_max_ms < captcha.click_delay_min_ms:
        raise ConfigurationError(
            "配置项 rights_statement.captcha.click_delay_max_ms "
            "不能小于 click_delay_min_ms"
        )
    if min(
        captcha.frame_timeout_ms,
        captcha.verify_timeout_ms,
        captcha.image_change_timeout_ms,
    ) < 1:
        raise ConfigurationError(
            "验证码超时配置必须大于 0"
        )

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
        rights_credentials=RightsCredentialsSettings(
            credit_code_env=_text(
                rights_credentials,
                "credit_code_env",
                rights_credentials_name,
            ),
            mobile_env=_text(
                rights_credentials,
                "mobile_env",
                rights_credentials_name,
            ),
            password_env=_text(
                rights_credentials,
                "password_env",
                rights_credentials_name,
            ),
        ),
        login=LoginSelectors(
            unit_login_tab=_text(rights_login, "unit_login_tab", rights_login_name),
            account_password_tab=_text(
                rights_login,
                "account_password_tab",
                rights_login_name,
            ),
            credit_code=_text(rights_login, "credit_code", rights_login_name),
            mobile=_text(rights_login, "mobile", rights_login_name),
            password=_text(rights_login, "password", rights_login_name),
            submit=_text(rights_login, "submit", rights_login_name),
            authenticated_marker=_text(
                rights_login, "authenticated_marker", rights_login_name
            ),
        ),
        captcha=captcha,
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
        ai=active_ai,
        ai_models=ai_models,
    )
