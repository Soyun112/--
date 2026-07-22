# -*- coding: utf-8 -*-
"""k 캘리브레이션 — 강남 어린이보호구역 기반 통학 OD 100쌍.

표본: 존 중심을 도착지로, 300m~1.2km 랜덤 점을 출발지로.
searchOption=4 고정, 주간 점수. 왕복 경로는 제외(재추첨 없음).
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
os.environ.setdefault("PUBLIC_DATA_MOCK", "true")

from app import db
from app.config import settings
from app.services import public_data
from app.services.routing import _call_tmap, _has_backtrack
from app.services.scoring import absolute_score, compute_features

OUT_DIR = ROOT / "claude_handoff_route_dump"
OUT_DIR.mkdir(exist_ok=True)
CSV_PATH = OUT_DIR / "calib_k_100_routes.csv"
SUMMARY_PATH = OUT_DIR / "calib_k_100_summary.json"

N_PAIRS = 100
RNG_SEED = 42
MIN_M = 300.0
MAX_M = 1200.0


def _offset_point(lat: float, lng: float, dist_m: float, bearing_rad: float) -> tuple[float, float]:
    dlat = (dist_m * math.cos(bearing_rad)) / 111_320.0
    dlng = (dist_m * math.sin(bearing_rad)) / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return lat + dlat, lng + dlng


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    return float(np.percentile(values, q))


def _nonzero_median(values: list[float]) -> float | None:
    nz = [v for v in values if v > 0]
    if not nz:
        return None
    return float(np.median(nz))


def _eff_km(distance_km: float) -> float:
    return max(float(distance_km), float(settings.score_length_floor_km))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    db.init_db()
    # MOCK 보안등 제거 — light는 안심 305만
    ingest = public_data.ingest_all()
    db.clear_table("streetlights")
    print(f"[calib] streetlights cleared; was ingest={ingest.get('streetlights')}")
    print(f"[calib] streetlights_now={len(public_data.get_streetlights())}")

    zones = public_data.get_child_zones()
    if len(zones) < 10:
        raise RuntimeError(f"need child_zones CSV, got {len(zones)}")

    snapshot = public_data.build_ingest_snapshot(ingest)
    snapshot["streetlights_forced_empty"] = True
    snapshot["light_density_source"] = "ansim_305_only"
    snapshot["n_pairs_requested"] = N_PAIRS
    snapshot["search_option"] = "4"
    snapshot["rng_seed"] = RNG_SEED

    rng = random.Random(RNG_SEED)
    fieldnames = [
        "route_id",
        "origin_lat",
        "origin_lng",
        "dest_lat",
        "dest_lng",
        "zone_name",
        "length_km",
        "sf_cctv_cnt",
        "sf_light_cnt",
        "sf_emerg_cnt",
        "zone_cctv",
        "coverage",
        "guardian_cnt",
        "camera_cnt",
        "accident_cnt",
        "doc_risk_cnt",
        "score",
        "status",
    ]

    rows: list[dict] = []
    n_fail = 0
    n_backtrack = 0
    n_ok = 0

    print(f"[calib] zones={len(zones)} pairs={N_PAIRS}")
    for i in range(N_PAIRS):
        zone = zones[i % len(zones)]
        dest = (float(zone["lat"]), float(zone["lng"]))
        dist_m = rng.uniform(MIN_M, MAX_M)
        bearing = rng.uniform(0, 2 * math.pi)
        origin = _offset_point(dest[0], dest[1], dist_m, bearing)
        zone_name = zone.get("name") or ""
        route_id = f"calib-{i:03d}"

        base = {
            "route_id": route_id,
            "origin_lat": round(origin[0], 7),
            "origin_lng": round(origin[1], 7),
            "dest_lat": round(dest[0], 7),
            "dest_lng": round(dest[1], 7),
            "zone_name": zone_name,
            "length_km": "",
            "sf_cctv_cnt": "",
            "sf_light_cnt": "",
            "sf_emerg_cnt": "",
            "zone_cctv": "",
            "coverage": "",
            "guardian_cnt": "",
            "camera_cnt": "",
            "accident_cnt": "",
            "doc_risk_cnt": "",
            "score": "",
            "status": "",
        }

        try:
            cand = _call_tmap(origin, dest, search_option="4", route_suffix=f"calib-{i}")
        except Exception as exc:
            n_fail += 1
            base["status"] = f"fail:{type(exc).__name__}"
            rows.append(base)
            print(f"  [{i+1}/{N_PAIRS}] FAIL {zone_name}: {exc}")
            continue

        if cand is None or len(cand.coordinates) < 2:
            n_fail += 1
            base["status"] = "fail:empty"
            rows.append(base)
            print(f"  [{i+1}/{N_PAIRS}] EMPTY {zone_name}")
            continue

        if _has_backtrack(cand.coordinates):
            n_backtrack += 1
            base["status"] = "backtrack"
            base["length_km"] = round(cand.distance_m / 1000.0, 4)
            rows.append(base)
            print(f"  [{i+1}/{N_PAIRS}] BACKTRACK {zone_name} {cand.distance_m:.0f}m")
            continue

        feats = compute_features(cand)
        score = absolute_score(feats, is_night=False, detour_penalty=0.0, walk_minutes=cand.duration_s / 60.0)
        n_ok += 1
        base.update(
            {
                "length_km": round(feats.distance_km, 4),
                "sf_cctv_cnt": feats.safety_facility_cctv_count,
                "sf_light_cnt": feats.safety_facility_streetlight_count,
                "sf_emerg_cnt": feats.emergency_pole_count,
                "zone_cctv": feats.zone_cctv_count,
                "coverage": round(feats.child_zone_coverage_pct / 100.0, 4),
                "guardian_cnt": feats.guardian_house_count,
                "camera_cnt": feats.speed_camera_count,
                "accident_cnt": feats.accident_hotspot_count,
                "doc_risk_cnt": feats.doc_risk_count,
                "score": score,
                "status": "ok",
            }
        )
        rows.append(base)
        print(
            f"  [{i+1}/{N_PAIRS}] OK {zone_name} {feats.distance_km:.2f}km "
            f"score={score:.1f} cov={feats.child_zone_coverage_pct:.0f}% "
            f"light={feats.safety_facility_streetlight_count}"
        )

    # write CSV with snapshot header comments
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("# calib_k_100 snapshot\n")
        for k, v in snapshot.items():
            f.write(f"# {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float, bool)) else v}\n")
        f.write(f"# ok={n_ok} backtrack={n_backtrack} fail={n_fail}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ok_rows = [r for r in rows if r["status"] == "ok"]

    def col(name: str) -> list[float]:
        return [float(r[name]) for r in ok_rows]

    L = [_eff_km(float(r["length_km"])) for r in ok_rows]
    dens = {
        "sf_cctv": [c / L[i] for i, c in enumerate(col("sf_cctv_cnt"))],
        "sf_light": [c / L[i] for i, c in enumerate(col("sf_light_cnt"))],
        "sf_emerg": [c / L[i] for i, c in enumerate(col("sf_emerg_cnt"))],
        "guardian": [c / L[i] for i, c in enumerate(col("guardian_cnt"))],
        "zone_cctv": col("zone_cctv"),  # count
    }
    coverage = col("coverage")
    scores = col("score")
    accidents = col("accident_cnt")
    cameras = col("camera_cnt")

    def count_dist(vals: list[float]) -> dict:
        return {
            "pct_0": round(100.0 * sum(1 for v in vals if v == 0) / max(1, len(vals)), 1),
            "pct_1": round(100.0 * sum(1 for v in vals if v == 1) / max(1, len(vals)), 1),
            "pct_2plus": round(100.0 * sum(1 for v in vals if v >= 2) / max(1, len(vals)), 1),
            "max": int(max(vals)) if vals else 0,
        }

    ansim_hit = sum(
        1
        for r in ok_rows
        if int(r["sf_cctv_cnt"]) + int(r["sf_light_cnt"]) + int(r["sf_emerg_cnt"]) > 0
    )

    summary = {
        "snapshot": snapshot,
        "counts": {"requested": N_PAIRS, "ok": n_ok, "backtrack": n_backtrack, "fail": n_fail},
        "nonzero_median_k": {
            "sf_cctv_per_km": _nonzero_median(dens["sf_cctv"]),
            "sf_light_per_km": _nonzero_median(dens["sf_light"]),
            "sf_emerg_per_km": _nonzero_median(dens["sf_emerg"]),
            "guardian_per_km": _nonzero_median(dens["guardian"]),
            "zone_cctv_count": _nonzero_median(dens["zone_cctv"]),
        },
        "coverage_median_all": float(np.median(coverage)) if coverage else None,
        "accident_dist": count_dist(accidents),
        "camera_dist": count_dist(cameras),
        "ansim_nonzero_ratio": round(ansim_hit / max(1, n_ok), 4),
        "score_dist": {
            "min": round(min(scores), 1) if scores else None,
            "p25": round(_pct(scores, 25), 1) if scores else None,
            "median": round(_pct(scores, 50), 1) if scores else None,
            "p75": round(_pct(scores, 75), 1) if scores else None,
            "max": round(max(scores), 1) if scores else None,
            "p75_minus_p25": round(_pct(scores, 75) - _pct(scores, 25), 1) if scores else None,
        },
        "files": {"csv": str(CSV_PATH.name), "summary": str(SUMMARY_PATH.name)},
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nOK → {CSV_PATH}")
    print(f"OK → {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
