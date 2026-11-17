"""采信编排：按侧读取样例或上传文件，返回逐行诊断。

本模块只负责「读进来、切行、判列」，金额与日期归一交给契约模块。
"""
from __future__ import annotations

from pathlib import Path

from ...errors import DomainError
from .reader import read_statement


def resolve_sample(settings, name: str) -> tuple[str, bytes]:
    base = Path(settings.sample_dir)
    path = (base / name).resolve()
    if base.resolve() not in path.parents and path.parent != base.resolve():
        raise DomainError("E_SAMPLE_PATH", "样例文件名不合法", 400)
    if not path.is_file():
        raise DomainError("E_SAMPLE_NOT_FOUND", f"样例不存在：{name}", 404)
    return name, path.read_bytes()


def read_and_map(settings, side: str, filename: str, raw: bytes, aliases: dict) -> dict:
    outcome = read_statement(raw, aliases, settings.encodings)
    outcome["side"] = side
    outcome["filename"] = filename
    outcome["bytes"] = len(raw)
    return outcome
