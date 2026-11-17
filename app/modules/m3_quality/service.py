"""质量服务：隔离区查询、原因分布与 CSV 导出。"""
from __future__ import annotations

from ...store import Store
from . import quarantine


def payload(store: Store, run: dict | None) -> dict:
    if not run:
        return {"run_id": None, "count": 0, "distribution": [], "rows": []}
    records = store.quarantine(run["run_id"])
    return {
        "run_id": run["run_id"],
        "count": len(records),
        "distribution": quarantine.distribution(store.records(run["run_id"])),
        "rows": records,
    }


def csv_text(store: Store, run: dict | None) -> str:
    if not run:
        return quarantine.csv_text([])
    return quarantine.csv_text(store.records(run["run_id"]))
