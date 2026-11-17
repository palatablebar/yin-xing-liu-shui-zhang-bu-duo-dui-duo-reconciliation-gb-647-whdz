"""契约服务：列别名表与契约内容。"""
from __future__ import annotations

from . import contract


def alias_index(side: str) -> dict[str, str]:
    if side not in ("bank", "ledger"):
        raise ValueError("side 只能是 bank 或 ledger")
    return contract.alias_index(side)


def payload(settings) -> dict:
    return contract.payload(settings)
