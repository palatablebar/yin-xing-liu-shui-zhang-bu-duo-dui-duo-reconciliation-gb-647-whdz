"""匹配求解：候选排序 → 不重叠挑选 → 组内合计与手续费分摊。"""
from __future__ import annotations

import hashlib
from decimal import Decimal

from ...config import dec
from ..m4_candidates import window
from . import fees, subset


def _match_id(bank_ids: list[str], ledger_ids: list[str]) -> str:
    key = hashlib.sha1(
        f"{','.join(bank_ids)}|{','.join(ledger_ids)}".encode("utf-8")
    ).hexdigest()[:10]
    return f"m-{key}"


def _index(records: list[dict], side: str) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for record in records:
        if record["side"] != side or record["status"] != "valid":
            continue
        table[record["txn_no"]] = {
            "txn_no": record["txn_no"],
            "amount": dec(record["amount"]),
            "fee": dec(record["fee"]),
            "direction": int(record["direction"]),
            "posted_at": window.parse_instant(record["posted_at"]),
        }
    return table


def solve(candidates: list[dict], records: list[dict], settings) -> list[dict]:
    bank = _index(records, "bank")
    ledger = _index(records, "ledger")
    ordered = sorted(candidates, key=subset.priority_key)
    chosen = subset.choose_disjoint(ordered)

    groups: list[dict] = []
    for candidate in chosen:
        bank_rows = [bank[key] for key in candidate["bank_ids"] if key in bank]
        ledger_rows = [ledger[key] for key in candidate["ledger_ids"] if key in ledger]
        if len(bank_rows) != len(candidate["bank_ids"]) or len(ledger_rows) != len(candidate["ledger_ids"]):
            continue
        bank_sum = sum((row["amount"] for row in bank_rows), Decimal("0.00"))
        ledger_sum = sum((row["amount"] for row in ledger_rows), Decimal("0.00"))
        bank_signed = sum((row["amount"] * row["direction"] for row in bank_rows), Decimal("0.00"))
        ledger_signed = sum((row["amount"] * row["direction"] for row in ledger_rows), Decimal("0.00"))
        groups.append(
            {
                "match_id": _match_id(candidate["bank_ids"], candidate["ledger_ids"]),
                "tier": int(candidate["tier"]),
                "bank_ids": list(candidate["bank_ids"]),
                "ledger_ids": list(candidate["ledger_ids"]),
                "bank_sum": bank_sum,
                "ledger_sum": ledger_sum,
                "diff": abs(bank_sum - ledger_sum).quantize(settings.fee_quantum),
                "day_gap": int(candidate["day_gap"]),
                "bank_signed": bank_signed,
                "ledger_signed": ledger_signed,
                "fee_actual": sum((row["fee"] for row in bank_rows), Decimal("0.00")),
            }
        )

    groups.sort(key=lambda group: (group["tier"], group["match_id"]))
    fee_total = sum((group["fee_actual"] for group in groups), Decimal("0.00"))
    allocations = fees.allocate(
        fee_total,
        [abs(group["bank_signed"]) for group in groups],
        settings.fee_quantum,
        [group["match_id"] for group in groups],
    )
    for group, allocated in zip(groups, allocations):
        group["fee_alloc"] = allocated
    return groups
