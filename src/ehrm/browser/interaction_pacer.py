from __future__ import annotations

import logging
import random
from collections.abc import Callable
from typing import TypeVar

from ehrm.core.exceptions import TaskCancelledError
from ehrm.core.settings import BrowserInteractionPacingSettings


_LOGGER = logging.getLogger("ehrm")
_Result = TypeVar("_Result")


class BrowserInteractionPacer:
    """Applies one shared, cancellation-aware delay before DOM actions.

    Callers deliberately invoke this component only for interactions that
    mutate browser DOM state (click/fill/select/check). Network requests and
    readiness polling therefore remain immediate.
    """

    def __init__(
        self,
        settings: BrowserInteractionPacingSettings,
        pause: Callable[[int], None],
        *,
        cancel_check: Callable[[], bool] | None = None,
        delay_sampler: Callable[[int, int], int] | None = None,
        cancelled_error: Callable[[], Exception] | None = None,
        cancellation_poll_ms: int = 100,
    ) -> None:
        self.settings = settings
        self._pause = pause
        self._cancel_check = cancel_check
        self._delay_sampler = delay_sampler or random.SystemRandom().randint
        self._cancelled_error = cancelled_error or (
            lambda: TaskCancelledError("用户提前停止任务")
        )
        self._cancellation_poll_ms = max(1, cancellation_poll_ms)

    def wait_before_action(self) -> int:
        """Waits for the sampled interval and returns its milliseconds."""
        self._raise_if_cancelled()
        if not self.settings.enabled:
            return 0

        delay_ms = self._delay_sampler(
            self.settings.min_delay_ms,
            self.settings.max_delay_ms,
        )
        remaining_ms = max(0, int(delay_ms))
        _LOGGER.debug("智慧人社 DOM 操作前随机等待 %dms", remaining_ms)
        while remaining_ms > 0:
            self._raise_if_cancelled()
            current_ms = min(self._cancellation_poll_ms, remaining_ms)
            self._pause(current_ms)
            remaining_ms -= current_ms
        self._raise_if_cancelled()
        return max(0, int(delay_ms))

    def perform(self, action: Callable[[], _Result]) -> _Result:
        """Runs one DOM action after exactly one shared pacing interval."""
        self.wait_before_action()
        return action()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise self._cancelled_error()
