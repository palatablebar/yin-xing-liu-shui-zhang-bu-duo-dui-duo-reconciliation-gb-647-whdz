"""匹配入口：求解与查看匹配组。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import service

router = APIRouter(prefix="/api/matches", tags=["匹配"])


@router.get("")
def get_matches(request: Request):
    store = request.app.state.store
    return service.payload(store, store.latest_run())


@router.post("")
def post_matches(request: Request):
    store = request.app.state.store
    return service.run_matching(store, store.latest_run(), request.app.state.settings)
