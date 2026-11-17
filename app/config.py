"""运行参数与常量：容差、日期窗口、子集上限、编码链、空值哨兵、账户登记。

所有阈值只在这里定义一次，规则模块与页面都从这里取，避免两处不一致。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

RULE_VERSION = "2026.11.1"
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# 口径升级只允许改这些匹配参数；规则版本与参数共同决定 run_id。
# 时区影响采信阶段的日期解析，升级不重读源文件，因此不在此列。
CALIBER_KEYS = ("tolerance", "window_days", "subset_max", "fee_quantum")
CALIBER_LABELS = {
    "tolerance": "金额容差",
    "window_days": "日期窗口",
    "subset_max": "子集上限",
    "fee_quantum": "手续费精度",
}

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

    def with_caliber(self, rule_version: str, tolerance=None, window_days=None,
                     subset_max=None, fee_quantum=None, tz_name=None) -> "Settings":
        """派生一份新口径的配置；未给出的项沿用当前值。"""
        return replace(
            self,
            rule_version=rule_version or self.rule_version,
            tolerance=Decimal(str(tolerance)) if tolerance is not None else self.tolerance,
            window_days=int(window_days) if window_days is not None else self.window_days,
            subset_max=int(subset_max) if subset_max is not None else self.subset_max,
            fee_quantum=(
                Decimal(str(fee_quantum)) if fee_quantum is not None else self.fee_quantum
            ),
            tz_name=tz_name or self.tz_name,
        )

    def for_run(self, run: dict | None) -> "Settings":
        """按批次自己记录的规则版本与参数派生配置。

        页面、导出与差异复算都走这一处，保证同一批次在页面和文件里是同一版。
        """
        if not run:
            return self
        params = run.get("params") or {}
        return self.with_caliber(
            run.get("rule_version") or self.rule_version,
            tolerance=params.get("tolerance"),
            window_days=params.get("window_days"),
            subset_max=params.get("subset_max"),
            fee_quantum=params.get("fee_quantum"),
        )
