from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import AllocationRun, MarketDay, Pillar, Segment, Vendor


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import Session
    db = Session(engine)

    day = MarketDay(name="周末夜市", day=date(2026, 9, 20))
    db.add(day); db.flush()
    seg = Segment(market_day_id=day.id, name="东街段", width_m=30.0)
    db.add(seg); db.flush()
    db.add(Pillar(segment_id=seg.id, position_m=12.25, thickness_m=0.5, label="灯柱A"))
    db.add(Pillar(segment_id=seg.id, position_m=20.0, thickness_m=0.5, label="灯柱B"))
    for name, wdt, pri in [
        ("阿强烧烤", 4.0, 2), ("林记糖水", 3.0, 2), ("老周水果", 5.0, 2),
        ("小美饰品", 2.5, 2), ("大碗面", 6.0, 2), ("手作皮具", 3.5, 3),
        ("巨型舞台车", 12.0, 9),
    ]:
        db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
    db.commit()

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    # 不用 with 上下文，避免触发连真实 Postgres 的 lifespan
    client = TestClient(app)
    yield client, db
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _truck_id(db):
    return db.scalar(select(Vendor.id).where(Vendor.name == "巨型舞台车"))


def _rejected_ids(payload):
    return {r["vendor_id"] for r in payload["rejected"]}


def test_latest_404_when_none_and_no_implicit_persist(ctx):
    client, db = ctx
    r = client.get("/api/allocate/latest?segment_id=1")
    assert r.status_code == 404
    assert db.scalar(select(func.count()).select_from(AllocationRun)) == 0


def test_preview_does_not_persist(ctx):
    client, _ = ctx
    r = client.post("/api/allocate/preview", json={"segment_id": 1, "boosts": []})
    assert r.status_code == 200
    p = r.json()
    assert p["confirmed"] is False and p["id"] is None
    assert client.get("/api/allocate/latest?segment_id=1").status_code == 404


def test_run_persists_confirmed_round(ctx):
    client, db = ctx
    r = client.post("/api/allocate/run", json={"segment_id": 1, "boosts": []})
    assert r.status_code == 200
    p = r.json()
    assert p["confirmed"] is True and p["id"] == 1 and p["round_token"] == "1"
    assert db.scalars(select(AllocationRun)).all() and len(db.scalars(select(AllocationRun)).all()) == 1


def test_illegal_boosts_whole_request_rejected_no_half_success(ctx):
    client, db = ctx
    truck = _truck_id(db)
    # 先有一次合法入库
    client.post("/api/allocate/run", json={"segment_id": 1, "boosts": []})
    bad_bodies = [
        {"boosts": [{"vendor_id": truck, "temp_priority": 0}]},
        {"boosts": [{"vendor_id": truck, "temp_priority": 10}]},
        {"boosts": [{"vendor_id": 999, "temp_priority": 1}]},
        {"boosts": [{"vendor_id": truck, "temp_priority": True}]},
        {"boosts": [{"vendor_id": truck, "temp_priority": 5.0}]},
        {"boosts": [{"vendor_id": truck, "temp_priority": "5"}]},
        {"boosts": [{"vendor_id": 1, "temp_priority": 1}, {"vendor_id": 1, "temp_priority": 2}]},
        {"boosts": [{"vendor_id": truck, "temp_priority": 1}], "extra": 1},
    ]
    for body in bad_bodies:
        rr = client.post("/api/allocate/run", json={"segment_id": 1, **body})
        assert rr.status_code == 400, body
    # 全部非法后仍只有最初那一行，latest 未变，且是未抬结果
    runs = db.scalars(select(AllocationRun).order_by(AllocationRun.id)).all()
    assert len(runs) == 1
    latest = client.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == 1
    assert _truck_id(db) in _rejected_ids(latest)


def test_boost_preview_then_run_keeps_registered_priority(ctx):
    client, db = ctx
    truck = _truck_id(db)
    pv = client.post("/api/allocate/preview",
                     json={"segment_id": 1, "boosts": [{"vendor_id": truck, "temp_priority": 1}]})
    assert pv.status_code == 200
    p = pv.json()
    placed = {x["vendor_id"]: x for x in p["placements"]}
    assert truck in placed and placed[truck]["start_m"] == 0.0
    by_id = {v["vendor_id"]: v for v in p["vendors"]}
    assert by_id[truck]["registered_priority"] == 9
    assert by_id[truck]["temp_priority"] == 1
    assert by_id[truck]["effective_priority"] == 1
    # 预览仍未入库
    assert client.get("/api/allocate/latest?segment_id=1").status_code == 404

    run = client.post("/api/allocate/run",
                      json={"segment_id": 1, "boosts": [{"vendor_id": truck, "temp_priority": 1}]})
    assert run.status_code == 200
    # 登记优先绝不被写回
    assert db.get(Vendor, truck).priority == 9
    vendors = {v["id"]: v for v in client.get("/api/vendors").json()}
    assert vendors[truck]["priority"] == 9


def test_clear_boost_returns_truck_to_rejected(ctx):
    client, db = ctx
    truck = _truck_id(db)
    client.post("/api/allocate/run", json={"boosts": [{"vendor_id": truck, "temp_priority": 1}]})
    client.post("/api/allocate/run", json={"boosts": []})
    latest = client.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == 2
    assert truck in _rejected_ids(latest)
    by_id = {v["vendor_id"]: v for v in latest["vendors"]}
    assert by_id[truck]["temp_priority"] is None and by_id[truck]["effective_priority"] == 9
