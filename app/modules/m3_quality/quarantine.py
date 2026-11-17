"""隔离区：原因码分布与可导出的证据行。"""
from __future__ import annotations

import csv
import io

from ... import reasons

CSV_HEADER = ["序号", "侧", "行号", "业务号", "账户", "金额原值", "时间原值", "原因码", "原因", "原行"]


def rows(records: list[dict]) -> list[dict]:
    return [record for record in records if record["status"] == "quarantine"]


def distribution(records: list[dict]) -> list[dict]:
    return reasons.distribution(rows(records))


def csv_text(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for index, record in enumerate(rows(records), 1):
        writer.writerow(
            [
                index,
                "银行" if record["side"] == "bank" else "账簿",
                record["row_no"],
                record["txn_no"],
                record["account"],
                record.get("raw_amount", ""),
                record.get("raw_date", ""),
                record["reason"],
                reasons.label(record["reason"]),
                " | ".join(str(cell) for cell in record.get("raw", [])),
            ]
        )
    return "\ufeff" + buffer.getvalue()
