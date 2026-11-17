"""采信入口：导入一份银行流水或账簿凭证。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from ...errors import DomainError
from ...pipeline import import_side

router = APIRouter(prefix="/api/statements", tags=["采信"])


@router.post("/import")
async def import_statement(
    request: Request,
    side: str = Form("bank"),
    sample: str = Form(""),
    file: UploadFile | None = File(None),
):
    if side not in ("bank", "ledger"):
        raise DomainError("E_SIDE", "side 只能是 bank 或 ledger", 400)
    settings = request.app.state.settings
    store = request.app.state.store
    if file is not None and file.filename:
        raw = await file.read()
        filename = file.filename
    elif sample:
        from .service import resolve_sample

        filename, raw = resolve_sample(settings, sample)
    else:
        raise DomainError("E_INPUT", "需要上传文件或指定样例", 400)
    return import_side(settings, store, side, filename, raw)


@router.get("")
def list_statement_rows(request: Request, side: str = "bank", status: str = "valid"):
    if side not in ("bank", "ledger"):
        raise DomainError("E_SIDE", "side 只能是 bank 或 ledger", 400)
    store = request.app.state.store
    run = store.latest_run()
    if not run:
        return {"run_id": None, "rows": [], "count": 0}
    rows = store.records(run["run_id"], side=side, status=status)
    return {"run_id": run["run_id"], "count": len(rows), "rows": rows}
