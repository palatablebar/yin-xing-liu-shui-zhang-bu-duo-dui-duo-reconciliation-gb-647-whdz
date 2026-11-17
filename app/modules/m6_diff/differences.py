"""对账：银行侧与账簿侧各自守恒，差异逐条归因。

银行合计 = 匹配金额 + 未匹配金额 − 手续费合计
账簿合计 = 匹配金额 + 未匹配金额
匹配差额 = 银行匹配金额 − 账簿匹配金额（容差内允许非 0）
"""
from __future__ import annotations

from decimal import Decimal

from ... import reasons
from ...config import dec
from ..m5_matching.subset import TIER_NAMES

ZERO = Decimal("0.00")


def _signed(record: dict) -> Decimal:
    return dec(record["amount"]) * int(record["direction"])


def reconcile(records: list[dict], matches: list[dict], settings) -> dict:
    valid = [record for record in records if record["status"] == "valid"]
    bank = [record for record in valid if record["side"] == "bank"]
    ledger = [record for record in valid if record["side"] == "ledger"]

    bank_gross = sum((_signed(record) for record in bank), ZERO)
    bank_fee = sum((dec(record["fee"]) for record in bank), ZERO)
    bank_total = bank_gross - bank_fee
    ledger_total = sum((_signed(record) for record in ledger), ZERO)

    matched_bank_ids: set[str] = set()
    matched_ledger_ids: set[str] = set()
    matched_bank_signed = ZERO
    matched_ledger_signed = ZERO
    fee_alloc_total = ZERO
    fee_actual_total = ZERO
    tier_counts: dict[str, int] = {}
    for group in matches:
        matched_bank_ids.update(group["bank_ids"])
        matched_ledger_ids.update(group["ledger_ids"])
        matched_bank_signed += dec(group["bank_signed"])
        matched_ledger_signed += dec(group["ledger_signed"])
        fee_alloc_total += dec(group["fee_alloc"])
        fee_actual_total += dec(group["fee_actual"])
        tier = str(group["tier"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    unmatched_bank = [record for record in bank if record["txn_no"] not in matched_bank_ids]
    unmatched_ledger = [record for record in ledger if record["txn_no"] not in matched_ledger_ids]
    bank_unmatched_signed = sum((_signed(record) for record in unmatched_bank), ZERO)
    ledger_unmatched_signed = sum((_signed(record) for record in unmatched_ledger), ZERO)
    match_gap = matched_bank_signed - matched_ledger_signed

    bank_quarantine = sum(1 for record in records
                          if record["status"] == "quarantine" and record["side"] == "bank")
    ledger_quarantine = sum(1 for record in records
                            if record["status"] == "quarantine" and record["side"] == "ledger")

    identities = [
        {
            "key": "bank_amount",
            "label": "银行合计",
            "unit": "元",
            "left": bank_total,
            "right": matched_bank_signed + bank_unmatched_signed - bank_fee,
            "balanced": bank_total == matched_bank_signed + bank_unmatched_signed - bank_fee,
        },
        {
            "key": "ledger_amount",
            "label": "账簿合计",
            "unit": "元",
            "left": ledger_total,
            "right": matched_ledger_signed + ledger_unmatched_signed,
            "balanced": ledger_total == matched_ledger_signed + ledger_unmatched_signed,
        },
        {
            "key": "bank_count",
            "label": "银行笔数",
            "unit": "笔",
            "left": len(bank),
            "right": len(matched_bank_ids) + len(unmatched_bank),
            "balanced": len(bank) == len(matched_bank_ids) + len(unmatched_bank),
        },
        {
            "key": "ledger_count",
            "label": "账簿笔数",
            "unit": "笔",
            "left": len(ledger),
            "right": len(matched_ledger_ids) + len(unmatched_ledger),
            "balanced": len(ledger) == len(matched_ledger_ids) + len(unmatched_ledger),
        },
        {
            "key": "fee_alloc",
            "label": "手续费分摊",
            "unit": "元",
            "left": fee_alloc_total,
            "right": fee_actual_total,
            "balanced": fee_alloc_total == fee_actual_total,
        },
        {
            "key": "match_gap",
            "label": "匹配差额",
            "unit": "元",
            "left": match_gap,
            "right": ZERO,
            "balanced": abs(match_gap) <= settings.tolerance,
        },
    ]

    differences: list[dict] = []
    for record in sorted(unmatched_bank, key=lambda item: item["txn_no"]):
        differences.append({
            "kind": "未匹配",
            "side": "银行",
            "ref": record["txn_no"],
            "amount": _signed(record),
            "reason": "BANK_UNMATCHED",
            "note": record.get("memo", ""),
        })
    for record in sorted(unmatched_ledger, key=lambda item: item["txn_no"]):
        differences.append({
            "kind": "未匹配",
            "side": "账簿",
            "ref": record["txn_no"],
            "amount": _signed(record),
            "reason": "LEDGER_UNMATCHED",
            "note": record.get("memo", ""),
        })
    differences.append({
        "kind": "手续费",
        "side": "银行",
        "ref": "FEE",
        "amount": -bank_fee,
        "reason": "FEE_TOTAL",
        "note": "计入银行侧",
    })
    if match_gap != 0:
        differences.append({
            "kind": "容差",
            "side": "双方",
            "ref": "GAP",
            "amount": match_gap,
            "reason": "TOLERANCE_GAP",
            "note": f"容差 {settings.tolerance}",
        })

    totals = {
        "bank_gross": bank_gross,
        "bank_fee": bank_fee,
        "bank_total": bank_total,
        "bank_matched": matched_bank_signed,
        "bank_unmatched": bank_unmatched_signed,
        "ledger_total": ledger_total,
        "ledger_matched": matched_ledger_signed,
        "ledger_unmatched": ledger_unmatched_signed,
        "match_gap": match_gap,
        "fee_alloc_total": fee_alloc_total,
        "fee_actual_total": fee_actual_total,
    }
    counts = {
        "bank_valid": len(bank),
        "bank_matched_rows": len(matched_bank_ids),
        "bank_unmatched_rows": len(unmatched_bank),
        "ledger_valid": len(ledger),
        "ledger_matched_rows": len(matched_ledger_ids),
        "ledger_unmatched_rows": len(unmatched_ledger),
        "matched_groups": len(matches),
        "matched_tier": tier_counts,
        "bank_quarantine": bank_quarantine,
        "ledger_quarantine": ledger_quarantine,
    }
    return {
        "totals": totals,
        "counts": counts,
        "identities": identities,
        "differences": differences,
        "tier_names": TIER_NAMES,
    }


def reason_label(code: str) -> str:
    return reasons.label(code)
