"""确定性择一：按层级、金额差、日期差、业务号排序后做不重叠挑选。

同一批候选无论以什么顺序传入，排序键都相同；行不会被两组同时占用。
"""
from __future__ import annotations

from decimal import Decimal

TIER_NAMES = {1: "一对一", 2: "一对多", 3: "多对一"}


def priority_key(candidate: dict) -> tuple:
    return (
        int(candidate["tier"]),
        abs(Decimal(str(candidate["diff"]))),
        int(candidate["day_gap"]),
        ",".join(candidate["bank_ids"]),
        ",".join(candidate["ledger_ids"]),
    )


def choose_disjoint(ordered: list[dict]) -> list[dict]:
    used_bank: set[str] = set()
    used_ledger: set[str] = set()
    chosen: list[dict] = []
    for candidate in ordered:
        banks = set(candidate["bank_ids"])
        ledgers = set(candidate["ledger_ids"])
        if banks & used_bank or ledgers & used_ledger:
            continue
        used_bank |= banks
        used_ledger |= ledgers
        chosen.append(candidate)
    return chosen
