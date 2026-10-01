"""1D First-Fit stall placement along a street segment; stalls cannot cross pillars."""
from __future__ import annotations
from dataclasses import asdict, dataclass

class PriorityError(ValueError):
    """本轮临时优先不合法（未知摊主或值不在 1–9）；整次抬升必须拒绝。"""

@dataclass
class Placement:
    vendor_id: int
    vendor_name: str
    start_m: float
    end_m: float
    width_m: float

@dataclass
class Rejected:
    vendor_id: int
    vendor_name: str
    width_m: float
    reason: str

@dataclass
class AllocResult:
    placements: list[Placement]
    rejected: list[Rejected]
    free_spans: list[tuple[float, float]]

def free_spans_from_pillars(width_m: float, pillars: list[dict]) -> list[tuple[float, float]]:
    """pillars: position_m, thickness_m — treated as blocked intervals."""
    blocked = []
    for p in pillars:
        half = p.get("thickness_m", 0.4) / 2.0
        lo = max(0.0, p["position_m"] - half)
        hi = min(width_m, p["position_m"] + half)
        if hi > lo:
            blocked.append((lo, hi))
    blocked.sort()
    merged = []
    for lo, hi in blocked:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    spans = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = hi
    if cursor < width_m:
        spans.append((cursor, width_m))
    return [(round(a, 3), round(b, 3)) for a, b in spans if b - a > 1e-6]

def allocate_first_fit(width_m: float, vendors: list[dict], pillars: list[dict]) -> AllocResult:
    """vendors sorted by priority ascending then id; each needs stall_width_m contiguous in one free span (no pillar cross)."""
    spans = free_spans_from_pillars(width_m, pillars)
    # mutable remaining capacity per span
    remain = [[a, b] for a, b in spans]
    ordered = sorted(vendors, key=lambda v: (v.get("priority", 1), v["id"]))
    placements: list[Placement] = []
    rejected: list[Rejected] = []
    for v in ordered:
        need = float(v["stall_width_m"])
        placed = False
        for span in remain:
            avail = span[1] - span[0]
            if avail + 1e-9 >= need:
                start = span[0]
                end = start + need
                placements.append(Placement(v["id"], v["name"], round(start, 3), round(end, 3), need))
                span[0] = end
                placed = True
                break
        if not placed:
            rejected.append(Rejected(v["id"], v["name"], need, "无连续空档可放下且不跨越挡柱"))
    free = [(round(a, 3), round(b, 3)) for a, b in remain if b - a > 1e-6]
    return AllocResult(placements, rejected, free)

def result_to_dict(r: AllocResult) -> dict:
    return {
        "placements": [asdict(p) for p in r.placements],
        "rejected": [asdict(x) for x in r.rejected],
        "free_spans": [{"start_m": a, "end_m": b} for a, b in r.free_spans],
    }

def apply_temp_priorities(vendors: list[dict], overrides: dict) -> list[dict]:
    """Return copied vendor dicts with this round's temp priority applied.

    只影响本轮：绝不 mutate 入参、绝不写回登记优先。overrides 为 {vendor_id: temp_priority}。
    任一 id 不存在或值不是 1–9 的真整数（拒绝 bool/float/str）都抛 PriorityError，
    由调用方整次拒绝，禁止半成功。
    """
    by_id = {}
    for v in vendors:
        vid = v["id"]
        if vid in by_id:
            raise PriorityError(f"登记摊主存在重复 id={vid}，无法分配")
        by_id[vid] = v
    # 先做完全部校验，再产出拷贝，保证非法时一个 dict 都不改。
    for vid, val in overrides.items():
        if vid not in by_id:
            raise PriorityError(f"临时优先指向不存在的摊主 id={vid}，整次抬升已拒绝")
        if isinstance(val, bool) or not isinstance(val, int) or not (1 <= val <= 9):
            raise PriorityError(
                f"摊主 id={vid} 的本轮临时优先必须是 1 到 9 的整数，整次抬升已拒绝"
            )
    out: list[dict] = []
    for v in vendors:
        nv = dict(v)
        if v["id"] in overrides:
            nv["priority"] = overrides[v["id"]]
        out.append(nv)
    return out
