"""契约入口：查看两侧列定义、容差与日期窗口。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from .service import payload

router = APIRouter(prefix="/api/contract", tags=["契约"])


@router.get("")
def get_contract(request: Request):
    return payload(request.app.state.settings)
