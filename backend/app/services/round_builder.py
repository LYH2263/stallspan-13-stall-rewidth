"""把一次分配（现算预览或确认入库）装配成统一的轮次载荷。

纯函数、不碰数据库：登记优先 / 本轮临时 / 本轮生效三套数与图、落库表、放不下
全部在同一份载荷里同源产出，前端不得再与独立的 /vendors 请求混读（防串口径）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from app.services.first_fit_engine import (
    allocate_first_fit,
    apply_temp_priorities,
    result_to_dict,
)


def build_round(seg, pillars: list[dict], vendors: list[dict], boosts: list[dict],
                *, confirmed: bool, run_id=None, created_at: datetime | None = None) -> dict:
    """seg 需有 id/name/width_m；vendors 为登记摊主 dict（含 id/name/stall_width_m/priority）；
    boosts 为 [{vendor_id, temp_priority}]（调用方负责拒绝重复 id）。

    非法临时值由 apply_temp_priorities 抛 PriorityError，调用方转 400，整次不写库。
    """
    overrides = {int(b["vendor_id"]): b["temp_priority"] for b in boosts}
    effective_vendors = apply_temp_priorities(vendors, overrides)

    registered = {v["id"]: v.get("priority", 1) for v in vendors}
    effective = {v["id"]: v.get("priority", 1) for v in effective_vendors}
    name_of = {v["id"]: v["name"] for v in vendors}
    width_of = {v["id"]: float(v["stall_width_m"]) for v in vendors}

    result = result_to_dict(allocate_first_fit(seg.width_m, effective_vendors, pillars))

    def _prio_fields(vid: int) -> dict:
        return {
            "registered_priority": registered[vid],
            "temp_priority": overrides.get(vid),
            "effective_priority": effective[vid],
        }

    for p in result["placements"]:
        p.update(_prio_fields(p["vendor_id"]))
    for r in result["rejected"]:
        r.update(_prio_fields(r["vendor_id"]))

    status = {p["vendor_id"]: "placed" for p in result["placements"]}
    for r in result["rejected"]:
        status[r["vendor_id"]] = "rejected"

    order = sorted(effective_vendors, key=lambda v: (v.get("priority", 1), v["id"]))
    result["vendors"] = [
        {
            "vendor_id": v["id"],
            "vendor_name": name_of[v["id"]],
            "width_m": width_of[v["id"]],
            "registered_priority": registered[v["id"]],
            "temp_priority": overrides.get(v["id"]),
            "effective_priority": effective[v["id"]],
            "status": status[v["id"]],
        }
        for v in order
    ]

    result["boosts"] = [
        {"vendor_id": vid, "temp_priority": overrides[vid]}
        for vid in sorted(overrides)
    ]
    result["segment"] = {"id": seg.id, "name": seg.name, "width_m": seg.width_m}
    result["pillars"] = pillars
    result["confirmed"] = confirmed
    result["created_at"] = created_at.isoformat() if created_at else None
    result["id"] = run_id
    result["round_token"] = str(run_id) if confirmed else f"preview-{uuid.uuid4().hex}"
    return result
