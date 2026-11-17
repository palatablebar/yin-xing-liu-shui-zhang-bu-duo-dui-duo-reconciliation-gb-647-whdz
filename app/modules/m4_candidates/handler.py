"""候选入口：生成候选与查看候选。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import service

router = APIRouter(prefix="/api/candidates", tags=["候选"])


@router.get("")
def get_candidates(request: Request):
    store = request.app.state.store
    return service.payload(store, store.latest_run())


@router.post("")
def post_candidates(request: Request):
    store = request.app.state.store
    return service.refresh(store, store.latest_run(), request.app.state.settings)
