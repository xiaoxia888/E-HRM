from __future__ import annotations

import json
import logging
import sys

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from ehrm.core.settings import BrowserSettings


_LOGGER = logging.getLogger("ehrm")


def _navigator_platform() -> str:
    if sys.platform == "darwin":
        return "MacIntel"
    if sys.platform == "win32":
        return "Win32"
    return "Linux x86_64"


class BrowserManager:
    def __init__(
        self,
        settings: BrowserSettings,
        *,
        headless: bool | None = None,
        ignore_https_errors: bool = False,
        stealth_allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.settings = settings
        self.headless = settings.headless if headless is None else headless
        self.ignore_https_errors = ignore_https_errors
        self.stealth_allowed_hosts = tuple(
            sorted({host.lower().rstrip(".") for host in stealth_allowed_hosts})
        )
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserManager":
        self.settings.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            browser_type = getattr(self._playwright, self.settings.engine)
            launch_options: dict[str, object] = {
                "user_data_dir": self.settings.user_data_dir,
                "headless": self.headless,
                "slow_mo": self.settings.slow_mo_ms,
                "accept_downloads": True,
                "ignore_https_errors": self.ignore_https_errors,
            }
            if self.settings.channel:
                launch_options["channel"] = self.settings.channel
            self.context = browser_type.launch_persistent_context(
                **launch_options,
            )
            if self.stealth_allowed_hosts:
                self._apply_host_limited_stealth(self.context)
            self.context.set_default_timeout(self.settings.action_timeout_ms)
            self.context.set_default_navigation_timeout(
                self.settings.navigation_timeout_ms
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    def _apply_host_limited_stealth(self, context: BrowserContext) -> None:
        """Inject stealth evasions only into documents on configured test hosts."""

        from playwright_stealth import Stealth

        allowed_hosts = json.dumps(
            self.stealth_allowed_hosts,
            ensure_ascii=True,
        )
        stealth_payload = Stealth(
            navigator_languages_override=("zh-CN", "zh"),
            navigator_platform_override=_navigator_platform(),
            # Keep the browser's real GPU values. A hard-coded WebGL renderer
            # would create a contradictory fingerprint across macOS/Windows.
            webgl_vendor=False,
        ).script_payload
        guarded_payload = f"""
(() => {{
    const allowedHosts = new Set({allowed_hosts});
    const documentHostname = globalThis.location?.hostname?.toLowerCase() || "";
    let topLevelHostname = documentHostname;
    if (globalThis.top !== globalThis) {{
        try {{
            topLevelHostname = globalThis.top.location.hostname.toLowerCase();
        }} catch (_) {{
            try {{
                topLevelHostname = new URL(document.referrer).hostname.toLowerCase();
            }} catch (_) {{
                topLevelHostname = "";
            }}
        }}
    }}
    if (
        !allowedHosts.has(documentHostname)
        && !allowedHosts.has(topLevelHostname)
    ) {{
        return;
    }}
    {stealth_payload}
}})();
"""
        context.add_init_script(script=guarded_payload)
        _LOGGER.info(
            "测试环境 stealth 已启用，允许主机：%s",
            "、".join(self.stealth_allowed_hosts),
        )

    @property
    def page(self) -> Page:
        if self.context is None:
            raise RuntimeError("BrowserManager 尚未启动")
        open_pages = [page for page in self.context.pages if not page.is_closed()]
        return open_pages[-1] if open_pages else self.context.new_page()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                # Cleanup is best effort. A closed browser must not replace the
                # original authentication/cancellation error.
                pass
            self.context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
