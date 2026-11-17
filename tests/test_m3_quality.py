"""M3 质量：原因分布、重复冲突、空值、符号、日期、主原因稳定性。"""
from app import reasons
from app.modules.m3_quality import rules


def row(row_no: int, txn: str, posted: str, amount: str, account: str = "6222-0012",
        direction: str = "借"):
    return {
        "row_no": row_no,
        "cells": {
            "txn_no": txn,
            "account": account,
            "posted_at": posted,
            "direction": direction,
            "amount": amount,
            "fee": "0.00",
            "memo": "",
            "counterparty": "",
        },
        "raw": [txn],
        "column_ok": True,
        "truncated": False,
    }


def all_records(client):
    rows = []
    for side in ("bank", "ledger"):
        for status in ("valid", "quarantine"):
            body = client.get("/api/statements",
                              params={"side": side, "status": status}).json()
            rows.extend(body["rows"])
    return rows


def test_quarantine_distribution_counts(demo):
    counts = {item["code"]: item["count"] for item in demo["quarantine_distribution"]}
    assert counts == {
        "ACCOUNT_UNKNOWN": 1,
        "AMOUNT_SENTINEL": 2,
        "COLUMN_COUNT": 1,
        "DATE_PARSE": 1,
        "DUP_TXN_CONFLICT": 2,
        "SIGN_UNKNOWN": 1,
    }
    assert sum(counts.values()) == 8


def test_duplicate_txn_keeps_earliest(client, demo):
    # TRAP-14：冲突保留发生时间最早的一条
    records = all_records(client)
    valid = {item["txn_no"]: item["amount"] for item in records if item["status"] == "valid"}
    assert valid["000003"] == "1250.50"
    duplicate = next(item for item in records
                     if item["status"] == "quarantine" and item["txn_no"] == "000003")
    assert duplicate["amount"] == "999.00"


def test_duplicate_tie_breaks_by_row_number(settings):
    # TRAP-14：同一时间取行号小者
    records = rules.build_records(
        "bank",
        [row(7, "T1", "2026-03-02T09:00:00+08:00", "10.00"),
         row(9, "T1", "2026-03-02T09:00:00+08:00", "20.00")],
        settings,
    )
    kept = [item for item in records if item["status"] == "valid"]
    dropped = [item for item in records if item["status"] == "quarantine"]
    assert len(kept) == 1
    assert kept[0]["row_no"] == 7 and kept[0]["amount"] == 10
    assert dropped[0]["row_no"] == 9
    assert dropped[0]["reason"] == "DUP_TXN_CONFLICT"


def test_unknown_account_quarantined(client, demo):
    item = next(row for row in all_records(client) if row["txn_no"] == "000013")
    assert item["status"] == "quarantine"
    assert item["reason"] == "ACCOUNT_UNKNOWN"


def test_unknown_sign_quarantined(client, demo):
    item = next(row for row in all_records(client) if row["txn_no"] == "000011")
    assert item["reason"] == "SIGN_UNKNOWN"


def test_date_parse_quarantined(client, demo):
    item = next(row for row in all_records(client) if row["txn_no"] == "000012")
    assert item["reason"] == "DATE_PARSE"


def test_amount_sentinel_not_zero(client, demo):
    # TRAP-07：空值不进合计
    item = next(row for row in all_records(client) if row["txn_no"] == "000010")
    assert item["reason"] == "AMOUNT_SENTINEL"
    assert demo["counts"]["bank_valid"] == 22
    assert demo["totals"]["bank_gross"] == "-246279.51"


def test_quarantine_csv_has_raw_value(client):
    client.post("/api/statements/import",
                data={"side": "bank", "sample": "bank_statement_dirty.csv"})
    text = client.get("/api/quarantine.csv").text
    assert "原因码" in text
    assert "N/A" in text
    assert "DUP_TXN_CONFLICT" in text
    assert "999.00" in text


def test_primary_reason_stable_on_multi_issue(settings):
    # TRAP-19：多规则同时命中时主原因码固定
    multi = row(1, "", "bad-date", "N/A", account="0000-0000", direction="X")
    record = rules.evaluate_row("bank", multi, settings)
    assert set(record["flags"]) >= {
        "MISSING_FIELD", "AMOUNT_SENTINEL", "SIGN_UNKNOWN", "DATE_PARSE", "ACCOUNT_UNKNOWN"
    }
    assert record["reason"] == "MISSING_FIELD"
    assert reasons.primary(record["flags"]) == "MISSING_FIELD"
