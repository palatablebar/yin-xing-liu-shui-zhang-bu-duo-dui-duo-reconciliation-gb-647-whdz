"""M5 求解：层级计数、Decimal 合计、手续费守恒、确定性择一与顺序无关。"""
from decimal import Decimal
from pathlib import Path

from app.modules.m1_ingest import service as m1_service
from app.modules.m2_contract import service as m2_service
from app.modules.m3_quality import rules
from app.modules.m4_candidates import candidate
from app.modules.m5_matching import fees, solve

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def groups(client):
    return client.get("/api/matches").json()["groups"]


def parse_ledger(settings, name):
    parsed = m1_service.read_and_map(
        settings, "ledger", name, (FIXTURES / name).read_bytes(),
        m2_service.alias_index("ledger"),
    )
    return rules.build_records("ledger", parsed["records"], settings)


def bank_record(txn, amount, posted, direction=-1):
    return {
        "side": "bank",
        "seq": 0,
        "row_no": 1,
        "txn_no": txn,
        "account": "6222-0012",
        "posted_at": posted,
        "direction": direction,
        "amount": amount,
        "fee": "0.00",
        "memo": "",
        "counterparty": "",
        "status": "valid",
        "reason": "",
        "flags": [],
        "raw": [],
    }


def test_match_group_counts_by_tier(client, demo):
    data = client.get("/api/matches").json()
    assert data["count"] == 11
    assert data["tiers"] == {"1": 7, "2": 2, "3": 2}


def test_bank_signed_total_matches_decimal_sum(client, demo):
    # TRAP-10：float 累加会差一分
    total = Decimal(demo["totals"]["bank_matched"])
    summed = sum((Decimal(group["bank_signed"]) for group in groups(client)), Decimal("0.00"))
    assert summed == total == Decimal("-245929.26")
    assert 0.1 + 0.2 != 0.3


def test_fee_allocation_sums_to_actual(client, demo):
    # TRAP-24：分摊合计必须等于实际手续费合计
    data = client.get("/api/matches").json()
    allocated = sum((Decimal(group["fee_alloc"]) for group in data["groups"]), Decimal("0.00"))
    actual = sum((Decimal(group["fee_actual"]) for group in data["groups"]), Decimal("0.00"))
    assert allocated == actual == Decimal("22.31")
    assert data["fee_alloc_total"] == data["fee_actual_total"] == "22.31"


def test_fee_allocation_order_independent(settings):
    # TRAP-24：输入顺序变化不影响每组分摊额
    weights = [Decimal("12000"), Decimal("800"), Decimal("499.99"), Decimal("1000.02")]
    keys = ["m-a", "m-b", "m-c", "m-d"]
    total = Decimal("0.07")
    first = fees.allocate(total, weights, settings.fee_quantum, keys)
    order = [3, 1, 0, 2]
    shuffled = fees.allocate(
        total, [weights[index] for index in order], settings.fee_quantum,
        [keys[index] for index in order],
    )
    mapping = {keys[order[position]]: shuffled[position] for position in range(len(order))}
    assert [mapping[key] for key in keys] == first
    assert sum(first, Decimal("0")) == total


def test_choose_disjoint_never_reuses_rows(client, demo):
    chosen = groups(client)
    bank_ids = [key for group in chosen for key in group["bank_ids"]]
    ledger_ids = [key for group in chosen for key in group["ledger_ids"]]
    assert len(bank_ids) == len(set(bank_ids)) == 15
    assert len(ledger_ids) == len(set(ledger_ids)) == 14


def test_tie_break_prefers_smaller_voucher(settings):
    records = parse_ledger(settings, "tie_break_ledger.csv")
    records.append(bank_record("B-TIE", "1234.00", "2026-03-10T01:00:00+00:00"))
    candidates = candidate.build(records, settings)
    result = solve.solve(candidates, records, settings)
    assert len(result) == 1
    assert result[0]["ledger_ids"] == ["V800"]


def test_tie_break_prefers_closer_date(settings):
    records = [
        bank_record("B-NEAR", "900.00", "2026-03-10T02:00:00+00:00"),
        {
            "side": "ledger", "seq": 0, "row_no": 2, "txn_no": "V-FAR",
            "account": "6222-0012", "posted_at": "2026-03-12T02:00:00+00:00",
            "direction": -1, "amount": "900.00", "fee": "0.00", "memo": "",
            "counterparty": "", "status": "valid", "reason": "", "flags": [], "raw": [],
        },
        {
            "side": "ledger", "seq": 1, "row_no": 3, "txn_no": "V-NEAR",
            "account": "6222-0012", "posted_at": "2026-03-10T03:00:00+00:00",
            "direction": -1, "amount": "900.00", "fee": "0.00", "memo": "",
            "counterparty": "", "status": "valid", "reason": "", "flags": [], "raw": [],
        },
    ]
    candidates = candidate.build(records, settings)
    result = solve.solve(candidates, records, settings)
    assert len(result) == 1
    assert result[0]["ledger_ids"] == ["V-NEAR"]
    assert result[0]["day_gap"] == 0


def test_result_independent_of_candidate_order(client, demo):
    # TRAP-19：候选顺序反转后匹配组不变
    store = client.app.state.store
    records = store.records(demo["run_id"])
    candidates = store.candidates(demo["run_id"])
    forward = solve.solve(candidates, records, client.app.state.settings)
    backward = solve.solve(list(reversed(candidates)), records, client.app.state.settings)
    assert [item["match_id"] for item in forward] == [item["match_id"] for item in backward]


def test_fee_actual_matches_member_rows(client, demo):
    group = next(item for item in groups(client) if item["bank_ids"] == ["000001"])
    assert group["fee_actual"] == "5.00"
    assert group["fee_alloc"] == "0.98"


def test_unmatched_counts_after_solve(client, demo):
    counts = demo["counts"]
    assert counts["bank_unmatched_rows"] == 7
    assert counts["ledger_unmatched_rows"] == 5
    assert counts["bank_matched_rows"] + counts["bank_unmatched_rows"] == counts["bank_valid"]
    assert counts["ledger_matched_rows"] + counts["ledger_unmatched_rows"] == counts["ledger_valid"]
