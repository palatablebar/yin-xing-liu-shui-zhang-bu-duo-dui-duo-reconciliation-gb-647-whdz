"""导出入口：报告 CSV 与运行清单 JSON。

支持 ``run_id``：指定历史批次时导出的就是那一批的页面结论，页码与文件同版。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...errors import DomainError
from . import service

router = APIRouter(tags=["导出"])


def _run(store, run_id: str | None):
    if run_id:
        run = store.get_run(run_id)
        if run is None:
            raise DomainError("E_NO_RUN", "批次不存在", 404)
        return run
    return store.latest_run()


@router.get("/api/export/summary")
def get_summary(request: Request, run_id: str | None = None):
    store = request.app.state.store
    return service.summary(store, _run(store, run_id), request.app.state.settings)


@router.get("/api/export/report.csv")
def get_report(request: Request, run_id: str | None = None):
    store = request.app.state.store
    text = service.report(store, _run(store, run_id), request.app.state.settings)
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.csv"'},
    )


@router.get("/api/export/manifest.json")
def get_manifest(request: Request, run_id: str | None = None):
    store = request.app.state.store
    text = service.manifest(store, _run(store, run_id), request.app.state.settings)
    return Response(
        content=text,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
    )
