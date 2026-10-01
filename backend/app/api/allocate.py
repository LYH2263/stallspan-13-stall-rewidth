import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AllocationRun, Pillar, Segment, Vendor
from app.services.first_fit_engine import allocate_first_fit, result_to_dict

router = APIRouter(prefix="/allocate", tags=["allocate"])


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_boosts(raw: Any, valid_vendor_ids: set[int]) -> dict[int, int]:
    """校验本轮临时优先表。任何一条非法（非 1-9、摊主不存在、重复、类型错）
    都整次拒绝——调用方保证在校验通过前不做任何写入，禁止半成功。"""
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise HTTPException(422, "临时优先表必须是数组，整次抬优先拒绝")
    boosts: dict[int, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(422, "临时优先条目必须是对象，整次抬优先拒绝")
        vid, pri = item.get("vendor_id"), item.get("priority")
        if not _is_int(vid):
            raise HTTPException(422, "临时优先的摊主编号必须是整数，整次抬优先拒绝")
        if vid not in valid_vendor_ids:
            raise HTTPException(422, f"摊主 {vid} 不存在于本集市日，整次抬优先拒绝")
        if not _is_int(pri) or not 1 <= pri <= 9:
            raise HTTPException(422, f"摊主 {vid} 的临时优先必须是 1 到 9 的整数，整次抬优先拒绝")
        if vid in boosts:
            raise HTTPException(422, f"摊主 {vid} 的临时优先重复，整次抬优先拒绝")
        boosts[vid] = pri
    return boosts


@router.post("/run")
def run_allocate(segment_id: int = 1,
                 payload: dict[str, Any] | None = Body(default=None),
                 db: Session = Depends(get_db)):
    seg = db.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "街段不存在")
    payload = payload or {}
    commit = payload.get("commit", True)
    if not isinstance(commit, bool):
        raise HTTPException(422, "commit 必须是布尔值")
    pillars = [{"position_m": p.position_m, "thickness_m": p.thickness_m}
               for p in db.scalars(select(Pillar).where(Pillar.segment_id == segment_id)).all()]
    vendor_rows = db.scalars(select(Vendor).where(Vendor.market_day_id == seg.market_day_id)).all()
    # 先校验后计算再入库：校验不过整次拒绝，登记、图、放不下均不变
    boosts = parse_boosts(payload.get("boosts"), {v.id for v in vendor_rows})
    vendors = [{"id": v.id, "name": v.name, "stall_width_m": v.stall_width_m,
                "priority": v.priority, "temp_priority": boosts.get(v.id)}
               for v in vendor_rows]
    result = result_to_dict(allocate_first_fit(seg.width_m, vendors, pillars))
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    result["boosts"] = [{"vendor_id": vid, "priority": pri} for vid, pri in sorted(boosts.items())]
    result["committed"] = commit
    if not commit:
        # 只现算不落库，不得伪装成已入库
        return {"id": None, **result}
    run = AllocationRun(segment_id=segment_id, created_at=datetime.utcnow(),
                        result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"id": run.id, **result}


@router.get("/latest")
def latest(segment_id: int = 1, db: Session = Depends(get_db)):
    run = db.scalars(select(AllocationRun).where(AllocationRun.segment_id == segment_id)
                     .order_by(AllocationRun.id.desc())).first()
    if not run:
        return run_allocate(segment_id=segment_id, payload=None, db=db)
    data = json.loads(run.result_json)
    data.setdefault("boosts", [])
    data.setdefault("committed", True)
    return {"id": run.id, **data}
