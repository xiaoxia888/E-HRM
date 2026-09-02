from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.core.result import ExecutionResult


class ExceptionManager:
    """Converts all task failures into the same result contract."""

    def __init__(
        self, logger: logging.Logger, screenshot_dir: Path = Path("screenshots")
    ) -> None:
        self.logger = logger
        self.screenshot_dir = screenshot_dir

    def handle(self, exc: Exception, page: Page | None = None) -> ExecutionResult:
        # Cancellation is an operator decision rather than a website failure;
        # taking a diagnostic screenshot only delays a requested stop.
        diagnostic = (
            None
            if isinstance(exc, TaskCancelledError)
            else self._capture_diagnostic(page)
        )
        if isinstance(exc, EhrmError):
            message = display_message(exc.code, exc.message)
            self.logger.error(
                "任务失败 code=%s message=%s internal=%s details=%s diagnostic=%s",
                exc.code,
                message,
                exc.message,
                exc.details,
                diagnostic,
            )
            return ExecutionResult(
                success=False,
                code=str(exc.code),
                message=message,
                diagnostic_path=diagnostic,
            )

        self.logger.exception("未处理异常 diagnostic=%s", diagnostic)
        return ExecutionResult(
            success=False,
            code=str(ErrorCode.UNEXPECTED_ERROR),
            message=display_message(ErrorCode.UNEXPECTED_ERROR),
            diagnostic_path=diagnostic,
        )

    def _capture_diagnostic(self, page: Page | None) -> Path | None:
        if page is None or page.is_closed():
            return None
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshot_dir / f"failure_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
        try:
            page.screenshot(path=path, full_page=True)
            return path
        except Exception:
            return None
