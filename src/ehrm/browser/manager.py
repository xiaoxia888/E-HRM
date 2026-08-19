from __future__ import annotations

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from ehrm.core.settings import BrowserSettings


class BrowserManager:
    def __init__(
        self, settings: BrowserSettings, *, headless: bool | None = None
    ) -> None:
        self.settings = settings
        self.headless = settings.headless if headless is None else headless
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserManager":
        self.settings.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            self.context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.settings.user_data_dir,
                headless=self.headless,
                slow_mo=self.settings.slow_mo_ms,
                accept_downloads=True,
            )
            self.context.set_default_timeout(self.settings.action_timeout_ms)
            self.context.set_default_navigation_timeout(
                self.settings.navigation_timeout_ms
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    @property
    def page(self) -> Page:
        if self.context is None:
            raise RuntimeError("BrowserManager 尚未启动")
        return self.context.pages[0] if self.context.pages else self.context.new_page()

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
