"""SQLite 기반 구조화 데이터 저장소.

공공데이터(어린이보호구역·교통사고다발지역·범죄지수 근사치)는 배치 스크립트
(scripts/ingest_public_data.py)로 적재하고, 문서 기반 위험/안전 포인트는
Document Parse + Information Extract 파이프라인 실행 시 적재된다.
모든 레코드에 source(출처)를 남겨 데이터 자산의 추적성을 확보한다.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS child_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    cctv_count INTEGER DEFAULT 0,
    managing_org TEXT,
    police_office TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS accident_hotspots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id TEXT,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    occurrence_count INTEGER DEFAULT 0,
    casualty_count INTEGER DEFAULT 0,
    fatality_count INTEGER DEFAULT 0,
    source TEXT
);

CREATE TABLE IF NOT EXISTS crime_grid (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_key TEXT UNIQUE,
    lat_center REAL NOT NULL,
    lng_center REAL NOT NULL,
    region_name TEXT,
    risk_index REAL DEFAULT 0,
    source TEXT
);

CREATE TABLE IF NOT EXISTS guardian_houses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    category TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    contact TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS streetlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    light_type TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS speed_cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id TEXT,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    speed_limit_kmh INTEGER,
    source TEXT
);

CREATE TABLE IF NOT EXISTS doc_risk_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    risk_type TEXT,
    is_risk INTEGER DEFAULT 1,
    snippet TEXT,
    source_doc TEXT,
    page INTEGER,
    report_date TEXT,
    recommendation TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    db_path: Path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)


def clear_table(table: str) -> None:
    assert table in {
        "child_zones",
        "accident_hotspots",
        "crime_grid",
        "doc_risk_points",
        "guardian_houses",
        "streetlights",
        "speed_cameras",
    }
    with session() as conn:
        conn.execute(f"DELETE FROM {table}")


def insert_child_zone(conn: sqlite3.Connection, *, name, lat, lng, cctv_count, managing_org, police_office, source):
    conn.execute(
        "INSERT INTO child_zones (name, lat, lng, cctv_count, managing_org, police_office, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, lat, lng, cctv_count, managing_org, police_office, source),
    )


def insert_accident_hotspot(conn: sqlite3.Connection, *, spot_id, name, lat, lng, occurrence_count, casualty_count, fatality_count, source):
    conn.execute(
        "INSERT INTO accident_hotspots (spot_id, name, lat, lng, occurrence_count, casualty_count, fatality_count, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (spot_id, name, lat, lng, occurrence_count, casualty_count, fatality_count, source),
    )


def insert_crime_grid(conn: sqlite3.Connection, *, grid_key, lat_center, lng_center, region_name, risk_index, source):
    conn.execute(
        "INSERT OR REPLACE INTO crime_grid (grid_key, lat_center, lng_center, region_name, risk_index, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (grid_key, lat_center, lng_center, region_name, risk_index, source),
    )


def insert_doc_risk_point(conn: sqlite3.Connection, *, lat, lng, risk_type, is_risk, snippet, source_doc, page, report_date, recommendation):
    conn.execute(
        "INSERT INTO doc_risk_points (lat, lng, risk_type, is_risk, snippet, source_doc, page, report_date, recommendation) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (lat, lng, risk_type, int(is_risk), snippet, source_doc, page, report_date, recommendation),
    )


def insert_guardian_house(conn: sqlite3.Connection, *, name, category, lat, lng, contact, source):
    conn.execute(
        "INSERT INTO guardian_houses (name, category, lat, lng, contact, source) VALUES (?, ?, ?, ?, ?, ?)",
        (name, category, lat, lng, contact, source),
    )


def insert_streetlight(conn: sqlite3.Connection, *, facility_id, lat, lng, light_type, source):
    conn.execute(
        "INSERT INTO streetlights (facility_id, lat, lng, light_type, source) VALUES (?, ?, ?, ?, ?)",
        (facility_id, lat, lng, light_type, source),
    )


def insert_speed_camera(conn: sqlite3.Connection, *, facility_id, name, lat, lng, speed_limit_kmh, source):
    conn.execute(
        "INSERT INTO speed_cameras (facility_id, name, lat, lng, speed_limit_kmh, source) VALUES (?, ?, ?, ?, ?, ?)",
        (facility_id, name, lat, lng, speed_limit_kmh, source),
    )


def fetch_all(table: str) -> list[sqlite3.Row]:
    with session() as conn:
        cur = conn.execute(f"SELECT * FROM {table}")
        return cur.fetchall()
