"""金额、日期、方向的归一。

- 金额：全角转半角、去千分位与币种符号、括号负数，Decimal 到分；
- 空值哨兵返回 None，与 0 分开；
- 时间：带偏移按偏移、纯日期按 +08:00 当日 00:00，统一转 UTC。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

QUANT = Decimal("0.01")
CURRENCY_RE = re.compile(r"(人民币|rmb|cny|元|￥|¥|\s)")
DATE_ONLY_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")


def tzinfo(name: str):
    try:
        return ZoneInfo(name)
    except Exception:  # 运行环境缺 tzdata 时固定 +08:00
        return timezone(timedelta(hours=8))


def normalize_text(value) -> str:
    return str(value or "").strip()


def parse_amount(raw, sentinels) -> Decimal | None:
    text = unicodedata.normalize("NFKC", normalize_text(raw))
    if text.lower() in {str(s).lower() for s in sentinels}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = CURRENCY_RE.sub("", text).replace(",", "")
    if text.startswith("+"):
        text = text[1:]
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"金额无法解析：{raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"金额不是有限数：{raw!r}")
    value = value.quantize(QUANT, rounding=ROUND_HALF_UP)
    return -value if negative else value


def parse_fee(raw, sentinels) -> Decimal:
    """手续费的空值哨兵表示「没有手续费」，按 0 计。"""
    value = parse_amount(raw, sentinels)
    return value if value is not None else Decimal("0.00")


def parse_direction(raw) -> int | None:
    from ...config import DIRECTION_ALIASES

    text = normalize_text(raw).lower()
    return DIRECTION_ALIASES.get(text)


def parse_date(raw, tz_name: str = "Asia/Shanghai") -> datetime:
    text = normalize_text(raw)
    if not text:
        raise ValueError("日期为空")
    zone = tzinfo(tz_name)
    if DATE_ONLY_RE.match(text):
        year, month, day = (int(part) for part in re.split(r"[-/]", text))
        local = datetime.combine(date(year, month, day), time(0, 0), tzinfo=zone)
        return local.astimezone(timezone.utc)
    normalized = text.replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"日期无法解析：{raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def signed(amount: Decimal, direction: int) -> Decimal:
    return amount * Decimal(direction)
