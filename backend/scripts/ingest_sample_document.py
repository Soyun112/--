"""샘플 통학로 안전진단 문서를 Document Parse + Information Extract 파이프라인으로 적재.

실행:
    cd backend
    python scripts/ingest_sample_document.py

UPSTAGE_API_KEY가 .env에 설정되어 있으면 실제 Upstage API를 호출하고,
없으면 자동으로 MOCK 추출 결과(app/data/sample_documents/sample_report_extract.json)를 사용한다.
실제 문서로 교체하려면 app/data/sample_documents/ 아래에 PDF를 넣고
이 스크립트의 SAMPLE_DOC_PATH를 수정하면 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.document_pipeline import ingest_document  # noqa: E402

SAMPLE_DOC_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "sample_documents" / "sample_report.md"
SAMPLE_DOC_NAME = "OO구_2024_통학로_안전진단_보고서(SAMPLE).pdf"


def main() -> None:
    result = ingest_document(SAMPLE_DOC_PATH.read_bytes(), SAMPLE_DOC_NAME)
    mock_tag = "MOCK" if result["used_mock"] else "실제 Upstage API"
    print(f"문서 적재 완료 ({mock_tag}): {result['risk_points_created']}개 위험/안전 포인트 생성")


if __name__ == "__main__":
    main()
