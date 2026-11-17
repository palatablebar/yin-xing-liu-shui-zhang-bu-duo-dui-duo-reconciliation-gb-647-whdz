"""候选服务：生成、落库、查询。"""
from __future__ import annotations

from ...errors import DomainError
from ..m8_upgrade import service as upgrade_service
from . import candidate


def build(records: list[dict], settings) -> list[dict]:
    return candidate.build(records, settings)


def payload(store, run: dict | None) -> dict:
    if not run:
        return {"run_id": None, "count": 0, "tiers": {}, "candidates": []}
    items = store.candidates(run["run_id"])
    tiers: dict[str, int] = {}
    for item in items:
        key = str(item["tier"])
        tiers[key] = tiers.get(key, 0) + 1
    return {"run_id": run["run_id"], "count": len(items), "tiers": tiers, "candidates": items}


def refresh(store, run: dict | None, settings) -> dict:
    if not run:
        raise DomainError("E_NO_RUN", "还没有批次", 404)
    records = store.records(run["run_id"])
    items = candidate.build(records, upgrade_service.active_settings(store, settings))
    store.replace_candidates(run["run_id"], items)
    store.set_status(run["run_id"], "ready")
    return payload(store, store.get_run(run["run_id"]))
