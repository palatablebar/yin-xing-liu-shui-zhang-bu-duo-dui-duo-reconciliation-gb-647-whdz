"""逐行质量规则：列、必填、金额、手续费、方向、日期、账户，以及重复流水号冲突。

一行可能同时命中多条，主原因码由 app/reasons.py 的优先级决定，结果不随检查顺序变化。
"""
from __future__ import annotations

from decimal import Decimal

from ... import reasons
from ..m1_ingest.decode import normalize_cell
from ..m2_contract.coerce import parse_amount, parse_date, parse_direction, parse_fee


def evaluate_row(side: str, row: dict, settings) -> dict:
    cells = row["cells"]
    codes: list[str] = []
    if row.get("truncated"):
        codes.append("TRUNCATED_TAIL")
    elif not row.get("column_ok"):
        codes.append("COLUMN_COUNT")

    txn_no = normalize_cell(cells.get("txn_no", ""))
    account = normalize_cell(cells.get("account", ""))
    if not txn_no or not account:
        codes.append("MISSING_FIELD")

    amount: Decimal | None = None
    try:
        amount = parse_amount(cells.get("amount", ""), settings.sentinels)
    except ValueError:
        codes.append("AMOUNT_PARSE")
    if amount is None and "AMOUNT_PARSE" not in codes:
        codes.append("AMOUNT_SENTINEL")

    fee = Decimal("0.00")
    try:
        fee = parse_fee(cells.get("fee", ""), settings.sentinels)
    except ValueError:
        codes.append("FEE_PARSE")

    direction = parse_direction(cells.get("direction", ""))
    if direction is None:
        codes.append("SIGN_UNKNOWN")

    posted_at = None
    try:
        posted_at = parse_date(cells.get("posted_at", ""), settings.tz_name)
    except ValueError:
        codes.append("DATE_PARSE")

    if account and account not in settings.accounts:
        codes.append("ACCOUNT_UNKNOWN")

    primary = reasons.primary(codes)
    record = {
        "side": side,
        "row_no": row["row_no"],
        "txn_no": txn_no,
        "account": account,
        "posted_at": posted_at.isoformat() if posted_at else "",
        "direction": direction or 0,
        "amount": amount if amount is not None else Decimal("0.00"),
        "fee": fee,
        "memo": normalize_cell(cells.get("memo", "")),
        "counterparty": normalize_cell(cells.get("counterparty", "")),
        "status": "quarantine" if codes else "valid",
        "reason": primary or "",
        "flags": codes,
        "raw_amount": cells.get("amount", ""),
        "raw_date": cells.get("posted_at", ""),
        "raw": row.get("raw", []),
    }
    return record


def mark_duplicates(records: list[dict]) -> None:
    """同一侧同一业务号出现多条有效行：保留发生时间最早的一条，时间相同取行号小者。"""
    groups: dict[str, list[dict]] = {}
    for record in records:
        if record["status"] == "valid" and record["txn_no"]:
            groups.setdefault(record["txn_no"], []).append(record)
    for items in groups.values():
        if len(items) < 2:
            continue
        items.sort(key=lambda item: (item["posted_at"] or "", item["row_no"]))
        for duplicate in items[1:]:
            duplicate["status"] = "quarantine"
            duplicate["reason"] = "DUP_TXN_CONFLICT"
            duplicate["flags"].append("DUP_TXN_CONFLICT")


def build_records(side: str, rows: list[dict], settings) -> list[dict]:
    records = []
    for seq, row in enumerate(rows):
        record = evaluate_row(side, row, settings)
        record["seq"] = seq
        records.append(record)
    mark_duplicates(records)
    return records
