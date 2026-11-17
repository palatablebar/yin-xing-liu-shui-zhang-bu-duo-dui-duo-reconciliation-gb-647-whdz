"""M4 候选：容差边界、窗口边界、日桶半开、子集上限与确定性排序。"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.modules.m1_ingest import service as m1_service
from app.modules.m2_contract import service as m2_service
from app.modules.m3_quality import rules
from app.modules.m4_candidates import candidate, window

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def candidates(client):
    return client.get("/api/candidates").json()["candidates"]


def find(cands, bank_ids, ledger_ids):
    bank = sorted(bank_ids)
    ledger = sorted(ledger_ids)
    return next((item for item in cands
                 if item["bank_ids"] == bank and item["ledger_ids"] == ledger), None)


def parse_ledger(settings, name):
    parsed = m1_service.read_and_map(
        settings, "ledger", name, (FIXTURES / name).read_bytes(),
        m2_service.alias_index("ledger"),
    )
    return rules.build_records("ledger", parsed["records"], settings)


def test_one_to_one_candidate_generated(client, demo):
    item = find(candidates(client), ["000001"], ["V001"])
    assert item is not None
    assert item["tier"] == 1
    assert item["diff"] == "0.00"


def test_tolerance_boundary_included(client, demo):
    item = find(candidates(client), ["000025"], ["V018"])
    assert item is not None
    assert item["diff"] == "0.02"


def test_tolerance_beyond_limit_excluded(client, demo):
    assert find(candidates(client), ["000004"], ["V012"]) is None


def test_window_boundary_three_days_included(settings):
    # TRAP-23：日期差正好 3 天算窗口内
    records = parse_ledger(settings, "window_edge_ledger.csv")
    zone = window.tzinfo(settings.tz_name)
    anchor = window.parse_instant("2026-03-31T02:00:00+00:00")
    gaps = {
        record["txn_no"]: window.day_gap(anchor, window.parse_instant(record["posted_at"]), zone)
        for record in records
    }
    assert gaps == {"W3A": 3, "W3B": 3, "W4": 4}
    w3a = next(record for record in records if record["txn_no"] == "W3A")
    assert window.in_window(anchor, window.parse_instant(w3a["posted_at"]), 3, zone)


def test_window_four_days_excluded(settings):
    # TRAP-23：第 4 天不进入窗口
    records = parse_ledger(settings, "window_edge_ledger.csv")
    zone = window.tzinfo(settings.tz_name)
    anchor = window.parse_instant("2026-03-31T02:00:00+00:00")
    w4 = next(record for record in records if record["txn_no"] == "W4")
    assert not window.in_window(anchor, window.parse_instant(w4["posted_at"]), 3, zone)


def test_day_bucket_is_half_open(settings):
    # TRAP-23：本地日桶左闭右开
    zone = window.tzinfo(settings.tz_name)
    late = window.parse_instant("2026-03-03T23:59:59+08:00")
    early = window.parse_instant("2026-03-04T00:00:00+08:00")
    start, end = window.day_bucket(late, zone)
    assert window.in_bucket(late, start, end)
    assert not window.in_bucket(early, start, end)
    next_start, _ = window.day_bucket(early, zone)
    assert start < next_start


def test_one_to_many_subset_candidate(client, demo):
    item = find(candidates(client), ["000002"], ["V002", "V003"])
    assert item is not None
    assert item["tier"] == 2
    assert Decimal(item["ledger_sum"]) == Decimal("3000.00")


def test_many_to_one_subset_bounded_to_four(client, demo):
    items = candidates(client)
    item = find(items, ["000016", "000017", "000018", "000019"], ["V011"])
    assert item is not None
    assert item["tier"] == 3 and item["bank_sum"] == "400.50"
    assert not any("V012" in candidate["ledger_ids"] for candidate in items)


def test_fee_not_included_in_candidate_amount(client, demo):
    item = find(candidates(client), ["000001"], ["V001"])
    assert item["bank_sum"] == "12000.00"
    assert Decimal(item["bank_sum"]) + Decimal("5.00") != Decimal("12000.00")


def test_candidate_order_deterministic(client, demo):
    store = client.app.state.store
    records = store.records(demo["run_id"])
    first = candidate.build(records, client.app.state.settings)
    second = candidate.build(list(reversed(records)), client.app.state.settings)
    assert [item["cand_id"] for item in first] == [item["cand_id"] for item in second]
    keys = [(item["tier"], Decimal(item["diff"]), item["day_gap"]) for item in first]
    assert keys == sorted(keys)
