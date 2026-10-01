import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AllocationRun, Pillar, Segment, Vendor
from app.services.first_fit_engine import PriorityError
from app.services.round_builder import build_round

router = APIRouter(prefix="/allocate", tags=["allocate"])


class BoostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: StrictInt = Field(gt=0)
    temp_priority: StrictInt = Field(ge=1, le=9)


class AllocateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: int = 1
    boosts: list[BoostIn] = Field(default_factory=list)


def _load_inputs(segment_id: int, db: Session):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    pillars = [{"position_m": p.position_m, "thickness_m": p.thickness_m}
               for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)
                                   .order_by(Pillar.position_m, Pillar.id)).all()]
    vendors = [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m, "priority": v.priority}
               for v in db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)
                                   .order_by(Vendor.id)).all()]
    return seg, pillars, vendors


def _compute(segment_id: int, boosts_in: list[BoostIn], db: Session):
    seg, pillars, vendors = _load_inputs(segment_id, db)
    ids = [b.vendor_id for b in boosts_in]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "同一摊主出现了多个本轮临时优先，整次抬升已拒绝")
    boosts = [{"vendor_id": b.vendor_id, "temp_priority": b.temp_priority} for b in boosts_in]
    try:
        return build_round(seg, pillars, vendors, boosts, confirmed=False)
    except PriorityError as exc:
        raise HTTPException(400, str(exc))


@router.post("/preview")
def preview_allocate(payload: AllocateRequest | None = None,
                     segment_id: int = 1, db: Session = Depends(get_db)):
    """现算：只算不写，本轮临时优先不入库、不写回登记。"""
    sid = payload.segment_id if payload else segment_id
    boosts = payload.boosts if payload else []
    return _compute(sid, boosts, db)


@router.post("/run")
def run_allocate(payload: AllocateRequest | None = None,
                 segment_id: int = 1, db: Session = Depends(get_db)):
    """确认：先纯算（非法整次拒绝、零写入），通过后唯一一次入库。"""
    sid = payload.segment_id if payload else segment_id
    boosts = payload.boosts if payload else []
    round_data = _compute(sid, boosts, db)

    created_at = datetime.utcnow()
    run = AllocationRun(segment_id=sid, created_at=created_at, result_json="{}")
    db.add(run)
    db.flush()  # 取 run.id；此时仍可回滚
    round_data["confirmed"] = True
    round_data["id"] = run.id
    round_data["created_at"] = created_at.isoformat()
    round_data["round_token"] = str(run.id)
    run.result_json = json.dumps(round_data, ensure_ascii=False)
    db.commit()
    db.refresh(run)
    return dict(round_data)


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    run = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                     .order_by(AllocationRun.id.desc())).first()
    if not run:
        # 不再隐式触发入库；无确认记录即 404。
        raise HTTPException(404, "尚未确认分配")
    data = json.loads(run.result_json)
    return _normalize_legacy(run.id, data)


def _normalize_legacy(run_id: int, data: dict) -> dict:
    """容忍旧 result_json（无本轮新增字段）：补默认，不回写旧行。"""
    data.setdefault("id", run_id)
    data.setdefault("confirmed", True)
    data.setdefault("round_token", str(run_id))
    data.setdefault("boosts", [])
    data.setdefault("created_at", None)
    if "vendors" not in data:
        vendors = []
        for p in data.get("placements", []):
            vendors.append(_legacy_vendor(p, "placed"))
        for r in data.get("rejected", []):
            vendors.append(_legacy_vendor(r, "rejected"))
        data["vendors"] = vendors
    for p in data.get("placements", []):
        p.setdefault("registered_priority", None)
        p.setdefault("temp_priority", None)
        p.setdefault("effective_priority", None)
    for r in data.get("rejected", []):
        r.setdefault("registered_priority", None)
        r.setdefault("temp_priority", None)
        r.setdefault("effective_priority", None)
    return data


def _legacy_vendor(item: dict, status: str) -> dict:
    return {
        "vendor_id": item.get("vendor_id"),
        "vendor_name": item.get("vendor_name"),
        "width_m": item.get("width_m"),
        "registered_priority": item.get("registered_priority"),
        "temp_priority": item.get("temp_priority"),
        "effective_priority": item.get("effective_priority"),
        "status": status,
    }
