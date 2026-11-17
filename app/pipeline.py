"""平台编排：采信 → 质量 → 候选 → 匹配。

模块之间只通过本文件衔接，模块内部不互相 import 规则函数；同一组输入得到同一 run_id，
重跑先删后插，行数与合计不变。
"""
from __future__ import annotations

import time
from decimal import Decimal

from .errors import DomainError
from .manifest import make_run_id, sha256_hex, utc_now_iso
from .modules.m1_ingest import service as m1_service
from .modules.m2_contract import service as m2_service
from .modules.m3_quality import quarantine as quarantine_mod
from .modules.m3_quality import rules as quality_rules
from .modules.m4_candidates import candidate as candidate_mod
from .modules.m5_matching import solve as solve_mod
from .modules.m6_diff import differences as differences_mod
from .modules.m8_upgrade import service as upgrade_service

DEFAULT_BANK = "bank_statement_dirty.csv"
DEFAULT_LEDGER = "ledger_book_dirty.csv"


def _parse(settings, side: str, filename: str, raw: bytes) -> tuple[dict, list[dict]]:
    aliases = m2_service.alias_index(side)
    parsed = m1_service.read_and_map(settings, side, filename, raw, aliases)
    records = []
    if not parsed["state"]:
        records = quality_rules.build_records(side, parsed["records"], settings)
    return parsed, records


def _side_meta(parsed: dict) -> dict:
    return {
        "file": parsed["filename"],
        "sha": parsed["sha256"] if "sha256" in parsed else "",
        "bytes": parsed["bytes"],
        "raw": parsed["raw_rows"],
        "state": parsed["state"] or "OK",
        "segments": parsed["segments"],
    }


def _counts(records: list[dict]) -> dict:
    bank = [record for record in records if record["side"] == "bank"]
    ledger = [record for record in records if record["side"] == "ledger"]
    return {
        "bank_raw": len(bank),
        "ledger_raw": len(ledger),
        "bank_valid": sum(1 for record in bank if record["status"] == "valid"),
        "ledger_valid": sum(1 for record in ledger if record["status"] == "valid"),
        "bank_quar": sum(1 for record in bank if record["status"] == "quarantine"),
        "ledger_quar": sum(1 for record in ledger if record["status"] == "quarantine"),
    }


def _run(settings, bank_meta: dict, ledger_meta: dict, records: list[dict],
         status: str, duration_ms: int = 0) -> dict:
    counts = _counts(records)
    params = settings.params()
    return {
        "run_id": make_run_id(bank_meta["sha"], ledger_meta["sha"],
                              settings.rule_version, params),
        "created_at": utc_now_iso(),
        "rule_version": settings.rule_version,
        "params": params,
        "bank_sha256": bank_meta["sha"],
        "ledger_sha256": ledger_meta["sha"],
        "bank_file": bank_meta["file"],
        "ledger_file": ledger_meta["file"],
        "bank_bytes": bank_meta["bytes"],
        "ledger_bytes": ledger_meta["bytes"],
        "bank_raw": counts["bank_raw"],
        "ledger_raw": counts["ledger_raw"],
        "bank_valid": counts["bank_valid"],
        "ledger_valid": counts["ledger_valid"],
        "bank_quar": counts["bank_quar"],
        "ledger_quar": counts["ledger_quar"],
        "segments": bank_meta["segments"] + ledger_meta["segments"],
        "status": status,
        "input_states": {"bank": bank_meta["state"], "ledger": ledger_meta["state"]},
        "duration_ms": duration_ms,
    }


def _summary(settings, run: dict, records: list[dict], candidates: list[dict],
             matches: list[dict]) -> dict:
    reconciliation = differences_mod.reconcile(records, matches, settings)
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "created_at": run["created_at"],
        "counts": reconciliation["counts"],
        "totals": {key: format(value, "f") for key, value in reconciliation["totals"].items()},
        "candidates": len(candidates),
        "matches": len(matches),
        "quarantine_distribution": quarantine_mod.distribution(records),
        "input_states": run["input_states"],
        "bank_sha256": run["bank_sha256"],
        "ledger_sha256": run["ledger_sha256"],
    }


def _empty_meta() -> dict:
    return {"file": "", "sha": "", "bytes": 0, "raw": 0, "state": "", "segments": 0}


def run_demo(settings, store, bank_name: str = DEFAULT_BANK,
             ledger_name: str = DEFAULT_LEDGER) -> dict:
    settings = upgrade_service.active_settings(store, settings)
    started = time.monotonic()
    bank_file, bank_raw = m1_service.resolve_sample(settings, bank_name)
    ledger_file, ledger_raw = m1_service.resolve_sample(settings, ledger_name)
    parsed_bank, bank_records = _parse(settings, "bank", bank_file, bank_raw)
    parsed_ledger, ledger_records = _parse(settings, "ledger", ledger_file, ledger_raw)
    parsed_bank["sha256"] = sha256_hex(bank_raw)
    parsed_ledger["sha256"] = sha256_hex(ledger_raw)
    records = bank_records + ledger_records
    candidates = candidate_mod.build(records, settings)
    matches = solve_mod.solve(candidates, records, settings)
    duration = int((time.monotonic() - started) * 1000)
    run = _run(settings, _side_meta(parsed_bank), _side_meta(parsed_ledger),
               records, "matched", duration)
    store.save_run(run, records, candidates, matches)
    return _summary(settings, store.get_run(run["run_id"]), records, candidates, matches)


def import_side(settings, store, side: str, filename: str, raw: bytes) -> dict:
    settings = upgrade_service.active_settings(store, settings)
    started = time.monotonic()
    parsed, records = _parse(settings, side, filename, raw)
    parsed_bytes = len(raw)
    meta = _side_meta(parsed)
    meta["bytes"] = parsed_bytes
    meta["sha"] = sha256_hex(raw)

    previous = store.latest_run()
    other = "ledger" if side == "bank" else "bank"
    other_records: list[dict] = []
    other_meta = _empty_meta()
    if previous and previous["status"] in ("partial_bank", "partial_ledger") \
            and previous.get(f"{other}_sha256"):
        other_records = store.records(previous["run_id"], side=other)
        other_meta = {
            "file": previous.get(f"{other}_file", ""),
            "sha": previous.get(f"{other}_sha256", ""),
            "bytes": previous.get(f"{other}_bytes", 0),
            "raw": previous.get(f"{other}_raw", 0),
            "state": previous.get("input_states", {}).get(other, "OK"),
            "segments": previous.get("segments", 0),
        }

    if side == "bank":
        bank_meta, ledger_meta = meta, other_meta
    else:
        bank_meta, ledger_meta = other_meta, meta
    combined = other_records + records
    both = bool(bank_meta["sha"] and ledger_meta["sha"])
    candidates: list[dict] = []
    matches: list[dict] = []
    if both:
        candidates = candidate_mod.build(combined, settings)
        matches = solve_mod.solve(candidates, combined, settings)
    status = "matched" if both else f"partial_{side}"
    duration = int((time.monotonic() - started) * 1000)
    run = _run(settings, bank_meta, ledger_meta, combined, status, duration)
    store.save_run(run, combined, candidates, matches)
    summary = _summary(settings, store.get_run(run["run_id"]), combined, candidates, matches)
    summary.update({
        "side": side,
        "state": parsed["state"],
        "encoding": parsed["encoding"],
        "bom": parsed["bom"],
        "segments": parsed["segments"],
        "raw_rows": parsed["raw_rows"],
        "valid": sum(1 for record in records if record["status"] == "valid"),
        "quarantine": sum(1 for record in records if record["status"] == "quarantine"),
    })
    return summary
