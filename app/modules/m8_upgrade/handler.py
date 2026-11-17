"""口径升级入口：计算影响、执行升级、查看升级记录与复核批次。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Request

from ...errors import DomainError
from . import service

router = APIRouter(tags=["口径升级"])


def _body(payload: dict | None) -> dict:
    return payload or {}


@router.post("/api/upgrades/impact")
def post_impact(request: Request, payload: dict | None = Body(default=None)):
    """只算不写：先看受影响匹配、差异与可发布范围。"""
    return service.apply(
        request.app.state.store, request.app.state.settings,
        {**_body(payload), "dry_run": True},
    )


@router.post("/api/upgrades")
def post_upgrade(request: Request, payload: dict | None = Body(default=None)):
    service_body = _body(payload)
    service_body.pop("dry_run", None)
    result = service.apply(request.app.state.store, request.app.state.settings, service_body)
    return result


# 单数别名：命令行与旧脚本更常写 /api/upgrade。
@router.post("/api/upgrade/impact", include_in_schema=False)
def post_impact_alias(request: Request, payload: dict | None = Body(default=None)):
    return post_impact(request, payload)


@router.post("/api/upgrade", include_in_schema=False)
def post_upgrade_alias(request: Request, payload: dict | None = Body(default=None)):
    return post_upgrade(request, payload)


@router.get("/api/upgrades")
def get_upgrades(request: Request):
    store = request.app.state.store
    upgrades = store.list_upgrades(20)
    return {"count": len(upgrades), "upgrades": upgrades}


@router.get("/api/upgrades/{upgrade_id}")
def get_upgrade(request: Request, upgrade_id: str):
    store = request.app.state.store
    upgrade = store.get_upgrade(upgrade_id)
    if upgrade is None:
        raise DomainError("E_NO_UPGRADE", "升级记录不存在", 404)
    return upgrade


@router.get("/api/upgrade/current")
def get_current(request: Request):
    """当前生效批次所属升级的影响结果，页面与导出共用同一份。"""
    store = request.app.state.store
    return service.report(store, store.latest_run())
