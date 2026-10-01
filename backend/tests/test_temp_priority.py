from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.first_fit_engine import (
    PriorityError,
    allocate_first_fit,
    apply_temp_priorities,
    result_to_dict,
)
from app.services.round_builder import build_round

SEG = SimpleNamespace(id=1, name="东街段", width_m=30.0)
PILLARS = [
    {"position_m": 12.25, "thickness_m": 0.5},
    {"position_m": 20.0, "thickness_m": 0.5},
]
# 与 seed.py 一致：六家小摊 + 巨型舞台车（12m，登记优先 9）
VENDORS = [
    {"id": 1, "name": "阿强烧烤", "stall_width_m": 4.0, "priority": 2},
    {"id": 2, "name": "林记糖水", "stall_width_m": 3.0, "priority": 2},
    {"id": 3, "name": "老周水果", "stall_width_m": 5.0, "priority": 2},
    {"id": 4, "name": "小美饰品", "stall_width_m": 2.5, "priority": 2},
    {"id": 5, "name": "大碗面", "stall_width_m": 6.0, "priority": 2},
    {"id": 6, "name": "手作皮具", "stall_width_m": 3.5, "priority": 3},
    {"id": 7, "name": "巨型舞台车", "stall_width_m": 12.0, "priority": 9},
]
TRUCK = 7


def _ids(items):
    return {x.vendor_id for x in items}


def test_unboosted_truck_is_rejected():
    r = allocate_first_fit(SEG.width_m, VENDORS, PILLARS)
    assert TRUCK in _ids(r.rejected)
    assert TRUCK not in _ids(r.placements)
    assert len(r.placements) + len(r.rejected) == len(VENDORS)


def test_boost_truck_to_one_places_it_leftmost():
    round_data = build_round(SEG, PILLARS, VENDORS, [{"vendor_id": TRUCK, "temp_priority": 1}],
                             confirmed=False)
    placed = {p["vendor_id"]: p for p in round_data["placements"]}
    rejected_ids = {r["vendor_id"] for r in round_data["rejected"]}
    assert TRUCK in placed
    assert TRUCK not in rejected_ids
    assert placed[TRUCK]["start_m"] == 0.0 and placed[TRUCK]["end_m"] == 12.0
    # 抬升把后选位的两家挤出，总数守恒
    assert len(round_data["placements"]) + len(round_data["rejected"]) == len(VENDORS)
    assert rejected_ids == {5, 6}


def test_boost_never_mutates_registered_priority():
    snapshot = [dict(v) for v in VENDORS]
    apply_temp_priorities(VENDORS, {TRUCK: 1})
    assert VENDORS == snapshot  # 入参逐字不变，登记优先不被写回
    assert next(v for v in VENDORS if v["id"] == TRUCK)["priority"] == 9


@pytest.mark.parametrize("bad", [0, 10, -1, True, False, 5.0, "5", 1.0])
def test_illegal_temp_values_rejected(bad):
    with pytest.raises(PriorityError):
        apply_temp_priorities(VENDORS, {TRUCK: bad})


def test_unknown_vendor_rejected():
    with pytest.raises(PriorityError):
        apply_temp_priorities(VENDORS, {999: 1})


def test_empty_overrides_equals_baseline():
    base = result_to_dict(allocate_first_fit(SEG.width_m, VENDORS, PILLARS))
    round_data = build_round(SEG, PILLARS, VENDORS, [], confirmed=False)
    # 几何结果逐值一致；新增的三优先字段只是加法元数据
    core_p = lambda xs: [(x.get("vendor_id"), x.get("start_m"), x.get("end_m"), x.get("width_m")) for x in xs]
    core_r = lambda xs: [(x.get("vendor_id"), x.get("width_m"), x.get("reason")) for x in xs]
    assert core_p(round_data["placements"]) == core_p(base["placements"])
    assert core_r(round_data["rejected"]) == core_r(base["rejected"])
    assert round_data["free_spans"] == base["free_spans"]


def test_echoed_priority_fields():
    round_data = build_round(SEG, PILLARS, VENDORS, [{"vendor_id": TRUCK, "temp_priority": 1}],
                             confirmed=True, run_id=3,
                             created_at=datetime(2026, 10, 1))
    by_id = {v["vendor_id"]: v for v in round_data["vendors"]}
    assert by_id[TRUCK]["registered_priority"] == 9
    assert by_id[TRUCK]["temp_priority"] == 1
    assert by_id[TRUCK]["effective_priority"] == 1
    assert by_id[TRUCK]["status"] == "placed"
    assert by_id[1]["temp_priority"] is None
    assert by_id[1]["effective_priority"] == 2
    assert round_data["confirmed"] is True
    assert round_data["id"] == 3
    assert round_data["round_token"] == "3"


def test_preview_round_token_is_ephemeral():
    a = build_round(SEG, PILLARS, VENDORS, [], confirmed=False)
    b = build_round(SEG, PILLARS, VENDORS, [], confirmed=False)
    assert a["id"] is None and a["confirmed"] is False
    assert a["round_token"].startswith("preview-")
    assert a["round_token"] != b["round_token"]
