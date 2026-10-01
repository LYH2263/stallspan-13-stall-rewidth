"""分配 API：本轮临时抬优先的端到端场景。

每个测试用独立内存库 + 种子数据；通过 dependency_overrides 换掉 get_db，
不触碰全局引擎（也不需要 postgres）。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import AllocationRun, Vendor
from app.services.seed import seed_if_empty

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=engine)


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    seed_if_empty(db)
    db.close()
    yield


def truck_id() -> int:
    db = Session()
    vid = db.scalar(select(Vendor.id).where(Vendor.name == "巨型舞台车"))
    db.close()
    return vid


def run_count() -> int:
    db = Session()
    n = db.scalar(select(func.count()).select_from(AllocationRun))
    db.close()
    return n


def registered_priority(vid: int) -> int:
    db = Session()
    pri = db.scalar(select(Vendor.priority).where(Vendor.id == vid))
    db.close()
    return pri


def names(rows):
    return [r["vendor_name"] for r in rows]


def test_unboosted_run_matches_baseline_and_truck_rejected():
    """未抬时与绿仓一致：按登记优先落位，巨型舞台车（登记 9）放不下。"""
    res = client.post("/api/allocate/run?segment_id=1")
    assert res.status_code == 200
    data = res.json()
    assert data["committed"] is True and data["id"] is not None
    assert data["boosts"] == []
    assert "巨型舞台车" in names(data["rejected"])
    assert "巨型舞台车" not in names(data["placements"])
    # 落位次序按登记优先（平档按 id）
    eff = [p["effective_priority"] for p in data["placements"]]
    assert eff == sorted(eff)
    for row in data["placements"] + data["rejected"]:
        assert row["temp_priority"] is None
        assert row["effective_priority"] == row["priority"]


def test_boost_truck_to_1_and_confirm_enters_map():
    """种子验收：巨型舞台车本轮抬到 1 再确认 → 进图；登记优先不被写回。"""
    tid = truck_id()
    res = client.post("/api/allocate/run?segment_id=1",
                      json={"boosts": [{"vendor_id": tid, "priority": 1}], "commit": True})
    assert res.status_code == 200
    data = res.json()
    assert data["committed"] is True and data["id"] is not None
    assert data["boosts"] == [{"vendor_id": tid, "priority": 1}]
    placed = {p["vendor_name"]: p for p in data["placements"]}
    assert "巨型舞台车" in placed
    # 成功摊不得写进放不下
    assert "巨型舞台车" not in names(data["rejected"])
    assert not ({p["vendor_id"] for p in data["placements"]}
                & {r["vendor_id"] for r in data["rejected"]})
    # 三套数：登记 9、临时 1、生效 1
    truck = placed["巨型舞台车"]
    assert (truck["priority"], truck["temp_priority"], truck["effective_priority"]) == (9, 1, 1)
    # 登记优先不得写回
    assert registered_priority(tid) == 9
    vendors = client.get("/api/vendors").json()
    assert next(v for v in vendors if v["id"] == tid)["priority"] == 9
    # latest 能对照本轮临时与登记两套数
    latest = client.get("/api/allocate/latest?segment_id=1").json()
    assert latest["id"] == data["id"]
    assert latest["boosts"] == [{"vendor_id": tid, "priority": 1}]
    truck_latest = next(p for p in latest["placements"] if p["vendor_id"] == tid)
    assert (truck_latest["priority"], truck_latest["temp_priority"]) == (9, 1)


def test_boost_makes_truck_more_left_than_unboosted():
    """抬到 1 后比未抬更容易进图：未抬进不了图，抬后进图。"""
    tid = truck_id()
    before = client.post("/api/allocate/run?segment_id=1", json={}).json()
    assert "巨型舞台车" in names(before["rejected"])
    after = client.post("/api/allocate/run?segment_id=1",
                        json={"boosts": [{"vendor_id": tid, "priority": 1}]}).json()
    assert "巨型舞台车" in names(after["placements"])


def test_clear_boost_returns_to_registered_disadvantage():
    """清除临时后再分：回到登记优先 9 的劣势，禁止继续吃临时缓存。"""
    tid = truck_id()
    boosted = client.post("/api/allocate/run?segment_id=1",
                          json={"boosts": [{"vendor_id": tid, "priority": 1}]}).json()
    assert "巨型舞台车" in names(boosted["placements"])
    cleared = client.post("/api/allocate/run?segment_id=1", json={"boosts": []}).json()
    assert cleared["boosts"] == []
    assert "巨型舞台车" in names(cleared["rejected"])
    # 再跑一次不带任何参数（本轮结束后的普通分配）也一样
    plain = client.post("/api/allocate/run?segment_id=1").json()
    assert "巨型舞台车" in names(plain["rejected"])


@pytest.mark.parametrize("bad_boost", [
    {"vendor_id": "TID", "priority": 0},      # 下界外
    {"vendor_id": "TID", "priority": 10},     # 上界外
    {"vendor_id": "TID", "priority": -3},
    {"vendor_id": "TID", "priority": 1.5},    # 非整数
    {"vendor_id": "TID", "priority": "1"},    # 字符串
    {"vendor_id": "TID", "priority": True},   # 布尔不是合法优先值
    {"vendor_id": "TID", "priority": None},
    {"vendor_id": 99999, "priority": 1},      # 不存在的摊
    {"vendor_id": "TID"},                     # 缺字段
    {"priority": 1},                          # 缺摊主
])
def test_invalid_boost_rejects_whole_round(bad_boost):
    """非法临时值整次拒绝：登记、图（run 记录）、放不下均不变，禁止半成功。"""
    tid = truck_id()
    item = {k: (tid if v == "TID" else v) for k, v in bad_boost.items()}
    before_runs = run_count()
    res = client.post("/api/allocate/run?segment_id=1", json={"boosts": [item]})
    assert res.status_code == 422
    assert run_count() == before_runs          # 图不变（无新入库 run）
    assert registered_priority(tid) == 9       # 登记不变


def test_mixed_valid_and_invalid_rejects_all():
    """一条非法即整次拒绝：合法条目也不许半成功。"""
    tid = truck_id()
    before_runs = run_count()
    res = client.post("/api/allocate/run?segment_id=1", json={
        "boosts": [{"vendor_id": tid, "priority": 1}, {"vendor_id": tid, "priority": 7}],
    })
    assert res.status_code == 422              # 同一摊重复抬也整次拒绝
    assert run_count() == before_runs
    res = client.post("/api/allocate/run?segment_id=1", json={
        "boosts": [{"vendor_id": tid, "priority": 1}, {"vendor_id": 99999, "priority": 2}],
    })
    assert res.status_code == 422
    assert run_count() == before_runs
    assert registered_priority(tid) == 9


def test_boosts_must_be_a_list():
    before_runs = run_count()
    res = client.post("/api/allocate/run?segment_id=1", json={"boosts": {"1": 2}})
    assert res.status_code == 422
    assert run_count() == before_runs


def test_preview_does_not_commit_and_is_not_disguised():
    """现算预览：结果照算但不落库，响应不得伪装成已入库。"""
    tid = truck_id()
    before_runs = run_count()
    res = client.post("/api/allocate/run?segment_id=1",
                      json={"boosts": [{"vendor_id": tid, "priority": 1}], "commit": False})
    assert res.status_code == 200
    data = res.json()
    assert data["committed"] is False
    assert data["id"] is None                  # 未入库不得给 run id
    assert "巨型舞台车" in names(data["placements"])
    assert run_count() == before_runs          # 预览不写库
    # 最近一次入库仍是未抬的那一份（预览不污染图与放不下）
    latest = client.get("/api/allocate/latest?segment_id=1").json()
    assert latest["boosts"] == []
    assert "巨型舞台车" in names(latest["rejected"])


def test_commit_must_be_bool():
    before_runs = run_count()
    res = client.post("/api/allocate/run?segment_id=1", json={"commit": "yes"})
    assert res.status_code == 422
    assert run_count() == before_runs
