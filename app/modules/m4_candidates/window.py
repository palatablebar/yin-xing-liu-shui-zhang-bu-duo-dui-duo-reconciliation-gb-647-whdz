"""日期窗口与日桶：本地日按 +08:00 划分，桶区间左闭右开 [日初, 次日初)。

候选窗口为「日期差 ≤ 3 天」：等价于本地日集合 [d-3, d+3]；相邻窗口共用一个端点日
但按行归组，不会把同一行计入两个窗口。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def tzinfo(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=8))


def parse_instant(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_day(instant: datetime, zone) -> date:
    return instant.astimezone(zone).date()


def day_gap(left: datetime, right: datetime, zone) -> int:
    return abs((local_day(left, zone) - local_day(right, zone)).days)


def in_window(left: datetime, right: datetime, window_days: int, zone) -> bool:
    return day_gap(left, right, zone) <= window_days


def day_bucket(instant: datetime, zone) -> tuple[datetime, datetime]:
    """返回该时刻所在本地日的 UTC 半开区间 [start, end)。"""
    day = local_day(instant, zone)
    start_local = datetime.combine(day, time(0, 0), tzinfo=zone)
    next_local = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=zone)
    return start_local.astimezone(timezone.utc), next_local.astimezone(timezone.utc)


def in_bucket(instant: datetime, start: datetime, end: datetime) -> bool:
    return start <= instant < end
