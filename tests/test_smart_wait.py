from __future__ import annotations

from collections.abc import Callable

import pytest

from ehrm.browser.smart_wait import (
    SmartWait,
    SmartWaitTimeoutError,
    WaitCondition,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[int] = []

    def clock(self) -> float:
        return self.now

    def pause(self, milliseconds: int) -> None:
        self.pauses.append(milliseconds)
        self.now += milliseconds / 1000


def _waiter(
    fake_time: FakeTime,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> SmartWait:
    return SmartWait(
        fake_time.pause,
        poll_interval_ms=100,
        cancel_check=cancel_check,
        cancelled_error=lambda: ValueError("cancelled"),
        clock=fake_time.clock,
    )


def test_first_returns_immediately_when_a_state_is_ready() -> None:
    fake_time = FakeTime()

    result = _waiter(fake_time).first(
        [
            WaitCondition("pending", lambda: None),
            WaitCondition("ready", lambda: "value"),
        ],
        timeout_ms=1000,
        description="测试状态",
    )

    assert result.condition == "ready"
    assert result.value == "value"
    assert result.elapsed_ms == 0
    assert fake_time.pauses == []


def test_stable_condition_must_remain_ready_for_its_window() -> None:
    fake_time = FakeTime()
    states = iter([True, None, True, True, True])

    result = _waiter(fake_time).first(
        [
            WaitCondition(
                "stable",
                lambda: next(states),
                stable_for_ms=200,
            )
        ],
        timeout_ms=1000,
        description="稳定状态",
    )

    assert result.condition == "stable"
    assert result.elapsed_ms == 400


def test_transient_probe_error_is_retried() -> None:
    fake_time = FakeTime()
    attempts = 0

    def probe() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise LookupError("DOM replaced")
        return "ready"

    result = _waiter(fake_time).first(
        [
            WaitCondition(
                "dom-ready",
                probe,
                transient_exceptions=(LookupError,),
            )
        ],
        timeout_ms=1000,
        description="DOM",
    )

    assert result.value == "ready"
    assert attempts == 2


def test_timeout_reports_all_competing_states() -> None:
    fake_time = FakeTime()

    with pytest.raises(SmartWaitTimeoutError, match="地区已生效、地区弹窗"):
        _waiter(fake_time).first(
            [
                WaitCondition("地区已生效", lambda: None),
                WaitCondition("地区弹窗", lambda: None),
            ],
            timeout_ms=250,
            description="等待地区页面",
        )


def test_cancellation_stops_without_waiting_for_deadline() -> None:
    fake_time = FakeTime()

    with pytest.raises(ValueError, match="cancelled"):
        _waiter(fake_time, cancel_check=lambda: True).first(
            [WaitCondition("pending", lambda: None)],
            timeout_ms=1000,
            description="取消测试",
        )

    assert fake_time.pauses == []
