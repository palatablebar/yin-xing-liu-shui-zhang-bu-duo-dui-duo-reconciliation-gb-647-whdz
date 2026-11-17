"""运行参数与常量：容差、日期窗口、子集上限、编码链、空值哨兵、账户登记。

所有阈值只在这里定义一次，规则模块与页面都从这里取，避免两处不一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

RULE_VERSION = "2026.11.1"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# 编码回退链：先按带 BOM 的 UTF-8 解，再按 UTF-8，最后按 GB18030。
ENCODING_CHAIN = ("utf-8-sig", "utf-8", "gb18030")

# 空值哨兵：金额列命中这些值表示「没有填」，不是 0。
SENTINELS = ("", "-", "--", "n/a", "na", "null", "none", "未知")

# 借贷方向别名：正号表示资金流入，负号表示资金流出。
DIRECTION_ALIASES = {
    "贷": 1, "收": 1, "收入": 1, "credit": 1, "cr": 1, "+": 1, "c": 1,
    "借": -1, "付": -1, "支出": -1, "debit": -1, "dr": -1, "-": -1, "d": -1,
}

# 账户登记：未登记的账户进隔离区，不参与对账。
ACCOUNTS = {
    "6222-0012": "基本户",
    "6222-0034": "一般户",
    "6222-0056": "货款户",
}


def dec(value) -> Decimal:
    """把存储里的字符串金额转回 Decimal；已是 Decimal 时原样返回。"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value not in (None, "") else "0"))


@dataclass(frozen=True)
class Settings:
    db_path: str
    rule_version: str = RULE_VERSION
    tolerance: Decimal = Decimal("0.02")
    window_days: int = 3
    subset_max: int = 4
    fee_quantum: Decimal = Decimal("0.01")
    tz_name: str = "Asia/Shanghai"
    sample_dir: str = str(PROJECT_DIR / "sample_data")
    encodings: tuple = ENCODING_CHAIN
    sentinels: tuple = SENTINELS
    accounts: dict = field(default_factory=lambda: dict(ACCOUNTS))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("LEDGERBANK_DB", str(PROJECT_DIR / "var" / "ledgerbank.sqlite")),
            rule_version=os.environ.get("RULE_VERSION", RULE_VERSION),
            sample_dir=os.environ.get("SAMPLE_DIR", str(PROJECT_DIR / "sample_data")),
            tz_name=os.environ.get("TZ", "Asia/Shanghai"),
        )

    def params(self) -> dict:
        return {
            "tolerance": str(self.tolerance),
            "window_days": self.window_days,
            "subset_max": self.subset_max,
            "fee_quantum": str(self.fee_quantum),
            "timezone": self.tz_name,
        }
