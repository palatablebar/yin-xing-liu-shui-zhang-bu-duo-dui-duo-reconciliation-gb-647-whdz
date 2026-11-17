"""导出入口：报告 CSV 与运行清单 JSON。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from . import service

router = APIRouter(tags=["导出"])


@router.get("/api/export/summary")
def get_summary(request: Request):
    store = request.app.state.store
    return service.summary(store, store.latest_run(), request.app.state.settings)


@router.get("/api/export/report.csv")
def get_report(request: Request):
    store = request.app.state.store
    text = service.report(store, store.latest_run(), request.app.state.settings)
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.csv"'},
    )


@router.get("/api/export/manifest.json")
def get_manifest(request: Request):
    store = request.app.state.store
    text = service.manifest(store, store.latest_run(), request.app.state.settings)
    return Response(
        content=text,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
    )
