from __future__ import annotations

import logging
from typing import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.excel_models import (
    ExcelRunResult,
    ExcelTaskRequest,
)
from ehrm.modules.rights_statement.excel_service import ExcelRightsStatementService


class DesktopWorkbench:
    """Owns one browser and one tab for the entire desktop-app lifetime."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self._browser: BrowserManager | None = None
        self._page: Page | None = None
        self._cancel_check = cancel_check
        self._service = ExcelRightsStatementService(
            settings,
            logger,
            progress_callback,
            cancel_check,
        )

    def __enter__(self) -> "DesktopWorkbench":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._browser is not None:
            return
        self._start_browser()
        LoginService(
            self.page,
            self.settings,
            self._cancel_check,
        ).ensure_authenticated()
        print("工作台登录完成。保持此浏览器标签页开启，可连续执行多个任务。")

    def stop(self) -> None:
        if self._browser is not None:
            self._browser.__exit__(None, None, None)
        self._browser = None
        self._page = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("桌面工作台尚未启动")
        return self._page

    def run(self, request: ExcelTaskRequest) -> ExcelRunResult:
        page = self._ensure_work_page()
        return self._service.execute_with_page(
            page,
            list(request.groups),
            request.mode,
            request.output_dir,
            request.source_excel,
        )

    def _ensure_work_page(self) -> Page:
        try:
            if self._browser is None or self._browser.context is None:
                self._restart_and_login()
            elif self._page is None or self._page.is_closed():
                # A newly created tab does not inherit this site's tab-scoped login.
                self._page = self._browser.context.new_page()
                LoginService(
                    self._page,
                    self.settings,
                    self._cancel_check,
                ).ensure_authenticated()

            page = self.page
            self.logger.info(
                "工作页签恢复 page_closed=%s context_pages=%s url=%s",
                page.is_closed(),
                len(self._browser.context.pages) if self._browser and self._browser.context else 0,
                page.url,
            )
            page.bring_to_front()
            protected_url = self.settings.site.rights_statement_url
            if protected_url:
                page.goto(protected_url, wait_until="domcontentloaded")
                page.wait_for_timeout(1_000)
                if not LoginService(
                    page,
                    self.settings,
                    self._cancel_check,
                ).is_authenticated():
                    LoginService(
                        page,
                        self.settings,
                        self._cancel_check,
                    ).ensure_authenticated()
            return page
        except PlaywrightError:
            self._restart_and_login()
            return self.page

    def _restart_and_login(self) -> None:
        self.stop()
        self._start_browser()
        LoginService(
            self.page,
            self.settings,
            self._cancel_check,
        ).ensure_authenticated()

    def _start_browser(self) -> None:
        browser = BrowserManager(self.settings.browser, headless=False)
        browser.__enter__()
        self._browser = browser
        self._page = browser.page
