"""页面装配：模板环境、格式化过滤器、六个页面的上下文。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from . import reasons
from .config import BASE_DIR
from .modules.m2_contract import service as contract_service
from .modules.m5_matching.subset import TIER_NAMES
from .modules.m6_diff import differences as differences_mod
from .modules.m6_diff import history as history_mod
from .modules.m7_export import service as export_service

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LOCAL_TZ = timezone(timedelta(hours=8))

NAV = (
    ("工作台", "/"),
    ("隔离区", "/quarantine"),
    ("候选", "/candidates"),
    ("匹配", "/matches"),
    ("批次", "/batches"),
    ("导出", "/export"),
)


def _decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def money(value) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "0.00"
    return f"{parsed:,.2f}"


def signed_money(value) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "0.00"
    if parsed == 0:
        return "0.00"
    return f"{parsed:+,.2f}"


def local_dt(value) -> str:
    if not value:
        return "-"
    try:
        instant = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def short_sha(value) -> str:
    return (str(value) or "")[:10]


def reason_label(code: str) -> str:
    return reasons.label(code)


def tier_label(tier) -> str:
    return TIER_NAMES.get(int(tier), "")


STATUS_LABELS = {
    "matched": "已匹配",
    "ready": "待匹配",
    "partial_bank": "仅银行",
    "partial_ledger": "仅账簿",
    "empty": "空批次",
}

TOTAL_LABELS = {
    "bank_gross": "银行发生额",
    "bank_fee": "手续费",
    "bank_total": "银行合计",
    "bank_matched": "银行匹配",
    "bank_unmatched": "银行未匹配",
    "ledger_total": "账簿合计",
    "ledger_matched": "账簿匹配",
    "ledger_unmatched": "账簿未匹配",
    "match_gap": "匹配差额",
    "fee_alloc_total": "手续费分摊",
    "fee_actual_total": "手续费实际",
}


def status_label(value) -> str:
    text = str(value or "")
    return STATUS_LABELS.get(text, reasons.label(text) if text in reasons.REASONS else text)


def setup(app: FastAPI) -> None:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.filters["money"] = money
    templates.env.filters["signed_money"] = signed_money
    templates.env.filters["localdt"] = local_dt
    templates.env.filters["shortsha"] = short_sha
    templates.env.filters["reason_label"] = reason_label
    templates.env.filters["tier_label"] = tier_label
    templates.env.filters["status_label"] = status_label
    app.state.templates = templates

    def base(request: Request, title: str, current: str) -> dict:
        store = request.app.state.store
        return {
            "request": request,
            "title": title,
            "current": current,
            "nav": NAV,
            "run": store.latest_run(),
            "settings": request.app.state.settings,
        }

    def render(request: Request, template: str, context: dict):
        return templates.TemplateResponse(request, template, context)

    @app.get("/")
    def index(request: Request):
        store = request.app.state.store
        settings = request.app.state.settings
        context = base(request, "工作台", "/")
        run = context["run"]
        records = store.records(run["run_id"]) if run else []
        matches = store.matches(run["run_id"]) if run else []
        bank_rows = [row for row in records if row["side"] == "bank" and row["status"] == "valid"]
        ledger_rows = [row for row in records
                       if row["side"] == "ledger" and row["status"] == "valid"]
        pairs: dict[str, str] = {}
        for group in matches:
            for key in group["bank_ids"] + group["ledger_ids"]:
                pairs[key] = group["match_id"]
        reconciliation = (
            differences_mod.reconcile(records, matches, settings) if run else None
        )
        context.update({
            "bank_rows": bank_rows,
            "ledger_rows": ledger_rows,
            "matches": matches,
            "reconciliation": reconciliation,
            "pairs": pairs,
            "contract": contract_service.payload(settings),
            "quarantine_count": len(store.quarantine(run["run_id"])) if run else 0,
        })
        return render(request, "index.html", context)

    @app.get("/quarantine")
    def quarantine(request: Request):
        store = request.app.state.store
        context = base(request, "隔离区", "/quarantine")
        run = context["run"]
        records = store.records(run["run_id"]) if run else []
        context.update({
            "rows": [row for row in records if row["status"] == "quarantine"],
            "distribution": reasons.distribution(
                [row for row in records if row["status"] == "quarantine"]
            ),
        })
        return render(request, "quarantine.html", context)

    @app.get("/candidates")
    def candidates(request: Request):
        store = request.app.state.store
        context = base(request, "候选", "/candidates")
        run = context["run"]
        items = store.candidates(run["run_id"]) if run else []
        tiers: dict[str, int] = {}
        for item in items:
            tiers[str(item["tier"])] = tiers.get(str(item["tier"]), 0) + 1
        context.update({"items": items, "tiers": tiers, "tier_names": TIER_NAMES})
        return render(request, "candidates.html", context)

    @app.get("/matches")
    def matches(request: Request):
        store = request.app.state.store
        context = base(request, "匹配", "/matches")
        run = context["run"]
        groups = store.matches(run["run_id"]) if run else []
        fee_total = sum((Decimal(group["fee_alloc"]) for group in groups), Decimal("0.00"))
        context.update({
            "groups": groups,
            "tier_names": TIER_NAMES,
            "fee_total": fee_total,
        })
        return render(request, "matches.html", context)

    @app.get("/batches")
    def batches(request: Request):
        store = request.app.state.store
        settings = request.app.state.settings
        context = base(request, "批次", "/batches")
        run = context["run"]
        batches_list = history_mod.batches(store, 12)
        reconciliation = None
        manifest = None
        if run:
            records = store.records(run["run_id"])
            matches = store.matches(run["run_id"])
            reconciliation = differences_mod.reconcile(records, matches, settings)
            manifest = history_mod.manifest(store, run, reconciliation["totals"])
        context.update({
            "batches": batches_list,
            "reconciliation": reconciliation,
            "manifest": manifest,
        })
        return render(request, "batches.html", context)

    @app.get("/export")
    def export(request: Request):
        store = request.app.state.store
        settings = request.app.state.settings
        context = base(request, "导出", "/export")
        run = context["run"]
        summary = export_service.summary(store, run, settings)
        total_rows = [
            {"label": TOTAL_LABELS.get(key, key), "value": value}
            for key, value in summary.get("totals", {}).items()
        ]
        context.update({"summary": summary, "total_rows": total_rows})
        return render(request, "export.html", context)
