"""공공데이터 배치 수집 스크립트.

PROJECT_PLAN.md 4장의 "관리 포인트"에 따라 공공API 수집은 요청 시점이 아니라
별도 배치로 분리한다. 운영 환경에서는 이 스크립트를 1일 1회 스케줄러(cron 등)로 실행해
SQLite(child_zones/accident_hotspots/crime_grid)를 갱신한다.

실행:
    cd backend
    python scripts/ingest_public_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import public_data  # noqa: E402


def main() -> None:
    summary = public_data.ingest_all()
    print("공공데이터 적재 완료:")
    for name, info in summary.items():
        mock_tag = " (MOCK 샘플 데이터)" if info["mock"] else " (실제 API)"
        print(f"  - {name}: {info['count']}건{mock_tag}")


if __name__ == "__main__":
    main()
