"""应用装配：配置 → 存储 → 页面 → 七个功能模块路由。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, errors, pipeline, web
from .store import Store
from .modules.m1_ingest import handler as m1_handler
from .modules.m2_contract import handler as m2_handler
from .modules.m3_quality import handler as m3_handler
from .modules.m4_candidates import handler as m4_handler
from .modules.m5_matching import handler as m5_handler
from .modules.m6_diff import handler as m6_handler
from .modules.m7_export import handler as m7_handler

MODULES = (m1_handler, m2_handler, m3_handler, m4_handler, m5_handler,
           m6_handler, m7_handler)


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.Settings.from_env()
    app = FastAPI(
        title="ledgerbank 银行流水与账簿对账",
        description="采信 → 质量 → 候选 → 匹配 → 差异 → 导出",
        version=settings.rule_version,
    )
    app.state.settings = settings
    app.state.store = Store(settings.db_path)
    web.setup(app)
    app.mount("/static", StaticFiles(directory=str(web.STATIC_DIR)), name="static")
    for module in MODULES:
        app.include_router(module.router)
    errors.install_handlers(app)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        store = request.app.state.store
        run = store.latest_run()
        return {
            "status": "ok",
            "rule_version": settings.rule_version,
            "run_id": run["run_id"] if run else None,
            "status_of_run": run["status"] if run else "empty",
        }

    @app.post("/api/demo/run")
    def demo(request: Request) -> dict:
        return pipeline.run_demo(request.app.state.settings, request.app.state.store)

    def _head_ok() -> Response:
        return Response(status_code=200, media_type="text/html; charset=utf-8")

    for path in ("/", "/quarantine", "/candidates", "/matches", "/batches", "/export",
                 "/api/health"):
        app.add_api_route(path, _head_ok, methods=["HEAD"], include_in_schema=False)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # noqa: ANN001
        return JSONResponse(status_code=400,
                            content={"error": "E_BAD_REQUEST", "message": str(exc)})

    return app
