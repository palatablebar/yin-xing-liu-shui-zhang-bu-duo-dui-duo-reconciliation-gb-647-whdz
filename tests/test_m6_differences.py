"""M6 差异：两侧守恒、笔数账、差异归因、批次清单与重跑。"""
from decimal import Decimal


def identities(client):
    return {item["key"]: item for item in client.get("/api/differences").json()["identities"]}


def test_bank_identity_holds(client, demo):
    data = client.get("/api/differences").json()
    item = next(row for row in data["identities"] if row["key"] == "bank_amount")
    assert item["balanced"] is True
    assert Decimal(str(item["left"])) == Decimal(demo["totals"]["bank_total"])


def test_ledger_identity_holds(client, demo):
    data = client.get("/api/differences").json()
    item = next(row for row in data["identities"] if row["key"] == "ledger_amount")
    assert item["balanced"] is True
    assert Decimal(str(item["left"])) == Decimal(demo["totals"]["ledger_total"])


def test_match_gap_explained_by_tolerance(client, demo):
    item = identities(client)["match_gap"]
    assert item["balanced"] is True
    assert Decimal(str(item["left"])) == Decimal("0.01")
    kinds = [row["reason"] for row in client.get("/api/differences").json()["differences"]]
    assert "TOLERANCE_GAP" in kinds


def test_bank_count_identity(client, demo):
    item = identities(client)["bank_count"]
    assert item["left"] == 22
    assert item["right"] == 15 + 7
    assert item["balanced"] is True


def test_ledger_count_identity(client, demo):
    item = identities(client)["ledger_count"]
    assert item["left"] == 19
    assert item["right"] == 14 + 5
    assert item["balanced"] is True


def test_unmatched_rows_have_reason(client, demo):
    differences = client.get("/api/differences").json()["differences"]
    bank = [row for row in differences if row["reason"] == "BANK_UNMATCHED"]
    ledger = [row for row in differences if row["reason"] == "LEDGER_UNMATCHED"]
    assert len(bank) == 7
    assert len(ledger) == 5
    assert Decimal(bank[0]["amount"]) > 0 or Decimal(bank[0]["amount"]) < 0


def test_batches_manifest_has_run_id_and_sha(client, demo):
    data = client.get("/api/batches").json()
    assert data["count"] >= 1
    batch = data["batches"][0]
    assert batch["run_id"] == demo["run_id"]
    assert len(batch["manifest"]["inputs"]["bank"]["sha256"]) == 64
    assert len(batch["manifest"]["inputs"]["ledger"]["sha256"]) == 64
    assert batch["manifest"]["rule_version"] == "2026.11.1"


def test_rerun_same_inputs_keeps_totals(client, demo):
    first = client.get("/api/differences").json()
    client.post("/api/demo/run")
    second = client.get("/api/differences").json()
    assert first["totals"] == second["totals"]
    assert first["counts"] == second["counts"]


def test_decimal_total_exact_not_float(client, demo):
    # TRAP-10：十进制合计与浮点累计不同
    rows = client.get("/api/statements", params={"side": "bank"}).json()["rows"]
    amounts = [Decimal(row["amount"]) * int(row["direction"]) for row in rows]
    exact = sum(amounts, Decimal("0.00"))
    assert exact == Decimal("-246279.51")
    assert exact == Decimal(demo["totals"]["bank_gross"])
    assert 0.1 + 0.2 + 0.3 != 0.6
    assert sum((Decimal("0.1"), Decimal("0.2"), Decimal("0.3")), Decimal("0")) == Decimal("0.6")
