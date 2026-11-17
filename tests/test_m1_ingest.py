"""M1 采信：编码、BOM、分段、列数、末行截断、空态与幂等。"""
from pathlib import Path

from app.modules.m1_ingest.decode import decode_bytes

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def import_sample(client, side: str, name: str):
    response = client.post("/api/statements/import", data={"side": side, "sample": name})
    return response


def import_file(client, side: str, name: str, path: Path):
    with path.open("rb") as handle:
        response = client.post(
            "/api/statements/import",
            data={"side": side},
            files={"file": (name, handle, "text/csv")},
        )
    return response


def test_bank_import_counts_and_segments(client):
    body = import_sample(client, "bank", "bank_statement_dirty.csv").json()
    assert body["valid"] == 22
    assert body["quarantine"] == 6
    assert body["raw_rows"] == 28
    assert body["segments"] == 2
    assert body["encoding"] == "utf-8-sig"


def test_gb18030_ledger_decodes_chinese_headers(client):
    body = import_sample(client, "ledger", "ledger_book_dirty.csv").json()
    assert body["encoding"] == "gb18030"
    assert body["valid"] == 19
    assert body["quarantine"] == 2


def test_bom_stripped_from_first_header():
    raw = (SAMPLE / "bank_statement_dirty.csv").read_bytes()
    decoded = decode_bytes(raw, ("utf-8-sig", "utf-8", "gb18030"))
    assert decoded["bom"] is True
    assert decoded["text"].startswith("流水号")
    assert "\ufeff" not in decoded["text"]


def test_duplicate_header_not_counted_as_row(client):
    import_sample(client, "bank", "bank_statement_dirty.csv")
    valid = client.get("/api/statements", params={"side": "bank", "status": "valid"}).json()
    quarantine = client.get("/api/statements",
                            params={"side": "bank", "status": "quarantine"}).json()
    assert len(valid["rows"]) == 22
    assert len(quarantine["rows"]) == 6
    assert all(row["txn_no"] != "流水号" for row in valid["rows"] + quarantine["rows"])


def test_column_count_quarantined(client):
    import_sample(client, "bank", "bank_statement_dirty.csv")
    data = client.get("/api/quarantine").json()
    row = next(item for item in data["rows"] if item["txn_no"] == "000009")
    assert row["reason"] == "COLUMN_COUNT"


# TRAP-16：末行截断
def test_truncated_tail_rejected(client):
    body = import_sample(client, "bank", "bank_truncated_tail.csv").json()
    assert body["valid"] == 2
    assert body["quarantine"] == 1
    data = client.get("/api/quarantine").json()
    assert data["rows"][0]["reason"] == "TRUNCATED_TAIL"


# TRAP-18：三种空态
def test_empty_states_are_three_outcomes(client):
    empty = import_sample(client, "bank", "empty_bank.csv").json()
    header_only = import_sample(client, "ledger", "header_only_ledger.csv").json()
    blank = import_sample(client, "bank", "all_blank_bank.csv").json()
    assert empty["state"] == "EMPTY_FILE"
    assert header_only["state"] == "HEADER_ONLY"
    assert blank["state"] == "ALL_BLANK"
    assert empty["valid"] == header_only["valid"] == blank["valid"] == 0


def test_quoted_newline_is_one_record(client):
    response = import_file(client, "bank", "quoted.csv",
                           FIXTURES / "quoted_newline_bank.csv")
    body = response.json()
    assert body["state"] is None
    assert body["valid"] == 2
    assert body["quarantine"] == 0


def test_legacy_column_aliases_map(client):
    response = import_file(client, "bank", "legacy.csv",
                           FIXTURES / "legacy_columns_bank.csv")
    body = response.json()
    assert body["valid"] == 2
    assert body["quarantine"] == 0
    rows = client.get("/api/statements", params={"side": "bank"}).json()["rows"]
    assert {row["txn_no"] for row in rows} == {"L001", "L002"}


def test_unknown_sample_returns_404(client):
    assert import_sample(client, "bank", "missing.csv").status_code == 404


def test_unknown_side_returns_400(client):
    response = client.post("/api/statements/import",
                           data={"side": "both", "sample": "bank_statement_dirty.csv"})
    assert response.status_code == 400


def test_reimport_keeps_run_id_and_counts(client):
    first = import_sample(client, "bank", "bank_statement_dirty.csv").json()
    second = import_sample(client, "bank", "bank_statement_dirty.csv").json()
    assert first["run_id"] == second["run_id"]
    assert first["valid"] == second["valid"] == 22
    assert first["counts"] == second["counts"]
