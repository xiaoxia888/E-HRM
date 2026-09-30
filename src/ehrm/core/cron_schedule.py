"""Shared five-field Unix cron adapter, evaluated by APScheduler."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

TIMEZONE = ZoneInfo("Asia/Shanghai")
_DAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _weekdays(value: str) -> str:
    # Unix: 0/7=Sunday. APScheduler: 0=Monday. Normalize to names before passing on.
    if value == "*":
        return value
    selected = set()
    def number(text):
        result = _DAYS.get(text.lower())
        result = int(text) if result is None else result
        if not 0 <= result <= 7:
            raise ValueError("星期必须为 0–7 或 sun–sat，0/7 表示周日")
        return result
    for part in value.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1 or step > 7:
            raise ValueError("星期步长必须为 1–7")
        if base == "*":
            start, end = 0, 6
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = number(left), number(right)
        else:
            start = number(base)
            end = 7 if step_text else start
        if start > end:
            raise ValueError("星期范围起点不能大于终点")
        selected.update(day % 7 for day in range(start, end + 1, step))
    return ",".join(name for name, day in _DAYS.items() if day in selected)


def cron_trigger(expression: str):
    try:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError("需要五个字段：分 时 日 月 星期")
        minute, hour, day, month, weekday = parts
        common = dict(minute=minute, hour=hour, month=month, timezone=TIMEZONE)
        unrestricted_day = day.startswith("*")
        unrestricted_weekday = weekday.startswith("*")
        weekday = _weekdays(weekday)
        # Unix cron uses OR when both day-of-month and day-of-week are restricted.
        if not unrestricted_day and not unrestricted_weekday:
            return OrTrigger([CronTrigger(day=day, **common), CronTrigger(day_of_week=weekday, **common)])
        return CronTrigger(day=day, day_of_week=weekday, **common)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Cron 表达式无效：{exc}") from exc


def upcoming(expression: str, count: int = 5, now: datetime | None = None) -> list[str]:
    trigger = cron_trigger(expression)
    previous = None
    current = now or datetime.now(TIMEZONE)
    result = []
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, current)
        if fire is None:
            break
        result.append(fire.isoformat())
        previous, current = fire, fire + timedelta(microseconds=1)
    if not result:
        raise ValueError("Cron 表达式没有可执行日期")
    return result
