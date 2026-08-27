from __future__ import annotations

import logging

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from ehrm.core.settings import BrowserSettings


_LOGGER = logging.getLogger("ehrm")


class BrowserManager:
    def __init__(
        self,
        settings: BrowserSettings,
        *,
        headless: bool | None = None,
        ignore_https_errors: bool = False,
        stealth_enabled: bool = False,
    ) -> None:
        self.settings = settings
        self.headless = settings.headless if headless is None else headless
        self.ignore_https_errors = ignore_https_errors
        self.stealth_enabled = stealth_enabled
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
            if self.stealth_enabled:
                self._apply_stealth(self.context)
            self.context.set_default_timeout(self.settings.action_timeout_ms)
            self.context.set_default_navigation_timeout(
                self.settings.navigation_timeout_ms
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    @staticmethod
    def _apply_stealth(context: BrowserContext) -> None:
        """Uses playwright-stealth's official synchronous context API."""

        from playwright_stealth import Stealth

        Stealth(
            navigator_platform=False,
            navigator_platform_override=None,
            navigator_languages=False,
            navigator_languages_override=None,
            webgl_vendor=False,
        ).apply_stealth_sync(context)
        _LOGGER.info("测试环境 stealth 已通过官方同步 API 注入")

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
