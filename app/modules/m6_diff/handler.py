"""差异与批次入口。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import service

router = APIRouter(tags=["差异"])


@router.get("/api/differences")
def get_differences(request: Request):
    store = request.app.state.store
    return service.payload(store, store.latest_run(), request.app.state.settings)


@router.get("/api/batches")
def get_batches(request: Request):
    return service.batches_payload(request.app.state.store)


@router.get("/api/batches/{run_id}")
def get_batch(request: Request, run_id: str):
    return service.batch_detail(request.app.state.store, run_id, request.app.state.settings)
