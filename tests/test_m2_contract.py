"""M2 契约：千分位、全角、哨兵、时区、大整数与列定义。"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.config import SENTINELS
from app.modules.m2_contract.coerce import (
    parse_amount,
    parse_date,
    parse_direction,
    parse_fee,
)


def test_thousands_and_fullwidth_amount():
    # TRAP-06：千分位与全角数字
    assert parse_amount("1,200.50", SENTINELS) == Decimal("1200.50")
    assert parse_amount("２，１００．００", SENTINELS) == Decimal("2100.00")
    assert parse_amount("(1,000.50)", SENTINELS) == Decimal("-1000.50")


def test_sentinel_amount_returns_none():
    # TRAP-07：空值哨兵不是 0
    for value in ("-", "--", "N/A", "NULL", "未知", "", "  "):
        assert parse_amount(value, SENTINELS) is None


def test_fee_sentinel_counts_zero():
    assert parse_fee("-", SENTINELS) == Decimal("0.00")
    assert parse_fee("1.50", SENTINELS) == Decimal("1.50")


def test_instant_offsets_collapse_to_same_utc():
    # TRAP-11：同一时刻两种写法归一
    left = parse_date("2026-03-03T10:00:00+08:00")
    right = parse_date("2026-03-03T02:00:00Z")
    assert left == right
    assert left.astimezone(timezone.utc).hour == 2


def test_date_only_uses_shanghai_midnight():
    # TRAP-11：纯日期按 +08:00 当日 00:00
    parsed = parse_date("2026-03-06")
    assert parsed == datetime(2026, 3, 5, 16, 0, tzinfo=timezone.utc)


def test_big_integer_id_kept_as_string(client):
    # TRAP-09：超过 2^53 的编号不转数字
    client.post("/api/statements/import",
                data={"side": "bank", "sample": "bank_statement_dirty.csv"})
    rows = client.get("/api/statements", params={"side": "bank"}).json()["rows"]
    big = next(row for row in rows if row["txn_no"] == "9007199254740993")
    assert isinstance(big["txn_no"], str)
    assert big["txn_no"] == "9007199254740993"


def test_direction_aliases_map_to_sign():
    for value in ("贷", "收", "credit", "CR", "+"):
        assert parse_direction(value) == 1
    for value in ("借", "付", "debit", "DR", "-"):
        assert parse_direction(value) == -1
    assert parse_direction("X") is None


def test_contract_exposes_tolerance_window_subset(client):
    body = client.get("/api/contract").json()
    assert body["tolerance"] == "0.02"
    assert body["window_days"] == 3
    assert body["subset_max"] == 4
    assert {field["name"] for field in body["fields"]["bank"]} >= {"txn_no", "amount", "fee"}
    assert {field["name"] for field in body["fields"]["ledger"]} >= {"txn_no", "account"}


def test_invalid_amount_and_date_raise():
    with pytest.raises(ValueError):
        parse_amount("12元8角", SENTINELS)
    with pytest.raises(ValueError):
        parse_date("2026-13-40")
