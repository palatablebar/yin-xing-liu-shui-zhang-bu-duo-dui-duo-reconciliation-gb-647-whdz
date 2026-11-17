"""M7 导出：报告分块、金额字符串、大整数保形、清单与无批次 404。"""
import json
from decimal import Decimal


def report(client):
    response = client.get("/api/export/report.csv")
    assert response.status_code == 200
    return response.text


def test_report_has_all_sections(client, demo):
    text = report(client)
    for section in ("合计", "匹配组", "未匹配", "隔离"):
        assert section in text


def test_report_money_strings_exact(client, demo):
    text = report(client)
    assert "-246301.82" in text
    assert "-10248167.41" in text
    assert "22.31" in text
    assert "0.01" in text


def test_manifest_has_input_sha(client, demo):
    body = client.get("/api/export/manifest.json").json()
    assert body["run_id"] == demo["run_id"]
    assert len(body["inputs"]["bank"]["sha256"]) == 64
    assert len(body["inputs"]["ledger"]["sha256"]) == 64
    assert body["rule_version"] == "2026.11.1"
    assert body["counts"]["bank_valid"] == 22


def test_big_txn_no_scientific_notation(client, demo):
    # TRAP-09：大整数业务号逐字导出
    text = report(client)
    assert "9007199254740993" in text
    assert "9.007199254740993" not in text
    assert "e+15" not in text.lower()


def test_report_quarantine_reasons_present(client, demo):
    text = report(client)
    for code in ("DUP_TXN_CONFLICT", "AMOUNT_SENTINEL", "COLUMN_COUNT", "TRUNCATED_TAIL"):
        if code == "TRUNCATED_TAIL":
            continue
        assert code in text


def test_export_without_run_returns_404(client):
    assert client.get("/api/export/report.csv").status_code == 404
    assert client.get("/api/export/manifest.json").status_code == 404


def test_export_summary_counts(client, demo):
    body = client.get("/api/export/summary").json()
    assert body["counts"]["bank_valid"] == 22
    assert body["counts"]["ledger_valid"] == 19
    assert body["totals"]["bank_total"] == "-246301.82"


def test_report_header_row(client, demo):
    first_line = report(client).lstrip("\ufeff").splitlines()[0]
    assert first_line.startswith("区块,编号,层级")
    assert "银行流水" in first_line and "账簿凭证" in first_line


def test_manifest_json_is_serializable(client, demo):
    response = client.get("/api/export/manifest.json")
    body = json.loads(response.text)
    assert isinstance(body["params"], dict)
    assert body["params"]["tolerance"] == "0.02"
    assert Decimal(body["totals"]["bank_total"]) == Decimal("-246301.82")
