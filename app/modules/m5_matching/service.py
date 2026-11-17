"""匹配服务：求解、落库、查询。"""
from __future__ import annotations

from decimal import Decimal

from ...errors import DomainError
from . import solve


def payload(store, run: dict | None) -> dict:
    if not run:
        return {"run_id": None, "count": 0, "tiers": {}, "groups": [],
                "fee_alloc_total": "0.00", "fee_actual_total": "0.00"}
    groups = store.matches(run["run_id"])
    tiers: dict[str, int] = {}
    for group in groups:
        key = str(group["tier"])
        tiers[key] = tiers.get(key, 0) + 1
    fee_alloc = sum((Decimal(group["fee_alloc"]) for group in groups), Decimal("0.00"))
    fee_actual = sum((Decimal(group["fee_actual"]) for group in groups), Decimal("0.00"))
    return {
        "run_id": run["run_id"],
        "count": len(groups),
        "tiers": tiers,
        "groups": groups,
        "fee_alloc_total": format(fee_alloc, "f"),
        "fee_actual_total": format(fee_actual, "f"),
    }


def run_matching(store, run: dict | None, settings) -> dict:
    if not run:
        raise DomainError("E_NO_RUN", "还没有批次", 404)
    candidates = store.candidates(run["run_id"])
    if not candidates:
        raise DomainError("E_NO_CANDIDATES", "还没有候选", 409)
    records = store.records(run["run_id"])
    groups = solve.solve(candidates, records, settings)
    store.replace_matches(run["run_id"], groups)
    store.set_status(run["run_id"], "matched")
    return payload(store, store.get_run(run["run_id"]))
