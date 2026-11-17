"""口径升级影响计算：受影响匹配、差异变化与可发布范围都在同一份结果里。

三条硬约束：
- 已复核批次不重算、不改写、不重新复核；结果里逐批写明「是否重新复核」；
- 新批次、候选、匹配、升级清单在同一个事务里写入，中断即整体回滚，旧版完整可用；
- 升级编号由「输入身份 + 目标口径」决定，重复执行不新增记录。
"""
from __future__ import annotations

import hashlib
from decimal import Decimal

from ...config import CALIBER_LABELS
from ...errors import DomainError
from ...manifest import make_run_id, utc_now_iso
from ..m4_candidates import candidate as candidate_mod
from ..m5_matching import solve as solve_mod
from ..m6_diff import differences as differences_mod

REVIEW_PENDING = "pending_close"
REVIEW_DONE = "reviewed"

DECISION_KEPT_REVIEWED = "kept_reviewed"
DECISION_RERUN = "rerun"
DECISION_CURRENT = "already_current"

RE_REVIEW_LABELS = {
    DECISION_KEPT_REVIEWED: "否，保持已复核结论",
    DECISION_RERUN: "是，新口径结果待复核",
    DECISION_CURRENT: "否，已在新口径上",
}

CALIBER_FIELDS = ("tolerance", "window_days", "subset_max", "fee_quantum")
MONEY_FIELDS = (
    "bank_gross", "bank_fee", "bank_total", "bank_matched", "bank_unmatched",
    "ledger_total", "ledger_matched", "ledger_unmatched", "match_gap",
    "fee_alloc_total", "fee_actual_total",
)


def _money(value) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _totals(reconciliation: dict) -> dict:
    return {key: _money(reconciliation["totals"][key]) for key in MONEY_FIELDS}


def _source_settings(base_settings, run: dict):
    """按源批次自己的规则版本与参数复算，保证「升级前」结论可还原。"""
    params = run.get("params") or {}
    return base_settings.with_caliber(
        run.get("rule_version") or base_settings.rule_version,
        tolerance=params.get("tolerance", base_settings.tolerance),
        window_days=params.get("window_days", base_settings.window_days),
        subset_max=params.get("subset_max", base_settings.subset_max),
        fee_quantum=params.get("fee_quantum", base_settings.fee_quantum),
    )


def _param_diff(before: dict, after: dict) -> list[dict]:
    changes = []
    for key in CALIBER_FIELDS:
        left = str(before.get(key, ""))
        right = str(after.get(key, ""))
        if left != right:
            changes.append({
                "key": key,
                "label": CALIBER_LABELS.get(key, key),
                "before": left,
                "after": right,
            })
    return changes


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


def _match_index(matches: list[dict]) -> dict[str, dict]:
    return {group["match_id"]: group for group in matches}


def _match_view(group: dict) -> dict:
    """匹配组的对外形态：金额一律十进制字符串，便于落库与逐字比对。"""
    return {
        "match_id": group["match_id"],
        "tier": int(group["tier"]),
        "bank_ids": list(group["bank_ids"]),
        "ledger_ids": list(group["ledger_ids"]),
        "bank_sum": _money(group["bank_sum"]),
        "ledger_sum": _money(group["ledger_sum"]),
        "diff": _money(group["diff"]),
        "day_gap": int(group["day_gap"]),
        "fee_alloc": _money(group.get("fee_alloc", "0")),
        "fee_actual": _money(group.get("fee_actual", "0")),
        "bank_signed": _money(group.get("bank_signed", "0")),
        "ledger_signed": _money(group.get("ledger_signed", "0")),
    }


def _match_changes(before: list[dict], after: list[dict]) -> dict:
    old = _match_index(before)
    new = _match_index(after)
    added = [_match_view(new[key]) for key in sorted(set(new) - set(old))]
    removed = [_match_view(old[key]) for key in sorted(set(old) - set(new))]
    changed = []
    for key in sorted(set(old) & set(new)):
        left, right = old[key], new[key]
        fields = {
            "tier": (left["tier"], right["tier"]),
            "diff": (str(left["diff"]), str(right["diff"])),
            "fee_alloc": (str(left["fee_alloc"]), str(right["fee_alloc"])),
            "bank_sum": (str(left["bank_sum"]), str(right["bank_sum"])),
            "ledger_sum": (str(left["ledger_sum"]), str(right["ledger_sum"])),
        }
        deltas = {
            name: {"before": pair[0], "after": pair[1]}
            for name, pair in fields.items() if pair[0] != pair[1]
        }
        if deltas:
            changed.append({"match_id": key, "changes": deltas})
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {
            "before": len(before),
            "after": len(after),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def _difference_key(item: dict) -> tuple:
    return (item.get("kind", ""), item.get("side", ""), item.get("ref", ""),
            item.get("reason", ""))


def _difference_view(item: dict) -> dict:
    view = dict(item)
    view["amount"] = _money(item.get("amount", "0"))
    return view


def _difference_changes(before: dict, after: dict) -> dict:
    old = {_difference_key(item): item for item in before["differences"]}
    new = {_difference_key(item): item for item in after["differences"]}
    added = [_difference_view(new[key]) for key in sorted(set(new) - set(old))]
    removed = [_difference_view(old[key]) for key in sorted(set(old) - set(new))]
    return {
        "added": added,
        "removed": removed,
        "counts": {
            "before": len(before["differences"]),
            "after": len(after["differences"]),
            "added": len(added),
            "removed": len(removed),
        },
    }


def _matched_ids(matches: list[dict], side: str) -> set[str]:
    return {key for group in matches for key in group[f"{side}_ids"]}


def _row_changes(before: list[dict], after: list[dict]) -> dict:
    out = {}
    for side in ("bank", "ledger"):
        old = _matched_ids(before, side)
        new = _matched_ids(after, side)
        out[side] = {
            "newly_matched": sorted(new - old),
            "newly_unmatched": sorted(old - new),
            "still_matched": sorted(old & new),
        }
    return out


def _identities(reconciliation: dict) -> dict:
    return {
        "balanced": all(item["balanced"] for item in reconciliation["identities"]),
        "items": [
            {
                "key": item["key"],
                "label": item["label"],
                "balanced": item["balanced"],
                "left": _money(item["left"]),
                "right": _money(item["right"]),
                "unit": item["unit"],
            }
            for item in reconciliation["identities"]
        ],
    }


def _publish_decision(status: str, identities: dict) -> tuple[bool, str]:
    if status != "matched":
        return False, "批次未完成两侧匹配"
    if not identities["balanced"]:
        return False, "存在不平账项"
    return True, "两侧守恒，可发布"


def _source_identity(run: dict) -> str:
    """输入身份：同一对流水/凭证无论重跑多少次都相同。"""
    has_both = bool(run.get("bank_sha256") and run.get("ledger_sha256"))
    return "|".join([
        run.get("bank_sha256", ""),
        run.get("ledger_sha256", ""),
        "both" if has_both else "partial",
    ])


def target_caliber(base_settings, body: dict):
    """把请求体归一成目标口径；缺省项沿用当前配置。"""
    rule_version = str(body.get("rule_version") or "").strip()
    if not rule_version:
        raise DomainError("E_CALIBER_VERSION", "升级必须给出目标规则版本", 400)
    try:
        target = base_settings.with_caliber(
            rule_version,
            tolerance=body.get("tolerance"),
            window_days=body.get("window_days"),
            subset_max=body.get("subset_max"),
            fee_quantum=body.get("fee_quantum"),
        )
    except (ValueError, ArithmeticError) as exc:
        raise DomainError("E_CALIBER_PARAM", f"口径参数不合法：{exc}", 400) from exc
    if target.tolerance < 0:
        raise DomainError("E_CALIBER_PARAM", "容差不能为负", 400)
    if target.window_days < 0:
        raise DomainError("E_CALIBER_PARAM", "日期窗口不能为负", 400)
    if target.subset_max < 2:
        raise DomainError("E_CALIBER_PARAM", "子集上限至少为 2", 400)
    if target.fee_quantum <= 0:
        raise DomainError("E_CALIBER_PARAM", "手续费精度必须为正", 400)
    return target


def upgrade_id_for(target_settings, sources: list[dict]) -> str:
    """升级身份只看目标口径与输入身份集合，重跑同一升级得到同一编号。"""
    params = target_settings.params()
    payload = "|".join([
        target_settings.rule_version,
        ",".join(f"{key}={params[key]}" for key in sorted(params)),
        ",".join(sorted({_source_identity(run) for run in sources})),
    ])
    return "up-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _new_run(source: dict, records: list[dict], target_settings, status: str) -> dict:
    counts = _counts(records)
    return {
        "run_id": make_run_id(
            source.get("bank_sha256", ""), source.get("ledger_sha256", ""),
            target_settings.rule_version, target_settings.params(),
        ),
        "created_at": utc_now_iso(),
        "rule_version": target_settings.rule_version,
        "params": target_settings.params(),
        "bank_sha256": source.get("bank_sha256", ""),
        "ledger_sha256": source.get("ledger_sha256", ""),
        "bank_file": source.get("bank_file", ""),
        "ledger_file": source.get("ledger_file", ""),
        "bank_bytes": source.get("bank_bytes", 0),
        "ledger_bytes": source.get("ledger_bytes", 0),
        "bank_raw": counts["bank_raw"],
        "ledger_raw": counts["ledger_raw"],
        "bank_valid": counts["bank_valid"],
        "ledger_valid": counts["ledger_valid"],
        "bank_quar": counts["bank_quar"],
        "ledger_quar": counts["ledger_quar"],
        "segments": source.get("segments", 0),
        "status": status,
        "input_states": source.get("input_states", {}),
        "duration_ms": 0,
        "review_status": REVIEW_PENDING,
        "supersedes": source["run_id"],
    }


def _same_caliber(run: dict, target_settings) -> bool:
    if run.get("rule_version") != target_settings.rule_version:
        return False
    params = run.get("params") or {}
    target = target_settings.params()
    return all(
        str(params.get(key, "")) == str(target[key]) for key in CALIBER_FIELDS
    )


def plan(store, base_settings, body: dict) -> dict:
    """计算升级影响，不写库。返回影响结果与待写入的批次包。"""
    target_settings = target_caliber(base_settings, body)
    target_params = target_settings.params()

    live = store.live_runs()
    if not live:
        raise DomainError("E_NO_RUN", "还没有批次", 404)

    requested = body.get("run_ids") or []
    if requested:
        wanted = set(requested)
        live = [run for run in live if run["run_id"] in wanted]
        missing = wanted - {run["run_id"] for run in live}
        if missing:
            raise DomainError("E_NO_RUN", f"批次不存在或已被替代：{sorted(missing)}", 404)

    batches: list[dict] = []
    bundles: list[dict] = []
    publishable_scope: list[dict] = []
    held_scope: list[dict] = []
    retained_scope: list[dict] = []
    match_delta = {"added": 0, "removed": 0, "changed": 0}
    diff_delta = {"added": 0, "removed": 0}

    for source in live:
        run_id = source["run_id"]
        records = store.records(run_id)
        old_matches = store.matches(run_id)
        old_settings = _source_settings(base_settings, source)
        old_recon = differences_mod.reconcile(records, old_matches, old_settings)
        old_identities = _identities(old_recon)
        old_totals = _totals(old_recon)
        bank_before = len([row for row in records if row["side"] == "bank"])
        ledger_before = len([row for row in records if row["side"] == "ledger"])

        if source.get("review_status") == REVIEW_DONE:
            decision = DECISION_KEPT_REVIEWED
        elif _same_caliber(source, target_settings):
            decision = DECISION_CURRENT
        else:
            decision = DECISION_RERUN

        entry = {
            "source_run_id": run_id,
            "source_rule_version": source.get("rule_version", ""),
            "source_params": source.get("params", {}),
            "review_status_before": source.get("review_status", REVIEW_PENDING),
            "status_before": source.get("status", ""),
            "decision": decision,
            "decision_label": {
                DECISION_KEPT_REVIEWED: "保持原结论",
                DECISION_RERUN: "按新口径重算",
                DECISION_CURRENT: "已在新口径",
            }[decision],
            "re_review_required": decision == DECISION_RERUN,
            "re_review_label": RE_REVIEW_LABELS[decision],
            "new_run_id": run_id,
            "new_rule_version": source.get("rule_version", ""),
            "rule_changes": [],
            "params_before": old_settings.params(),
            "params_after": old_settings.params(),
            "rows": {
                "bank_before": bank_before,
                "ledger_before": ledger_before,
                "bank_after": bank_before,
                "ledger_after": ledger_before,
                "preserved": True,
            },
        }

        if decision != DECISION_RERUN:
            unchanged_matches = {
                "counts": {"before": len(old_matches), "after": len(old_matches),
                           "added": 0, "removed": 0, "changed": 0},
                "added": [], "removed": [], "changed": [],
            }
            unchanged_diffs = {
                "counts": {"before": len(old_recon["differences"]),
                           "after": len(old_recon["differences"]),
                           "added": 0, "removed": 0},
                "added": [], "removed": [],
            }
            unchanged_rows = {
                side: {
                    "newly_matched": [],
                    "newly_unmatched": [],
                    "still_matched": sorted(_matched_ids(old_matches, side)),
                }
                for side in ("bank", "ledger")
            }
            entry.update({
                "matches": unchanged_matches,
                "differences": unchanged_diffs,
                "rows_changed": unchanged_rows,
                "totals": {"before": old_totals, "after": old_totals},
                "identities": old_identities,
                "publishable": False,
            })
            if decision == DECISION_KEPT_REVIEWED:
                entry["publish_reason"] = "已复核批次保持原结论，不随本次口径重复发布"
                retained_scope.append({
                    "run_id": run_id,
                    "rule_version": source.get("rule_version", ""),
                    "review_status": REVIEW_DONE,
                    "reviewed_at": source.get("reviewed_at", ""),
                    "note": "保持已复核结论",
                })
            else:
                entry["publish_reason"] = "当前批次已经使用目标口径"
            entry["publish_version"] = source.get("rule_version", "")
            batches.append(entry)
            continue

        both = bool(source.get("bank_sha256") and source.get("ledger_sha256"))
        status = "matched" if both else source.get("status", "partial_bank")
        new_run = _new_run(source, records, target_settings, status)

        # 新批次号由「输入 + 目标口径」唯一确定。若这个口径的历史批次仍在使用
        # （未被替代），直接复用它：重算结果确定，复用既不新增记录也不改写历史。
        # 若同号批次已被替代，说明它在口径链的上一环，不能拉回来当新版。
        existing_target = store.get_run(new_run["run_id"])
        reused = existing_target is not None
        if reused:
            if existing_target.get("superseded_by"):
                raise DomainError(
                    "E_CALIBER_CONFLICT",
                    f"目标口径批次 {new_run['run_id']} 已被 "
                    f"{existing_target['superseded_by']} 替代，不能复用",
                    409,
                )
            candidates = store.candidates(new_run["run_id"])
            matches = store.matches(new_run["run_id"])
            new_run = existing_target
        else:
            candidates = candidate_mod.build(records, target_settings) if both else []
            matches = solve_mod.solve(candidates, records, target_settings) if both else []

        new_recon = differences_mod.reconcile(records, matches, target_settings)
        new_identities = _identities(new_recon)
        new_totals = _totals(new_recon)
        match_changes = _match_changes(old_matches, matches)
        difference_changes = _difference_changes(old_recon, new_recon)
        rows_changed = _row_changes(old_matches, matches)
        publishable, publish_reason = _publish_decision(
            new_run.get("status", status), new_identities
        )

        entry.update({
            "new_run_id": new_run["run_id"],
            "new_rule_version": target_settings.rule_version,
            "rule_changes": _param_diff(old_settings.params(), target_params),
            "params_after": target_params,
            "matches": match_changes,
            "differences": difference_changes,
            "rows_changed": rows_changed,
            "totals": {"before": old_totals, "after": new_totals},
            "identities": new_identities,
            "publishable": publishable,
            "publish_reason": publish_reason,
            "publish_version": target_settings.rule_version,
            "reused": reused,
        })
        if reused and new_run.get("review_status") == REVIEW_DONE:
            entry["re_review_required"] = False
            entry["re_review_label"] = "否，目标口径批次已复核"
            entry["publishable"] = False
            entry["publish_reason"] = "目标口径批次已复核，沿用原结论"
            retained_scope.append({
                "run_id": new_run["run_id"],
                "rule_version": new_run.get("rule_version", target_settings.rule_version),
                "review_status": REVIEW_DONE,
                "reviewed_at": new_run.get("reviewed_at", ""),
                "note": "目标口径批次已复核",
            })
            publishable = False
        if publishable:
            publishable_scope.append({
                "run_id": new_run["run_id"],
                "source_run_id": run_id,
                "rule_version": target_settings.rule_version,
                "matches": len(matches),
                "counts": new_recon["counts"],
                "totals": new_totals,
            })
        elif not (reused and new_run.get("review_status") == REVIEW_DONE):
            held_scope.append({
                "run_id": new_run["run_id"],
                "source_run_id": run_id,
                "rule_version": target_settings.rule_version,
                "status": status,
                "reason": entry["publish_reason"],
            })

        match_delta["added"] += match_changes["counts"]["added"]
        match_delta["removed"] += match_changes["counts"]["removed"]
        match_delta["changed"] += match_changes["counts"]["changed"]
        diff_delta["added"] += difference_changes["counts"]["added"]
        diff_delta["removed"] += difference_changes["counts"]["removed"]

        bundles.append({
            "source_run_id": run_id,
            "run": new_run,
            "reused": reused,
            "records": records,
            "candidates": candidates,
            "matches": matches,
        })
        batches.append(entry)

    rerun_count = len(bundles)
    kept_count = sum(1 for item in batches if item["decision"] == DECISION_KEPT_REVIEWED)
    current_count = sum(
        1 for item in batches if item["decision"] == DECISION_CURRENT
    )

    result = {
        "upgrade_id": upgrade_id_for(target_settings, live),
        "created_at": utc_now_iso(),
        "source_rule_version": base_settings.rule_version,
        "target": {
            "rule_version": target_settings.rule_version,
            "params": target_params,
        },
        "noop": rerun_count == 0,
        "dry_run": bool(body.get("dry_run")),
        "summary": {
            "batches_total": len(batches),
            "batches_rerun": rerun_count,
            "batches_kept_reviewed": kept_count,
            "batches_already_current": current_count,
            "re_review_required": rerun_count,
            "re_review_skipped": kept_count + current_count,
            "matches_added": match_delta["added"],
            "matches_removed": match_delta["removed"],
            "matches_changed": match_delta["changed"],
            "differences_added": diff_delta["added"],
            "differences_removed": diff_delta["removed"],
            "publishable_batches": len(publishable_scope),
            "held_batches": len(held_scope),
            "retained_reviewed_batches": len(retained_scope),
        },
        "rule_changes": _param_diff(base_settings.params(), target_params),
        "batches": batches,
        "publishable_scope": publishable_scope,
        "held_scope": held_scope,
        "retained_scope": retained_scope,
    }
    return {"impact": result, "target_settings": target_settings, "bundles": bundles}


def apply(store, base_settings, body: dict) -> dict:
    """执行升级：dry_run 只返回影响；否则单事务写入，重复执行不新增记录。"""
    planned = plan(store, base_settings, body)
    impact = planned["impact"]
    bundles = planned["bundles"]
    if body.get("dry_run"):
        impact["applied"] = False
        impact["created"] = False
        return impact
    if not bundles:
        # 没有需要重算的批次（全部已复核或已在新口径）：这份升级仍记录一次决策，
        # 以便页面与审计看到「哪些批次不重新复核」；重复执行命中同一条记录。
        stored = store.get_upgrade(impact["upgrade_id"]) if impact["upgrade_id"] else None
        if stored is not None:
            previous = stored["impact"]
            previous["applied"] = True
            previous["created"] = False
            previous["dry_run"] = False
            previous["replayed"] = True
            return previous

    write = {
        "upgrade_id": impact["upgrade_id"],
        "created_at": impact["created_at"],
        "target_rule_version": impact["target"]["rule_version"],
        "params": impact["target"]["params"],
        "active_caliber": impact["target"],
        "source_run_ids": [bundle["source_run_id"] for bundle in bundles],
        "impact": impact,
        "runs": bundles,
    }
    outcome = store.apply_upgrade(write)
    impact["applied"] = True
    impact["created"] = outcome["created"]
    impact["upgrade_id"] = outcome["upgrade"]["upgrade_id"]
    impact["created_at"] = outcome["upgrade"]["created_at"]
    if not outcome["created"]:
        # 重复执行：返回首次落库的影响结果，不产生第二份记录。
        impact = outcome["upgrade"]["impact"]
        impact["applied"] = True
        impact["created"] = False
        impact["dry_run"] = False
    return impact


def active_settings(store, base_settings):
    """当前生效口径的配置；没升级过时就是默认配置。

    导入、单步重跑与样例运行都从这里取，避免升级后新旧口径混用。
    """
    caliber = store.active_caliber() if hasattr(store, "active_caliber") else {}
    if not caliber:
        return base_settings
    params = caliber.get("params") or {}
    return base_settings.with_caliber(
        caliber.get("rule_version") or base_settings.rule_version,
        tolerance=params.get("tolerance"),
        window_days=params.get("window_days"),
        subset_max=params.get("subset_max"),
        fee_quantum=params.get("fee_quantum"),
    )


def report(store, run: dict | None) -> dict:
    """只读：当前生效批次所属的升级记录与影响结果。"""
    if not run:
        return {"run_id": None, "upgrade": None, "batches": []}
    upgrade_ref = ""
    for upgrade in store.list_upgrades(20):
        impact = upgrade["impact"]
        if run["run_id"] in upgrade["source_run_ids"]:
            upgrade_ref = upgrade["upgrade_id"]
            break
        if any(item.get("new_run_id") == run["run_id"] for item in impact.get("batches", [])):
            upgrade_ref = upgrade["upgrade_id"]
            break
        if any(item.get("run_id") == run["run_id"]
               for item in impact.get("retained_scope", [])):
            upgrade_ref = upgrade["upgrade_id"]
            break
    if not upgrade_ref:
        return {"run_id": run["run_id"], "upgrade": None, "batches": []}
    upgrade = store.get_upgrade(upgrade_ref)
    return {
        "run_id": run["run_id"],
        "upgrade": upgrade,
        "batches": upgrade["impact"].get("batches", []),
    }
