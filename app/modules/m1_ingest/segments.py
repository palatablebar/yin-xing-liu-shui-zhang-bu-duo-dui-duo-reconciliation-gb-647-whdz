"""表头识别、分段、列数与末行截断判定。

- 表头行：归一后至少 3 个单元格命中列别名；
- 重复表头：分段导出常见，计入段数但不作为数据行；
- 末行截断：文件末行没有换行且列数少于表头。
"""
from __future__ import annotations

from .decode import normalize_cell


def header_like(cells, aliases) -> bool:
    hits = 0
    for cell in cells:
        token = normalize_cell(cell).lower()
        if token and token in aliases:
            hits += 1
    return hits >= 3


def split_records(rows, aliases, trailing_newline: bool) -> dict:
    header: list[str] | None = None
    header_map: dict[str, int] = {}
    segments = 0
    blank_rows = 0
    records: list[dict] = []

    for row_no, cells in rows:
        normalized = [normalize_cell(cell) for cell in cells]
        if not any(normalized):
            blank_rows += 1
            continue
        if header_like(normalized, aliases):
            segments += 1
            if header is None:
                header = normalized
                for index, name in enumerate(normalized):
                    canonical = aliases.get(name.lower())
                    if canonical and canonical not in header_map:
                        header_map[canonical] = index
            continue
        if header is None:
            return {
                "error": "HEADER_MISSING",
                "segments": segments,
                "blank_rows": blank_rows,
                "records": [],
                "header": [],
                "header_map": {},
            }
        cells_map: dict[str, str] = {}
        for canonical, index in header_map.items():
            cells_map[canonical] = cells[index] if index < len(cells) else ""
        records.append(
            {
                "row_no": row_no,
                "cells": cells_map,
                "raw": cells,
                "column_ok": len(cells) == len(header),
                "truncated": False,
            }
        )

    if records and not trailing_newline:
        last = records[-1]
        if not last["column_ok"]:
            last["truncated"] = True

    return {
        "error": None,
        "segments": segments,
        "blank_rows": blank_rows,
        "records": records,
        "header": header or [],
        "header_map": header_map,
    }
