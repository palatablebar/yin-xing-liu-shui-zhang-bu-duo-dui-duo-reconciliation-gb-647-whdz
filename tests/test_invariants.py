"""不变量：守恒、不重叠、手续费守恒、幂等、隔离不参与合计。"""
from decimal import Decimal


def test_bank_conservation(client, demo):
    identities = {item["key"]: item for item in client.get("/api/differences").json()["identities"]}
    assert identities["bank_amount"]["balanced"] is True
    assert identities["ledger_amount"]["balanced"] is True
    assert identities["bank_count"]["balanced"] is True
    assert identities["ledger_count"]["balanced"] is True


def test_disjoint_assignment(client, demo):
    groups = client.get("/api/matches").json()["groups"]
    bank = [key for group in groups for key in group["bank_ids"]]
    ledger = [key for group in groups for key in group["ledger_ids"]]
    assert len(bank) == len(set(bank))
    assert len(ledger) == len(set(ledger))


def test_fee_conservation(client, demo):
    data = client.get("/api/matches").json()
    allocated = sum((Decimal(group["fee_alloc"]) for group in data["groups"]), Decimal("0.00"))
    actual = sum((Decimal(group["fee_actual"]) for group in data["groups"]), Decimal("0.00"))
    assert allocated == actual == Decimal("22.31")
    assert allocated == Decimal(demo["totals"]["bank_fee"])


def test_rerun_row_counts_stable(client, demo):
    before = client.get("/api/statements", params={"side": "bank"}).json()["count"]
    ledger_before = client.get("/api/statements", params={"side": "ledger"}).json()["count"]
    client.post("/api/demo/run")
    after = client.get("/api/statements", params={"side": "bank"}).json()["count"]
    ledger_after = client.get("/api/statements", params={"side": "ledger"}).json()["count"]
    assert before == after == 22
    assert ledger_before == ledger_after == 19


def test_quarantine_excluded_from_totals(client, demo):
    rows = client.get("/api/statements", params={"side": "bank"}).json()["rows"]
    gross = sum((Decimal(row["amount"]) * int(row["direction"]) for row in rows), Decimal("0.00"))
    assert gross == Decimal(demo["totals"]["bank_gross"])
    assert Decimal("999.00") not in {Decimal(row["amount"]) for row in rows}
