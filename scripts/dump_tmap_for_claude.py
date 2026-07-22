# -*- coding: utf-8 -*-
"""Dump Tmap pedestrian raw + pipeline polyline for Claude handoff."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# backend on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from app.config import settings
from app.services.routing import (
    TMAP_PEDESTRIAN_URL,
    _call_tmap,
    _coords_from_tmap_features,
    _fetch_tmap_pedestrian_raw,
)
from app.services.tmap_geo import match_coords_to_roads

OUT = ROOT / "claude_handoff_route_dump"
OUT.mkdir(exist_ok=True)

# 강남 통학 데모: 개나리SK뷰 ↔ 필수학학원 (도보 ~10분대)
ORIGIN = (37.5012, 127.0499)  # 집
DEST = (37.4989686, 127.0525688)  # 학원
ORIGIN_NAME = "개나리SK뷰5차아파트"
DEST_NAME = "필수학학원"


def to_geojson_linestring(coords_latlng: list[tuple[float, float]], name: str) -> dict:
    # GeoJSON is [lng, lat]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": name, "coord_count": len(coords_latlng)},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lng, lat] for lat, lng in coords_latlng],
                },
            }
        ],
    }


def raw_features_to_geojson(data: dict, name: str) -> dict:
    features_out = []
    for f in data.get("features") or []:
        g = f.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        features_out.append(
            {
                "type": "Feature",
                "properties": {
                    "name": name,
                    "description": (f.get("properties") or {}).get("description"),
                    "index": (f.get("properties") or {}).get("index"),
                },
                "geometry": g,
            }
        )
    return {"type": "FeatureCollection", "features": features_out}


def main() -> None:
    report: dict = {
        "note": "Claude handoff — keys redacted",
        "tmap_key_present": bool(settings.tmap_app_key),
        "settings": {
            "tmap_pedestrian_search_option": settings.tmap_pedestrian_search_option,
            "tmap_road_match_enabled": settings.tmap_road_match_enabled,
            "tmap_pedestrian_alt_enabled": settings.tmap_pedestrian_alt_enabled,
            "tmap_route_densify_enabled": settings.tmap_route_densify_enabled,
            "routing_mock": settings.routing_mock,
        },
        "scenario": {
            "origin_latlng": ORIGIN,
            "destination_latlng": DEST,
            "origin_name": ORIGIN_NAME,
            "destination_name": DEST_NAME,
            "is_seolleung_special_path": False,
            "note": "선릉로 특수 경로 분기 제거됨 — 일반 main/alt/우회",
        },
    }

    option = settings.tmap_pedestrian_search_option or "4"
    body = {
        "startX": ORIGIN[1],
        "startY": ORIGIN[0],
        "endX": DEST[1],
        "endY": DEST[0],
        "startName": "출발지",
        "endName": "목적지",
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": option,
        "sort": "index",
        "speed": 4,
    }
    report["request"] = {
        "url": TMAP_PEDESTRIAN_URL,
        "query_params": {"version": "1", "format": "json"},
        "body": body,
        "headers_note": "appKey REDACTED",
    }

    print("Calling Tmap pedestrian…")
    raw = _fetch_tmap_pedestrian_raw(ORIGIN, DEST, search_option=option, pass_list=None)
    if not raw:
        report["error"] = "pedestrian returned None (429 / network / quota / key)"
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("FAILED — see report.json")
        return

    (OUT / "tmap_pedestrian_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "tmap_raw_linestrings.geojson").write_text(
        json.dumps(raw_features_to_geojson(raw, "tmap_raw_LineString_only"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    features = raw.get("features") or []
    point_n = sum(1 for f in features if (f.get("geometry") or {}).get("type") == "Point")
    line_n = sum(1 for f in features if (f.get("geometry") or {}).get("type") == "LineString")

    coords, dist, time_s, main_road = _coords_from_tmap_features(features, search_option=option)
    coords_road = match_coords_to_roads(list(coords))

    (OUT / "pipeline_before_roadmatch.geojson").write_text(
        json.dumps(to_geojson_linestring(coords, "pipeline_LineString_parse_only"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "pipeline_after_roadmatch.geojson").write_text(
        json.dumps(
            to_geojson_linestring(coords_road, "pipeline_after_matchToRoads"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Full candidate path (main/alt/detour) + safety scores
    from app import db
    from app.services.routing import get_route_candidates, _has_backtrack
    from app.services.scoring import score_candidates

    db.init_db()

    # Windows console encoding safety for routing prints
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cands = get_route_candidates(ORIGIN, DEST, force_mock=False, origin_name=ORIGIN_NAME, destination_name=DEST_NAME)
    scored = score_candidates(cands) if cands else []
    score_by_id = {s.raw.id: s for s in scored}

    cand_summaries = []
    for c in cands:
        gj = to_geojson_linestring(c.coordinates, c.id)
        path = OUT / f"candidate_{c.id}.geojson"
        path.write_text(json.dumps(gj, ensure_ascii=False, indent=2), encoding="utf-8")
        s = score_by_id.get(c.id)
        cand_summaries.append(
            {
                "id": c.id,
                "label": c.label,
                "source": c.source,
                "distance_m": round(c.distance_m, 1),
                "duration_s": c.duration_s,
                "coord_count": len(c.coordinates),
                "has_backtrack": _has_backtrack(c.coordinates),
                "safety_score": None if s is None else round(float(s.safety_score), 2),
                "is_recommended": None if s is None else bool(s.is_recommended),
                "geojson_file": path.name,
                "first3": c.coordinates[:3],
                "last2": c.coordinates[-2:],
            }
        )

    report["response_summary"] = {
        "feature_count": len(features),
        "Point": point_n,
        "LineString": line_n,
        "parsed_coord_count": len(coords),
        "after_roadmatch_coord_count": len(coords_road),
        "total_distance_m": dist,
        "total_time_s": time_s,
        "coords_changed_by_roadmatch": coords != coords_road,
    }
    report["candidates"] = cand_summaries
    report["files"] = sorted(p.name for p in OUT.iterdir())

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK →", OUT)
    print(json.dumps(report["response_summary"], ensure_ascii=False, indent=2))
    print("seolleung special removed:", not report["scenario"]["is_seolleung_special_path"])
    print("candidates:", json.dumps(cand_summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
