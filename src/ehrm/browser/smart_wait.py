from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import time
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class WaitCondition(Generic[T]):
    """A named state probe participating in a first-completed race.

    A probe returns ``None`` while its state is pending and any non-None value
    when the state is ready. ``stable_for_ms`` is useful for disappearing
    loading indicators that must remain absent during their exit animation.
    """

    name: str
    probe: Callable[[], T | None]
    stable_for_ms: int = 0
    transient_exceptions: tuple[type[Exception], ...] = ()


@dataclass(frozen=True, slots=True)
class WaitResult(Generic[T]):
    condition: str
    value: T
    elapsed_ms: int


class SmartWaitTimeoutError(TimeoutError):
    def __init__(
        self,
        description: str,
        *,
        timeout_ms: int,
        condition_names: Sequence[str],
        last_errors: dict[str, str],
    ) -> None:
        states = "、".join(condition_names)
        details = f"等待状态：{states}；最大等待：{timeout_ms}ms"
        if last_errors:
            errors = "；".join(
                f"{name}={message}" for name, message in last_errors.items()
            )
            details += f"；最近瞬时错误：{errors}"
        super().__init__(f"{description}超时（{details}）")
        self.description = description
        self.timeout_ms = timeout_ms
        self.condition_names = tuple(condition_names)
        self.last_errors = dict(last_errors)


class SmartWait:
    """Condition-driven wait loop with a deadline and cancellation support."""

    def __init__(
        self,
        pause: Callable[[int], None],
        *,
        poll_interval_ms: int = 100,
        cancel_check: Callable[[], bool] | None = None,
        cancelled_error: Callable[[], Exception] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_interval_ms < 1:
            raise ValueError("poll_interval_ms 必须大于 0")
        self._pause = pause
        self._poll_interval_ms = poll_interval_ms
        self._cancel_check = cancel_check
        self._cancelled_error = cancelled_error
        self._clock = clock

    def first(
        self,
        conditions: Sequence[WaitCondition[T]],
        *,
        timeout_ms: int,
        description: str,
    ) -> WaitResult[T]:
        if not conditions:
            raise ValueError("智能等待至少需要一个候选状态")
        if timeout_ms < 1:
            raise ValueError("timeout_ms 必须大于 0")

        started_at = self._clock()
        deadline = started_at + timeout_ms / 1000
        stable_since: dict[str, float] = {}
        last_errors: dict[str, str] = {}

        while True:
            self._raise_if_cancelled()
            now = self._clock()
            for condition in conditions:
                try:
                    value = condition.probe()
                    last_errors.pop(condition.name, None)
                except condition.transient_exceptions as exc:
                    stable_since.pop(condition.name, None)
                    last_errors[condition.name] = str(exc)
                    continue

                if value is None:
                    stable_since.pop(condition.name, None)
                    continue
                if condition.stable_for_ms > 0:
                    first_seen = stable_since.setdefault(condition.name, now)
                    if now - first_seen < condition.stable_for_ms / 1000:
                        continue
                elapsed_ms = max(0, round((now - started_at) * 1000))
                return WaitResult(condition.name, value, elapsed_ms)

            now = self._clock()
            if now >= deadline:
                raise SmartWaitTimeoutError(
                    description,
                    timeout_ms=timeout_ms,
                    condition_names=[condition.name for condition in conditions],
                    last_errors=last_errors,
                )
            remaining_ms = max(1, round((deadline - now) * 1000))
            self._pause(min(self._poll_interval_ms, remaining_ms))

    def _raise_if_cancelled(self) -> None:
        if self._cancel_check is None or not self._cancel_check():
            return
        if self._cancelled_error is not None:
            raise self._cancelled_error()
        raise RuntimeError("等待已取消")
