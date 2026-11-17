"""候选生成：一对一、一对多（账簿子集和）、多对一（银行子集和）。

- 金额差 ≤ 容差、日期差 ≤ 窗口、方向相同；
- 子集最多 4 条，按金额降序枚举，超过目标 + 容差的分支不再递归；
- 手续费不参与匹配金额，只随银行行进入成本统计。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from ...config import dec
from . import window

QUANT = Decimal("0.01")


def as_row(record: dict) -> dict:
    return {
        "side": record["side"],
        "txn_no": record["txn_no"],
        "account": record["account"],
        "posted_at": window.parse_instant(record["posted_at"]),
        "direction": int(record["direction"]),
        "amount": dec(record["amount"]),
        "fee": dec(record["fee"]),
    }


def valid_rows(records: list[dict], side: str) -> list[dict]:
    return [as_row(record) for record in records
            if record["status"] == "valid" and record["side"] == side]


def bounded_subsets(rows: list[dict], target: Decimal, tolerance: Decimal,
                    max_items: int) -> list[list[dict]]:
    ordered = sorted(rows, key=lambda row: (-row["amount"], row["txn_no"]))
    results: list[list[dict]] = []
    total_rows = len(ordered)

    def walk(start: int, chosen: list[dict], total: Decimal) -> None:
        if len(chosen) >= 2 and abs(total - target) <= tolerance:
            results.append(list(chosen))
        if len(chosen) >= max_items:
            return
        for index in range(start, total_rows):
            row = ordered[index]
            next_total = total + row["amount"]
            if next_total > target + tolerance:
                continue
            chosen.append(row)
            walk(index + 1, chosen, next_total)
            chosen.pop()

    walk(0, [], Decimal("0.00"))
    return results


def _day_gap(anchor: datetime, rows: list[dict], zone) -> int:
    return max((window.day_gap(anchor, row["posted_at"], zone) for row in rows), default=0)


def _candidate(tier: int, banks: list[dict], ledgers: list[dict], zone) -> dict:
    bank_ids = sorted(row["txn_no"] for row in banks)
    ledger_ids = sorted(row["txn_no"] for row in ledgers)
    bank_sum = sum((row["amount"] for row in banks), Decimal("0.00"))
    ledger_sum = sum((row["amount"] for row in ledgers), Decimal("0.00"))
    diff = abs(bank_sum - ledger_sum).quantize(QUANT)
    if tier == 1:
        gap = _day_gap(banks[0]["posted_at"], ledgers, zone)
    elif tier == 2:
        gap = _day_gap(banks[0]["posted_at"], ledgers, zone)
    else:
        gap = _day_gap(ledgers[0]["posted_at"], banks, zone)
    key = hashlib.sha1(
        f"{tier}|{','.join(bank_ids)}|{','.join(ledger_ids)}".encode("utf-8")
    ).hexdigest()[:10]
    return {
        "cand_id": f"c{tier}-{key}",
        "tier": tier,
        "bank_ids": bank_ids,
        "ledger_ids": ledger_ids,
        "bank_sum": bank_sum,
        "ledger_sum": ledger_sum,
        "diff": diff,
        "day_gap": gap,
    }


def build(records: list[dict], settings) -> list[dict]:
    zone = window.tzinfo(settings.tz_name)
    bank = valid_rows(records, "bank")
    ledger = valid_rows(records, "ledger")
    tolerance = settings.tolerance
    max_items = settings.subset_max
    results: list[dict] = []

    for bank_row in bank:
        for ledger_row in ledger:
            if bank_row["direction"] != ledger_row["direction"]:
                continue
            gap = window.day_gap(bank_row["posted_at"], ledger_row["posted_at"], zone)
            if gap > settings.window_days:
                continue
            if abs(bank_row["amount"] - ledger_row["amount"]) <= tolerance:
                results.append(_candidate(1, [bank_row], [ledger_row], zone))

    for bank_row in bank:
        pool = [
            row for row in ledger
            if row["direction"] == bank_row["direction"]
            and window.day_gap(bank_row["posted_at"], row["posted_at"], zone) <= settings.window_days
        ]
        for combo in bounded_subsets(pool, bank_row["amount"], tolerance, max_items):
            results.append(_candidate(2, [bank_row], combo, zone))

    for ledger_row in ledger:
        pool = [
            row for row in bank
            if row["direction"] == ledger_row["direction"]
            and window.day_gap(ledger_row["posted_at"], row["posted_at"], zone) <= settings.window_days
        ]
        for combo in bounded_subsets(pool, ledger_row["amount"], tolerance, max_items):
            results.append(_candidate(3, combo, [ledger_row], zone))

    results.sort(
        key=lambda item: (
            item["tier"],
            item["diff"],
            item["day_gap"],
            ",".join(item["bank_ids"]),
            ",".join(item["ledger_ids"]),
        )
    )
    return results
