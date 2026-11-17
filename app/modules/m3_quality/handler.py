"""质量入口：列表、原因分布、隔离 CSV。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from . import service

router = APIRouter(tags=["质量"])


@router.get("/api/quarantine")
def get_quarantine(request: Request):
    store = request.app.state.store
    return service.payload(store, store.latest_run())


@router.get("/api/quarantine.csv")
def get_quarantine_csv(request: Request):
    store = request.app.state.store
    text = service.csv_text(store, store.latest_run())
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="quarantine.csv"'},
    )
