"""原因码唯一来源。

隔离行、未匹配行、差异行都只从这里取码与中文名；页面、CSV、清单共用同一份文字。
"""
from __future__ import annotations

# code -> (中文名, 所属阶段)
REASONS = {
    "EMPTY_FILE": ("空文件", "采信"),
    "HEADER_ONLY": ("仅表头", "采信"),
    "ALL_BLANK": ("全空行", "采信"),
    "HEADER_MISSING": ("表头缺失", "采信"),
    "TRUNCATED_TAIL": ("末行截断", "采信"),
    "COLUMN_COUNT": ("列数不齐", "采信"),
    "MISSING_FIELD": ("必填字段缺失", "质量"),
    "AMOUNT_SENTINEL": ("金额为空值", "质量"),
    "AMOUNT_PARSE": ("金额无法解析", "质量"),
    "FEE_PARSE": ("手续费无法解析", "质量"),
    "SIGN_UNKNOWN": ("借贷符号未知", "质量"),
    "DATE_PARSE": ("日期无法解析", "质量"),
    "ACCOUNT_UNKNOWN": ("账户未登记", "质量"),
    "DUP_TXN_CONFLICT": ("流水号取值冲突", "质量"),
    "BANK_UNMATCHED": ("银行未匹配", "差异"),
    "LEDGER_UNMATCHED": ("账簿未匹配", "差异"),
    "TOLERANCE_GAP": ("容差差额", "差异"),
    "FEE_TOTAL": ("手续费合计", "差异"),
}

# 一行同时命中多条规则时，按此顺序取主原因码，保证结果不随检查顺序变化。
PRIORITY = (
    "COLUMN_COUNT",
    "TRUNCATED_TAIL",
    "MISSING_FIELD",
    "AMOUNT_SENTINEL",
    "AMOUNT_PARSE",
    "FEE_PARSE",
    "SIGN_UNKNOWN",
    "DATE_PARSE",
    "ACCOUNT_UNKNOWN",
    "DUP_TXN_CONFLICT",
)

STAGES = ("采信", "质量", "候选", "求解", "差异", "导出")


def label(code: str) -> str:
    return REASONS.get(code, ("未分类", "未知"))[0]


def stage_of(code: str) -> str:
    return REASONS.get(code, ("", "未知"))[1]


def primary(codes) -> str | None:
    """多条原因码取优先级最高的一条。"""
    found = [c for c in PRIORITY if c in codes]
    if found:
        return found[0]
    return codes[0] if codes else None


def distribution(items) -> list[dict]:
    """按原因码统计条数，稳定排序。"""
    counts: dict[str, int] = {}
    for item in items:
        code = item.get("reason") or item.get("code") or "UNKNOWN"
        counts[code] = counts.get(code, 0) + 1
    return [
        {"code": code, "label": label(code), "count": counts[code]}
        for code in sorted(counts)
    ]
