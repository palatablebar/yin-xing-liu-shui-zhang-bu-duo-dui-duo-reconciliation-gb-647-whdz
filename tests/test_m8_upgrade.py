"""口径升级：复核保护、影响结果、可发布范围、幂等与中断回滚。"""
import json

import pytest

from app.store import Store


def upgrade(client, **body):
    body.setdefault("rule_version", "2026.11.2")
    body.setdefault("tolerance", "0.01")
    return client.post("/api/upgrades", json=body)


def impact(client, **body):
    body.setdefault("rule_version", "2026.11.2")
    body.setdefault("tolerance", "0.01")
    response = client.post("/api/upgrades/impact", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def review(client, run_id, reviewed_by="张会计"):
    response = client.post(f"/api/runs/{run_id}/review", json={"reviewed_by": reviewed_by})
    assert response.status_code == 200, response.text
    return response.json()


# TRAP-25：已复核批次必须保持原结论，不能被新口径覆盖
def test_reviewed_batch_is_kept_and_not_re_reviewed(client, demo):
    review(client, demo["run_id"])
    body = impact(client)
    assert body["summary"]["batches_rerun"] == 0
    assert body["summary"]["batches_kept_reviewed"] == 1
    assert body["summary"]["re_review_required"] == 0
    batch = body["batches"][0]
    assert batch["decision"] == "kept_reviewed"
    assert batch["re_review_required"] is False
    assert "否" in batch["re_review_label"]
    assert batch["new_run_id"] == demo["run_id"]
    assert batch["publishable"] is False
    assert body["retained_scope"][0]["run_id"] == demo["run_id"]


def test_reviewed_batch_cannot_be_overwritten(client, demo):
    review(client, demo["run_id"])
    response = client.post("/api/demo/run")
    assert response.status_code == 409
    assert response.json()["error"] == "E_RUN_REVIEWED"
    assert client.get("/api/matches").json()["count"] == 11


def test_reviewed_batch_page_and_export_same_version(client, demo):
    review(client, demo["run_id"])
    upgrade(client)
    page = client.get("/batches", params={"run_id": demo["run_id"]})
    assert page.status_code == 200
    assert demo["run_id"] in page.text
    assert "2026.11.1" in page.text
    manifest = json.loads(
        client.get("/api/export/manifest.json", params={"run_id": demo["run_id"]}).text
    )
    assert manifest["run_id"] == demo["run_id"]
    assert manifest["rule_version"] == "2026.11.1"
    assert manifest["review_status"] == "reviewed"
    report_line = client.get(
        "/api/export/report.csv", params={"run_id": demo["run_id"]}
    ).text.lstrip("﻿").splitlines()[1]
    assert f"版本,{demo['run_id']},2026.11.1,已复核" in report_line


# TRAP-26：待关账批次立即用新口径重算，结果与新页面/导出同版
def test_pending_batch_rerun_produces_new_version(client, demo):
    body = impact(client)
    assert body["summary"]["batches_rerun"] == 1
    assert body["summary"]["re_review_required"] == 1
    batch = body["batches"][0]
    assert batch["decision"] == "rerun"
    assert batch["new_run_id"] != demo["run_id"]
    assert batch["new_rule_version"] == "2026.11.2"
    assert batch["matches"]["counts"]["before"] > batch["matches"]["counts"]["after"]
    assert batch["differences"]["counts"]["added"] > 0

    applied = upgrade(client)
    result = applied.json()
    assert result["applied"] is True and result["created"] is True
    new_id = result["batches"][0]["new_run_id"]

    health = client.get("/api/health").json()
    assert health["run_id"] == new_id
    assert health["active_rule_version"] == "2026.11.2"
    assert client.get("/api/matches").json()["count"] == 10

    report_line = client.get("/api/export/report.csv").text.lstrip("﻿").splitlines()[1]
    assert f"版本,{new_id},2026.11.2,待关账" in report_line
    page = client.get("/batches")
    assert new_id in page.text and "2026.11.2" in page.text


def test_impact_result_contains_matches_differences_and_scope(client, demo):
    body = impact(client)
    batch = body["batches"][0]
    for key in ("matches", "differences", "rows_changed", "totals", "identities"):
        assert key in batch
    assert set(batch["matches"]["counts"]) >= {"before", "after", "added", "removed", "changed"}
    removed = batch["matches"]["removed"][0]
    assert isinstance(removed["bank_sum"], str)
    assert body["publishable_scope"][0]["run_id"] == batch["new_run_id"]
    assert body["publishable_scope"][0]["rule_version"] == "2026.11.2"
    assert all(item["balanced"] for item in batch["identities"]["items"])


def test_rule_changes_are_reported(client, demo):
    batch = impact(client)["batches"][0]
    changes = {item["key"]: item for item in batch["rule_changes"]}
    assert changes["tolerance"]["before"] == "0.02"
    assert changes["tolerance"]["after"] == "0.01"
    assert changes["tolerance"]["label"] == "金额容差"
    assert batch["source_rule_version"] == "2026.11.1"


# TRAP-27：重复执行升级不能新增批次或流水/匹配记录
def test_upgrade_is_idempotent(client, demo):
    store = client.app.state.store
    first = upgrade(client).json()
    second = upgrade(client).json()
    assert second["created"] is False
    assert second["upgrade_id"] == first["upgrade_id"]
    assert len(store.list_runs(100)) == 2
    assert client.get("/api/upgrades").json()["count"] == 1
    assert client.get("/api/statements", params={"side": "bank"}).json()["count"] == 22
    assert client.get("/api/statements", params={"side": "ledger"}).json()["count"] == 19
    assert client.get("/api/matches").json()["count"] == 10


def test_second_upgrade_on_new_caliber_is_noop(client, demo):
    upgrade(client)
    body = impact(client)
    assert body["summary"]["batches_already_current"] == 1
    assert body["summary"]["batches_rerun"] == 0
    assert body["batches"][0]["re_review_required"] is False


# TRAP-28：升级中途失败必须整体回滚，旧版完整可用
def test_interrupted_upgrade_rolls_back(client, demo):
    store = client.app.state.store
    before_runs = len(store.list_runs(100))
    before_records = len(store.records(demo["run_id"]))
    before_matches = len(store.matches(demo["run_id"]))

    original = Store._save_run
    calls = {"n": 0}

    def brittle(self, conn, run, records, candidates, matches):
        calls["n"] += 1
        original(self, conn, run, records, candidates, matches)
        raise RuntimeError("simulated crash")

    Store._save_run = brittle
    try:
        with pytest.raises(RuntimeError):
            upgrade(client)
    finally:
        Store._save_run = original

    assert len(store.list_runs(100)) == before_runs
    assert len(store.records(demo["run_id"])) == before_records
    assert len(store.matches(demo["run_id"])) == before_matches
    assert client.get("/api/upgrades").json()["count"] == 0
    assert client.get("/api/health").json()["run_id"] == demo["run_id"]

    # 恢复后重试：一次成功，再执行一次仍是同一份升级
    retried = upgrade(client).json()
    assert retried["created"] is True
    again = upgrade(client).json()
    assert again["created"] is False
    assert again["upgrade_id"] == retried["upgrade_id"]


def test_upgrade_preserves_ledger_and_bank_rows(client, demo):
    store = client.app.state.store
    before = {
        side: sorted((row["txn_no"], row["amount"]) for row in store.records(demo["run_id"], side=side))
        for side in ("bank", "ledger")
    }
    result = upgrade(client).json()
    new_id = result["batches"][0]["new_run_id"]
    after = {
        side: sorted((row["txn_no"], row["amount"]) for row in store.records(new_id, side=side))
        for side in ("bank", "ledger")
    }
    assert after == before
    # 源批次的数据也还在，不因升级被删
    assert len(store.records(demo["run_id"])) == sum(len(value) for value in before.values())


def test_upgrade_without_run_returns_404(client):
    assert client.post("/api/upgrades", json={"rule_version": "2026.11.2"}).status_code == 404


def test_upgrade_requires_target_version(client, demo):
    response = client.post("/api/upgrades", json={"tolerance": "0.01"})
    assert response.status_code == 400
    assert response.json()["error"] == "E_CALIBER_VERSION"


def test_invalid_caliber_rejected(client, demo):
    response = client.post("/api/upgrades", json={"rule_version": "2026.11.2", "subset_max": 1})
    assert response.status_code == 400
    assert response.json()["error"] == "E_CALIBER_PARAM"


def test_dry_run_does_not_write(client, demo):
    store = client.app.state.store
    body = impact(client)
    assert body["applied"] is False and body["dry_run"] is True
    assert len(store.list_runs(100)) == 1
    assert client.get("/api/upgrades").json()["count"] == 0


def test_impact_details_explain_changed_rows(client, demo):
    batch = impact(client)["batches"][0]
    assert batch["rows_changed"]["bank"]["newly_unmatched"]
    assert batch["rows_changed"]["ledger"]["newly_unmatched"]
    assert batch["matches"]["removed"][0]["match_id"].startswith("m-")
    assert batch["matches"]["changed"]
    assert {item["reason"] for item in batch["differences"]["added"]} >= {
        "BANK_UNMATCHED", "LEDGER_UNMATCHED"
    }


def test_all_reviewed_upgrade_records_decision_without_new_batch(client, demo):
    review(client, demo["run_id"])
    body = upgrade(client).json()
    assert body["applied"] is True and body["created"] is True
    assert body["summary"]["batches_rerun"] == 0
    assert body["summary"]["batches_kept_reviewed"] == 1
    assert len(client.app.state.store.list_runs(100)) == 1
    again = upgrade(client).json()
    assert again["created"] is False
    assert again["upgrade_id"] == body["upgrade_id"]
    assert client.get("/api/upgrades").json()["count"] == 1
    page = client.get("/upgrade").text
    assert body["upgrade_id"] in page
    assert "否，保持已复核结论" in page


def test_superseded_batch_cannot_be_reviewed(client, demo):
    result = upgrade(client).json()
    new_id = result["batches"][0]["new_run_id"]
    response = client.post(f"/api/runs/{demo['run_id']}/review", json={})
    assert response.status_code == 409
    assert response.json()["error"] == "E_RUN_SUPERSEDED"
    assert client.post(f"/api/runs/{new_id}/review", json={}).status_code == 200


def test_scoped_upgrade_only_touches_requested_batch(client):
    client.post("/api/statements/import",
                data={"side": "bank", "sample": "bank_statement_dirty.csv"})
    second = client.post("/api/statements/import",
                         data={"side": "ledger", "sample": "ledger_book_dirty.csv"}).json()
    store = client.app.state.store
    live_ids = [run["run_id"] for run in store.live_runs()]
    assert len(live_ids) == 2
    scoped = client.post("/api/upgrades/impact", json={
        "rule_version": "2026.11.2", "run_ids": [second["run_id"]],
    }).json()
    assert [item["source_run_id"] for item in scoped["batches"]] == [second["run_id"]]
    assert scoped["summary"]["batches_total"] == 1
