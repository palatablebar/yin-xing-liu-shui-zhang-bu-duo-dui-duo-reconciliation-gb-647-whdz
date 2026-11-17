"""编码回退与单元格归一。

真实流水里同时出现带 BOM 的 UTF-8、无 BOM 的 UTF-8 和 GB18030；这里按声明顺序
逐个严格解码，失败才回退，并把 BOM 从首列名里剥掉，避免按列名取值全空。
"""
from __future__ import annotations

import unicodedata

BOM_CHAR = "\ufeff"


def decode_bytes(raw: bytes, encodings) -> dict:
    if not raw:
        return {"text": "", "encoding": None, "bom": False, "error": "EMPTY_FILE"}
    bom = raw.startswith(b"\xef\xbb\xbf")
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        return {
            "text": text.replace(BOM_CHAR, ""),
            "encoding": encoding,
            "bom": bom,
            "error": None,
        }
    text = raw.decode(encodings[-1], errors="replace").replace(BOM_CHAR, "")
    return {"text": text, "encoding": encodings[-1], "bom": bom, "error": "DECODE_FALLBACK"}


def normalize_cell(value: str | None) -> str:
    """全角转半角（NFKC）、去 BOM、去首尾空白（含全角空格）。"""
    text = unicodedata.normalize("NFKC", value or "")
    return text.replace(BOM_CHAR, "").strip().strip("\u3000").strip()
