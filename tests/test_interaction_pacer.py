from unittest.mock import Mock

import pytest

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.core.exceptions import TaskCancelledError
from ehrm.core.settings import BrowserInteractionPacingSettings


def _settings(*, enabled: bool = True) -> BrowserInteractionPacingSettings:
    return BrowserInteractionPacingSettings(
        enabled=enabled,
        min_delay_ms=1000,
        max_delay_ms=2000,
    )


def test_dom_action_uses_one_sample_from_common_range_before_action() -> None:
    events: list[object] = []
    sampler = Mock(return_value=1350)
    pacer = BrowserInteractionPacer(
        _settings(),
        lambda milliseconds: events.append(milliseconds),
        delay_sampler=sampler,
        cancellation_poll_ms=500,
    )

    result = pacer.perform(lambda: events.append("action") or "done")

    assert result == "done"
    sampler.assert_called_once_with(1000, 2000)
    assert events == [500, 500, 350, "action"]


def test_disabled_pacing_runs_action_without_sleeping() -> None:
    pause = Mock()
    action = Mock(return_value="done")
    pacer = BrowserInteractionPacer(_settings(enabled=False), pause)

    assert pacer.perform(action) == "done"
    pause.assert_not_called()
    action.assert_called_once_with()


def test_pacing_can_be_cancelled_during_long_delay() -> None:
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    pacer = BrowserInteractionPacer(
        _settings(),
        lambda _milliseconds: None,
        cancel_check=cancelled,
        delay_sampler=Mock(return_value=1500),
        cancellation_poll_ms=100,
    )

    with pytest.raises(TaskCancelledError):
        pacer.perform(lambda: None)
