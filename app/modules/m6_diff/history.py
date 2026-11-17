"""批次历史与运行清单。"""
from __future__ import annotations

from ...manifest import build_manifest


def batches(store, limit: int = 20) -> list[dict]:
    runs = store.list_runs(limit)
    out = []
    for run in runs:
        out.append({
            "run_id": run["run_id"],
            "created_at": run["created_at"],
            "status": run["status"],
            "rule_version": run["rule_version"],
            "review_status": run.get("review_status", ""),
            "reviewed_at": run.get("reviewed_at", ""),
            "supersedes": run.get("supersedes", ""),
            "superseded_by": run.get("superseded_by", ""),
            "bank_valid": run["bank_valid"],
            "ledger_valid": run["ledger_valid"],
            "bank_quarantine": run["bank_quar"],
            "ledger_quarantine": run["ledger_quar"],
            "manifest": build_manifest(run),
        })
    return out


def manifest(store, run: dict, totals: dict | None = None) -> dict:
    payload = build_manifest(run)
    if totals:
        payload["totals"] = {key: format(value, "f") if hasattr(value, "as_tuple") else value
                             for key, value in totals.items()}
    return payload
