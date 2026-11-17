"""端到端：样例 → 采信 → 质量 → 候选 → 匹配 → 差异 → 导出。"""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


PAGES = ("/", "/quarantine", "/candidates", "/matches", "/batches", "/export")


def test_full_pipeline_from_samples(client):
    response = client.post("/api/demo/run")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "matched"
    assert body["counts"]["matched_groups"] == 11
    identities = client.get("/api/differences").json()["identities"]
    assert all(item["balanced"] for item in identities)
    assert "合计" in client.get("/api/export/report.csv").text
    assert client.get("/api/matches").json()["count"] == 11


def test_all_six_pages_return_200(client, demo):
    for path in PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "ledgerbank" in response.text


def test_second_demo_run_same_run_id(client, demo):
    again = client.post("/api/demo/run").json()
    assert again["run_id"] == demo["run_id"]
    assert again["counts"] == demo["counts"]
    assert again["totals"] == demo["totals"]
    rows = client.get("/api/statements", params={"side": "bank"}).json()
    assert rows["count"] == 22


def test_bad_import_then_recover(client):
    bad = client.post("/api/statements/import",
                      data={"side": "bank", "sample": "missing.csv"})
    assert bad.status_code == 404
    good = client.post("/api/demo/run")
    assert good.status_code == 200
    assert good.json()["status"] == "matched"


def test_expected_totals_fixture(client, demo):
    expected = json.loads((FIXTURES / "expected_totals.json").read_text(encoding="utf-8"))
    assert demo["totals"] == expected["totals"]
    assert demo["counts"] == expected["counts"]


def test_expected_match_groups_fixture(client, demo):
    expected = json.loads((FIXTURES / "expected_matches.json").read_text(encoding="utf-8"))
    groups = client.get("/api/matches").json()["groups"]
    observed = [
        (group["match_id"], group["tier"], group["bank_ids"], group["ledger_ids"], group["diff"])
        for group in groups
    ]
    wanted = [
        (group["match_id"], group["tier"], group["bank_ids"], group["ledger_ids"], group["diff"])
        for group in expected["groups"]
    ]
    assert observed == wanted
