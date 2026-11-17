"""列契约：两侧的规范字段、列别名、必填项与取值含义。

列别名让旧导出文件的列名（交易金额 / 凭证金额 …）映射到同一套规范字段。
"""
from __future__ import annotations

from ..m1_ingest.decode import normalize_cell

FIELDS = {
    "bank": (
        ("txn_no", "流水号", "文本，保留前导零与大整数"),
        ("account", "账户", "文本，保留前导零"),
        ("posted_at", "发生时间", "带偏移时间或日期，统一转 UTC"),
        ("direction", "借贷标志", "贷/收 为 +1，借/付 为 -1"),
        ("amount", "金额", "Decimal，元，2 位小数"),
        ("fee", "手续费", "Decimal，元，2 位小数；空值表示无"),
        ("counterparty", "对方户名", "文本"),
        ("memo", "摘要", "文本"),
    ),
    "ledger": (
        ("txn_no", "凭证号", "文本，保留前导零与大整数"),
        ("account", "账户", "文本，保留前导零"),
        ("posted_at", "记账日期", "日期或带偏移时间，统一转 UTC"),
        ("direction", "方向", "借/贷，含义与银行侧一致"),
        ("amount", "金额", "Decimal，元，2 位小数"),
        ("fee", "手续费", "账簿侧一般留空"),
        ("memo", "摘要", "文本"),
    ),
}

ALIASES = {
    "bank": {
        "txn_no": ("流水号", "交易流水号", "交易编号", "银行流水号", "交易序号", "txn_no"),
        "account": ("账户", "账号", "银行账号", "account"),
        "posted_at": ("发生时间", "交易时间", "记账时间", "发生日期", "交易日期", "posted_at"),
        "direction": ("借贷标志", "收付标志", "方向", "借贷方向", "direction"),
        "amount": ("金额", "交易金额", "发生金额", "amount"),
        "fee": ("手续费", "费用", "fee"),
        "counterparty": ("对方户名", "对方名称", "对方账户名", "counterparty"),
        "memo": ("摘要", "附言", "备注", "memo"),
    },
    "ledger": {
        "txn_no": ("凭证号", "凭证编号", "记账凭证号", "voucher_no"),
        "account": ("账户", "账号", "银行账号", "account"),
        "posted_at": ("记账日期", "发生日期", "日期", "posted_at"),
        "direction": ("方向", "借贷标志", "收付标志", "direction"),
        "amount": ("金额", "凭证金额", "amount"),
        "fee": ("手续费", "fee"),
        "memo": ("摘要", "附言", "备注", "memo"),
    },
}

REQUIRED = ("txn_no", "account", "posted_at", "direction", "amount")


def alias_index(side: str) -> dict[str, str]:
    """列名（归一后小写）→ 规范字段。"""
    table: dict[str, str] = {}
    for field, names in ALIASES[side].items():
        for name in names:
            table[normalize_cell(name).lower()] = field
    return table


def payload(settings) -> dict:
    return {
        "fields": {
            side: [
                {"name": name, "label": label, "note": note,
                 "required": name in REQUIRED,
                 "aliases": list(ALIASES[side][name])}
                for name, label, note in FIELDS[side]
            ]
            for side in ("bank", "ledger")
        },
        "tolerance": str(settings.tolerance),
        "window_days": settings.window_days,
        "subset_max": settings.subset_max,
        "direction": {"in": ["贷", "收", "credit"], "out": ["借", "付", "debit"]},
        "accounts": settings.accounts,
        "fee_policy": "手续费计入银行侧，不进入匹配金额",
    }
