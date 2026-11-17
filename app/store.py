"""SQLite 存储：批次、流水行、候选、匹配与口径升级结果。

约定：
- 金额与手续费一律存 Decimal 字符串，不落 float；
- 一次运行的所有行在同一个事务里写入，失败整体回滚；
- 同一 run_id 重跑先删后插，行数、合计与首跑一致；
- 已复核批次与已被新口径替代的批次都是只读的，任何重跑不得覆盖；
- 大整数编号（流水号、凭证号）按字符串保形，不过 int()。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import DomainError
from .manifest import utc_now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    bank_sha256 TEXT NOT NULL DEFAULT '',
    ledger_sha256 TEXT NOT NULL DEFAULT '',
    bank_file TEXT NOT NULL DEFAULT '',
    ledger_file TEXT NOT NULL DEFAULT '',
    bank_bytes INTEGER NOT NULL DEFAULT 0,
    ledger_bytes INTEGER NOT NULL DEFAULT 0,
    bank_raw INTEGER NOT NULL DEFAULT 0,
    ledger_raw INTEGER NOT NULL DEFAULT 0,
    bank_valid INTEGER NOT NULL DEFAULT 0,
    ledger_valid INTEGER NOT NULL DEFAULT 0,
    bank_quar INTEGER NOT NULL DEFAULT 0,
    ledger_quar INTEGER NOT NULL DEFAULT 0,
    segments INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'empty',
    input_states_json TEXT NOT NULL DEFAULT '{}',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending_close',
    reviewed_at TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    supersedes TEXT NOT NULL DEFAULT '',
    superseded_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS records (
    run_id TEXT NOT NULL,
    side TEXT NOT NULL,
    seq INTEGER NOT NULL,
    row_no INTEGER NOT NULL,
    txn_no TEXT NOT NULL,
    account TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    direction INTEGER NOT NULL DEFAULT 0,
    amount TEXT NOT NULL DEFAULT '',
    fee TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'valid',
    reason TEXT NOT NULL DEFAULT '',
    flags_json TEXT NOT NULL DEFAULT '[]',
    raw_json TEXT NOT NULL DEFAULT '[]',
    raw_amount TEXT NOT NULL DEFAULT '',
    raw_date TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_records_run ON records(run_id, side, status);
CREATE TABLE IF NOT EXISTS candidates (
    run_id TEXT NOT NULL,
    cand_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    bank_ids TEXT NOT NULL,
    ledger_ids TEXT NOT NULL,
    bank_sum TEXT NOT NULL,
    ledger_sum TEXT NOT NULL,
    diff TEXT NOT NULL,
    day_gap INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id, tier);
CREATE TABLE IF NOT EXISTS matches (
    run_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    bank_ids TEXT NOT NULL,
    ledger_ids TEXT NOT NULL,
    bank_sum TEXT NOT NULL,
    ledger_sum TEXT NOT NULL,
    diff TEXT NOT NULL,
    day_gap INTEGER NOT NULL DEFAULT 0,
    fee_alloc TEXT NOT NULL DEFAULT '0',
    fee_actual TEXT NOT NULL DEFAULT '0',
    bank_signed TEXT NOT NULL DEFAULT '0',
    ledger_signed TEXT NOT NULL DEFAULT '0'
);
CREATE INDEX IF NOT EXISTS idx_matches_run ON matches(run_id, tier);
CREATE TABLE IF NOT EXISTS upgrades (
    upgrade_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    target_rule_version TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    source_run_ids TEXT NOT NULL DEFAULT '[]',
    impact_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upgrades_created ON upgrades(created_at);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

RUN_COLUMNS = (
    "run_id", "created_at", "rule_version", "params_json", "bank_sha256", "ledger_sha256",
    "bank_file", "ledger_file", "bank_bytes", "ledger_bytes", "bank_raw", "ledger_raw",
    "bank_valid", "ledger_valid", "bank_quar", "ledger_quar", "segments", "status",
    "input_states_json", "duration_ms", "review_status", "reviewed_at", "reviewed_by",
    "supersedes", "superseded_by",
)

# 已复核批次保持原结论；被新口径替代的旧批次也不允许再改写。
LOCKED_REVIEW_STATUSES = ("reviewed",)
LIVE_STATUSES = ("matched", "ready", "partial_bank", "partial_ledger")


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn) -> None:
        """老库补列：口径升级前创建的库没有复核与替代字段。"""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        additions = {
            "review_status": "TEXT NOT NULL DEFAULT 'pending_close'",
            "reviewed_at": "TEXT NOT NULL DEFAULT ''",
            "reviewed_by": "TEXT NOT NULL DEFAULT ''",
            "supersedes": "TEXT NOT NULL DEFAULT ''",
            "superseded_by": "TEXT NOT NULL DEFAULT ''",
        }
        for name, decl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {decl}")

    # ---------- 批次 ----------
    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["params"] = json.loads(data.pop("params_json") or "{}")
        data["input_states"] = json.loads(data.pop("input_states_json") or "{}")
        return data

    def latest_run(self) -> dict | None:
        """当前工作批次：最近创建且未被替代的批次。

        升级生成的新批次总是最后写入；已复核且保持原结论的旧批次仍在历史里可查，
        但不会抢占「当前批次」。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE superseded_by = '' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return self._run_row(row) if row else None

    def get_run(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._run_row(row) for row in rows]

    def live_runs(self) -> list[dict]:
        """所有未被替代的批次，按创建先后排列（升级按此顺序生成新批次）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE superseded_by = '' ORDER BY rowid ASC"
            ).fetchall()
        return [self._run_row(row) for row in rows]

    def list_upgrades(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM upgrades ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["params"] = json.loads(item.pop("params_json") or "{}")
            item["source_run_ids"] = json.loads(item.pop("source_run_ids") or "[]")
            item["impact"] = json.loads(item.pop("impact_json") or "{}")
            out.append(item)
        return out

    @staticmethod
    def _assert_writable(conn, run_id: str) -> dict | None:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        if row["review_status"] in LOCKED_REVIEW_STATUSES:
            raise DomainError(
                "E_RUN_REVIEWED",
                f"批次 {run_id} 已复核，保持原结论，不接受重跑覆盖",
                409,
            )
        if row["superseded_by"]:
            raise DomainError(
                "E_RUN_SUPERSEDED",
                f"批次 {run_id} 已被 {row['superseded_by']} 替代，只读",
                409,
            )
        return dict(row)

    def save_run(self, run: dict, records: list[dict], candidates: list[dict],
                 matches: list[dict]) -> None:
        with self._conn() as conn:
            self._save_run(conn, run, records, candidates, matches)

    def _save_run(self, conn, run: dict, records: list[dict], candidates: list[dict],
                  matches: list[dict]) -> None:
        params_json = json.dumps(run.get("params", {}), ensure_ascii=False, sort_keys=True)
        states_json = json.dumps(run.get("input_states", {}), ensure_ascii=False)
        run_id = run["run_id"]
        existing = self._assert_writable(conn, run_id)
        conn.execute("DELETE FROM records WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM candidates WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM matches WHERE run_id = ?", (run_id,))
        # 复核与替代标记是历史结论，重跑只刷新内容，不重置状态。
        review_status = run.get("review_status") or (
            existing["review_status"] if existing else "pending_close"
        )
        reviewed_at = run.get("reviewed_at") or (existing["reviewed_at"] if existing else "")
        reviewed_by = run.get("reviewed_by") or (existing["reviewed_by"] if existing else "")
        supersedes = run.get("supersedes") or (existing["supersedes"] if existing else "")
        superseded_by = run.get("superseded_by") or (
            existing["superseded_by"] if existing else ""
        )
        conn.execute(
            """INSERT OR REPLACE INTO runs (
                run_id, created_at, rule_version, params_json, bank_sha256, ledger_sha256,
                bank_file, ledger_file, bank_bytes, ledger_bytes, bank_raw, ledger_raw,
                bank_valid, ledger_valid, bank_quar, ledger_quar, segments, status,
                input_states_json, duration_ms, review_status, reviewed_at, reviewed_by,
                supersedes, superseded_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, run["created_at"], run["rule_version"], params_json,
                run.get("bank_sha256", ""), run.get("ledger_sha256", ""),
                run.get("bank_file", ""), run.get("ledger_file", ""),
                run.get("bank_bytes", 0), run.get("ledger_bytes", 0),
                run.get("bank_raw", 0), run.get("ledger_raw", 0),
                run.get("bank_valid", 0), run.get("ledger_valid", 0),
                run.get("bank_quar", 0), run.get("ledger_quar", 0),
                run.get("segments", 0), run.get("status", "empty"),
                states_json, run.get("duration_ms", 0),
                review_status, reviewed_at, reviewed_by, supersedes, superseded_by,
            ),
        )
        conn.executemany(
            """INSERT INTO records (run_id, side, seq, row_no, txn_no, account, posted_at,
                direction, amount, fee, memo, counterparty, status, reason, flags_json,
                raw_json, raw_amount, raw_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, r["side"], r["seq"], r["row_no"], r["txn_no"], r.get("account", ""),
                    r.get("posted_at", ""), r.get("direction", 0), str(r.get("amount", "")),
                    str(r.get("fee", "")), r.get("memo", ""), r.get("counterparty", ""),
                    r.get("status", "valid"), r.get("reason", ""),
                    json.dumps(r.get("flags", []), ensure_ascii=False),
                    json.dumps(r.get("raw", []), ensure_ascii=False),
                    str(r.get("raw_amount", "")), str(r.get("raw_date", "")),
                )
                for r in records
            ],
        )
        self._insert_candidates(conn, run_id, candidates)
        self._insert_matches(conn, run_id, matches)

    def set_status(self, run_id: str, status: str) -> None:
        with self._conn() as conn:
            self._assert_writable(conn, run_id)
            conn.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id))

    # ---------- 行 ----------
    def records(self, run_id: str, side: str | None = None,
                status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM records WHERE run_id = ?"
        args: list = [run_id]
        if side:
            sql += " AND side = ?"
            args.append(side)
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY side, row_no, seq"
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["flags"] = json.loads(item.pop("flags_json") or "[]")
            item["raw"] = json.loads(item.pop("raw_json") or "[]")
            out.append(item)
        return out

    def quarantine(self, run_id: str) -> list[dict]:
        return self.records(run_id, status="quarantine")

    def candidates(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE run_id = ? ORDER BY tier, cand_id", (run_id,)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["bank_ids"] = json.loads(item.pop("bank_ids") or "[]")
            item["ledger_ids"] = json.loads(item.pop("ledger_ids") or "[]")
            out.append(item)
        return out

    def matches(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM matches WHERE run_id = ? ORDER BY tier, match_id", (run_id,)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["bank_ids"] = json.loads(item.pop("bank_ids") or "[]")
            item["ledger_ids"] = json.loads(item.pop("ledger_ids") or "[]")
            out.append(item)
        return out

    def replace_candidates(self, run_id: str, candidates: list[dict]) -> None:
        with self._conn() as conn:
            self._assert_writable(conn, run_id)
            conn.execute("DELETE FROM candidates WHERE run_id = ?", (run_id,))
            self._insert_candidates(conn, run_id, candidates)

    @staticmethod
    def _insert_candidates(conn, run_id: str, candidates: list[dict]) -> None:
        conn.executemany(
            """INSERT INTO candidates (run_id, cand_id, tier, bank_ids, ledger_ids,
                bank_sum, ledger_sum, diff, day_gap) VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, c["cand_id"], c["tier"],
                    json.dumps(c["bank_ids"], ensure_ascii=False),
                    json.dumps(c["ledger_ids"], ensure_ascii=False),
                    str(c["bank_sum"]), str(c["ledger_sum"]), str(c["diff"]), c["day_gap"],
                )
                for c in candidates
            ],
        )

    def replace_matches(self, run_id: str, matches: list[dict]) -> None:
        with self._conn() as conn:
            self._assert_writable(conn, run_id)
            conn.execute("DELETE FROM matches WHERE run_id = ?", (run_id,))
            self._insert_matches(conn, run_id, matches)

    @staticmethod
    def _insert_matches(conn, run_id: str, matches: list[dict]) -> None:
        conn.executemany(
            """INSERT INTO matches (run_id, match_id, tier, bank_ids, ledger_ids,
                bank_sum, ledger_sum, diff, day_gap, fee_alloc, fee_actual,
                bank_signed, ledger_signed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, m["match_id"], m["tier"],
                    json.dumps(m["bank_ids"], ensure_ascii=False),
                    json.dumps(m["ledger_ids"], ensure_ascii=False),
                    str(m["bank_sum"]), str(m["ledger_sum"]), str(m["diff"]), m["day_gap"],
                    str(m.get("fee_alloc", "0")), str(m.get("fee_actual", "0")),
                    str(m.get("bank_signed", "0")), str(m.get("ledger_signed", "0")),
                )
                for m in matches
            ],
        )

    # ---------- 复核 ----------
    def mark_reviewed(self, run_id: str, reviewed_by: str = "") -> dict:
        """把当前批次标记为已复核；已复核批次保持原结论，重复标记不改变内容。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise DomainError("E_NO_RUN", "批次不存在", 404)
            if row["review_status"] == "reviewed":
                return self._run_row(row)
            if row["superseded_by"]:
                raise DomainError(
                    "E_RUN_SUPERSEDED",
                    f"批次 {run_id} 已被 {row['superseded_by']} 替代，不能再标记复核",
                    409,
                )
            conn.execute(
                "UPDATE runs SET review_status = 'reviewed', reviewed_at = ?, reviewed_by = ? "
                "WHERE run_id = ?",
                (utc_now_iso(), reviewed_by or "财务共享组", run_id),
            )
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_row(row)

    # ---------- 升级记录 ----------
    def save_upgrade(self, upgrade: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO upgrades (
                    upgrade_id, created_at, target_rule_version, params_json,
                    source_run_ids, impact_json
                ) VALUES (?,?,?,?,?,?)""",
                (
                    upgrade["upgrade_id"], upgrade["created_at"],
                    upgrade["target_rule_version"],
                    json.dumps(upgrade.get("params", {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(upgrade.get("source_run_ids", []), ensure_ascii=False),
                    json.dumps(upgrade.get("impact", {}), ensure_ascii=False),
                ),
            )

    def get_upgrade(self, upgrade_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM upgrades WHERE upgrade_id = ?", (upgrade_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["source_run_ids"] = json.loads(item.pop("source_run_ids") or "[]")
        item["impact"] = json.loads(item.pop("impact_json") or "{}")
        return item

    # ---------- 元信息 ----------
    def get_meta(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def active_caliber(self) -> dict:
        """当前生效口径：未升级过时为空，导入与单步重跑都按它派生设置。"""
        raw = self.get_meta("active_caliber_json", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---------- 口径升级（单事务） ----------
    def apply_upgrade(self, plan: dict) -> dict:
        """把一批升级结果一次性写入，失败整体回滚。

        - 新批次与记录、候选、匹配、升级清单在同一个事务里落库；
        - 同一 upgrade_id 重复执行只返回首次结果，不新增记录；
        - 源批次的旧结论保持在原处，只被标记 superseded_by，不删行。
        """
        upgrade_id = plan["upgrade_id"]
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM upgrades WHERE upgrade_id = ?", (upgrade_id,)
            ).fetchone()
            if row is not None:
                item = dict(row)
                item["params"] = json.loads(item.pop("params_json") or "{}")
                item["source_run_ids"] = json.loads(item.pop("source_run_ids") or "[]")
                item["impact"] = json.loads(item.pop("impact_json") or "{}")
                return {"upgrade": item, "created": False}
            for bundle in plan["runs"]:
                run = bundle["run"]
                source_id = bundle.get("source_run_id") or ""
                existing_new = conn.execute(
                    "SELECT * FROM runs WHERE run_id = ?", (run["run_id"],)
                ).fetchone()
                if existing_new is not None:
                    # 目标口径的批次已经存在（例如另一批次先升到了同一口径）：
                    # 复用它的行与匹配，不再写一遍，避免覆盖已有匹配关系。
                    if source_id:
                        conn.execute(
                            "UPDATE runs SET superseded_by = ? "
                            "WHERE run_id = ? AND superseded_by = ''",
                            (run["run_id"], source_id),
                        )
                    continue
                if source_id:
                    # 源批次保留原结论与全部数据，只标记被哪个新批次替代。
                    conn.execute(
                        "UPDATE runs SET superseded_by = ? WHERE run_id = ? AND superseded_by = ''",
                        (run["run_id"], source_id),
                    )
                self._save_run(conn, run, bundle["records"], bundle["candidates"],
                               bundle["matches"])
            conn.execute(
                """INSERT INTO upgrades (
                    upgrade_id, created_at, target_rule_version, params_json,
                    source_run_ids, impact_json
                ) VALUES (?,?,?,?,?,?)""",
                (
                    upgrade_id, plan["created_at"], plan["target_rule_version"],
                    json.dumps(plan.get("params", {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(plan.get("source_run_ids", []), ensure_ascii=False),
                    json.dumps(plan.get("impact", {}), ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('active_rule_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (plan["target_rule_version"],),
            )
            if plan.get("active_caliber"):
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('active_caliber_json', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (json.dumps(plan["active_caliber"], ensure_ascii=False, sort_keys=True),),
                )
            row = conn.execute(
                "SELECT * FROM upgrades WHERE upgrade_id = ?", (upgrade_id,)
            ).fetchone()
        item = dict(row)
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["source_run_ids"] = json.loads(item.pop("source_run_ids") or "[]")
        item["impact"] = json.loads(item.pop("impact_json") or "{}")
        return {"upgrade": item, "created": True}
