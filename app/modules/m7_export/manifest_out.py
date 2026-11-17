"""运行清单导出：run_id、输入 sha256、规则版本、参数、计数与合计。"""
from __future__ import annotations

import json
from decimal import Decimal

from ...manifest import build_manifest


def manifest_text(run: dict, reconciliation: dict | None = None) -> str:
    payload = build_manifest(run)
    if reconciliation:
        payload["totals"] = {
            key: format(value, "f") if isinstance(value, Decimal) else value
            for key, value in reconciliation["totals"].items()
        }
        payload["counts"].update(reconciliation["counts"])
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
