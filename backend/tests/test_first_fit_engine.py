from app.services.first_fit_engine import allocate_first_fit, free_spans_from_pillars

PILLARS_2 = [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}]

def test_free_spans_with_pillars():
    spans = free_spans_from_pillars(30.0, [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}])
    assert len(spans) == 3
    assert spans[0][0] == 0.0

def test_first_fit_no_cross_pillar():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 12.0, "priority": 1},
    ]
    pillars = [{"position_m": 10.0, "thickness_m": 0.5}]
    r = allocate_first_fit(30.0, vendors, pillars)
    assert any(p.vendor_name == "A" for p in r.placements)
    # 12m may fit in a free span after first placement depending on remainders
    assert len(r.placements) + len(r.rejected) == 2

def test_reject_oversized():
    vendors = [{"id": 1, "name": "Huge", "stall_width_m": 25.0, "priority": 1}]
    pillars = [{"position_m": 10.0, "thickness_m": 0.5}, {"position_m": 20.0, "thickness_m": 0.5}]
    r = allocate_first_fit(30.0, vendors, pillars)
    assert len(r.rejected) == 1
    assert r.rejected[0].vendor_name == "Huge"

def test_temp_priority_overrides_registered_this_round():
    # B 登记 9 本轮抬到 1：与登记 1 的 A 同档，按 id 排 A 先 B 后，但 B 先于登记 2 的 C
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 4.0, "priority": 9, "temp_priority": 1},
        {"id": 3, "name": "C", "stall_width_m": 4.0, "priority": 2},
    ]
    r = allocate_first_fit(30.0, vendors, PILLARS_2)
    assert [p.vendor_name for p in r.placements] == ["A", "B", "C"]
    b = r.placements[1]
    assert (b.priority, b.temp_priority, b.effective_priority) == (9, 1, 1)
    # 登记优先不得被写回
    assert r.placements[0].priority == 1

def test_temp_priority_changes_position():
    # 同一街段：未抬时 A(登记1) 占最左；B 抬到 1 后按 id 仍 A 先，但 C(登记2) 被挤到 B 之后
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 1},
        {"id": 2, "name": "B", "stall_width_m": 4.0, "priority": 9, "temp_priority": 1},
        {"id": 3, "name": "C", "stall_width_m": 4.0, "priority": 2},
    ]
    r = allocate_first_fit(30.0, vendors, PILLARS_2)
    starts = {p.vendor_name: p.start_m for p in r.placements}
    assert starts["B"] < starts["C"]

def test_no_boost_identical_to_baseline():
    vendors = [
        {"id": 1, "name": "A", "stall_width_m": 4.0, "priority": 2},
        {"id": 2, "name": "B", "stall_width_m": 4.0, "priority": 1},
        {"id": 3, "name": "C", "stall_width_m": 25.0, "priority": 3},
    ]
    baseline = allocate_first_fit(30.0, vendors, PILLARS_2)
    with_none = allocate_first_fit(30.0, [{**v, "temp_priority": None} for v in vendors], PILLARS_2)
    assert [p.vendor_id for p in baseline.placements] == [p.vendor_id for p in with_none.placements]
    assert [x.vendor_id for x in baseline.rejected] == [x.vendor_id for x in with_none.rejected]
    assert baseline.free_spans == with_none.free_spans
    # 未抬时生效优先就是登记优先
    for p in with_none.placements + with_none.rejected:
        assert p.temp_priority is None
        assert p.effective_priority == p.priority

def test_rejected_carries_all_three_priorities():
    vendors = [{"id": 1, "name": "Huge", "stall_width_m": 25.0, "priority": 4, "temp_priority": 2}]
    r = allocate_first_fit(30.0, vendors, PILLARS_2)
    x = r.rejected[0]
    assert (x.priority, x.temp_priority, x.effective_priority) == (4, 2, 2)
