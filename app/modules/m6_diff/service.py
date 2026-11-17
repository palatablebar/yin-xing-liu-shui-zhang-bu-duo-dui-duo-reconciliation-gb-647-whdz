"""差异服务：对账结论、批次历史、单批详情。"""
from __future__ import annotations

from ...errors import DomainError
from . import differences, history


def payload(store, run: dict | None, settings) -> dict:
    if not run:
        return {
            "run_id": None,
            "totals": {},
            "counts": {},
            "identities": [],
            "differences": [],
            "tier_names": differences.TIER_NAMES,
        }
    records = store.records(run["run_id"])
    matches = store.matches(run["run_id"])
    effective = settings.for_run(run)
    result = differences.reconcile(records, matches, effective)
    result["run_id"] = run["run_id"]
    result["rule_version"] = run.get("rule_version", "")
    result["params"] = run.get("params", {})
    result["review_status"] = run.get("review_status", "")
    return result


def batches_payload(store) -> dict:
    return {"count": len(store.list_runs(20)), "batches": history.batches(store)}


def batch_detail(store, run_id: str, settings) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise DomainError("E_NO_RUN", "批次不存在", 404)
    result = payload(store, run, settings)
    result["manifest"] = history.manifest(store, run, result.get("totals"))
    return result
