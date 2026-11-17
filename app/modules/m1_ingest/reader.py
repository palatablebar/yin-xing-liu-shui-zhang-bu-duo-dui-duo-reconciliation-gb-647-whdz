"""流式读入一份流水文件：解码 → CSV 解析 → 分段与列校验。

用 csv 模块而不是 splitlines()，单元格里的换行与引号不会被切成两条记录。
"""
from __future__ import annotations

import csv
import io

from .decode import decode_bytes
from .segments import split_records


def read_statement(raw: bytes, aliases: dict, encodings) -> dict:
    decoded = decode_bytes(raw, encodings)
    if decoded["error"] == "EMPTY_FILE":
        return {
            "state": "EMPTY_FILE",
            "encoding": None,
            "bom": False,
            "segments": 0,
            "blank_rows": 0,
            "records": [],
            "raw_rows": 0,
        }

    text = decoded["text"]
    trailing_newline = text.endswith("\n")
    parsed_rows: list[tuple[int, list[str]]] = []
    reader = csv.reader(io.StringIO(text, newline=""))
    for cells in reader:
        parsed_rows.append((reader.line_num, cells))

    outcome = split_records(parsed_rows, aliases, trailing_newline)
    if outcome["error"] == "HEADER_MISSING":
        state = "HEADER_MISSING"
    elif not outcome["records"]:
        state = "ALL_BLANK" if outcome["blank_rows"] else "HEADER_ONLY"
    else:
        state = None

    return {
        "state": state,
        "encoding": decoded["encoding"],
        "bom": decoded["bom"],
        "segments": outcome["segments"],
        "blank_rows": outcome["blank_rows"],
        "records": outcome["records"],
        "raw_rows": len(outcome["records"]),
        "header_map": outcome["header_map"],
    }
