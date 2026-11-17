"""运行清单：run_id、输入摘要、规则版本、参数与计数。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_run_id(bank_sha: str, ledger_sha: str, rule_version: str, params: dict) -> str:
    """同一组输入 + 同一组参数得到同一个 run_id，重跑命中同一批次。"""
    payload = "|".join(
        [
            rule_version,
            bank_sha or "-",
            ledger_sha or "-",
            ",".join(f"{k}={params[k]}" for k in sorted(params)),
        ]
    )
    return "run-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_safe(value):
    """Decimal / datetime 转字符串，大整数保持字符串。"""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def build_manifest(run: dict) -> dict:
    return {
        "run_id": run["run_id"],
        "created_at": run["created_at"],
        "rule_version": run["rule_version"],
        "params": run.get("params", {}),
        "inputs": {
            "bank": {
                "file": run.get("bank_file") or "",
                "sha256": run.get("bank_sha256") or "",
                "bytes": run.get("bank_bytes", 0),
            },
            "ledger": {
                "file": run.get("ledger_file") or "",
                "sha256": run.get("ledger_sha256") or "",
                "bytes": run.get("ledger_bytes", 0),
            },
        },
        "counts": {
            "bank_raw": run.get("bank_raw", 0),
            "ledger_raw": run.get("ledger_raw", 0),
            "bank_valid": run.get("bank_valid", 0),
            "ledger_valid": run.get("ledger_valid", 0),
            "bank_quarantine": run.get("bank_quar", 0),
            "ledger_quarantine": run.get("ledger_quar", 0),
            "segments": run.get("segments", 0),
        },
        "input_states": run.get("input_states", {}),
        "duration_ms": run.get("duration_ms", 0),
        "status": run.get("status", ""),
    }
