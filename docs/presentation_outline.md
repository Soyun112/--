# 발표자료 개요 (슬라이드 구성안)

PROJECT_PLAN.md의 내용을 그대로 인용해 슬라이드를 채운다. 각 슬라이드에 대응하는
루브릭 배점을 함께 표기해 발표 중 스스로 점검할 수 있게 한다.

1. **표지** — 서비스명(가칭 "안심등굣길"), 팀명, 한 줄 소개
2. **문제 정의** [Service Differentiation 10pt] — 기존 지도서비스/범용 LLM의 한계,
   실제 통학로 사고·범죄 통계로 문제의 심각성 제시
3. **차별화** [Service Differentiation] — PROJECT_PLAN.md 2장 비교표(카카오맵/티맵,
   범용 LLM, 기존 안전지도 vs 우리 서비스) 그대로 사용
4. **데이터 아키텍처** [Data Architecture & Process 20pt] — PROJECT_PLAN.md 4장
   mermaid 다이어그램, 데이터 출처 표(3장), "관리 포인트"(배치 수집/출처 추적) 설명
5. **안전점수 알고리즘** [Solution Depth 15pt] — 5장 수식, Haversine 리샘플링·버퍼링
   설명, 상대 정규화를 선택한 이유(절대 가중치의 자의성 회피)
6. **Upstage 활용 상세** [Effective Use of Upstage 20pt — 최우선] — 6장 파이프라인,
   Before/After 비교(문서 근거 없는 범용 LLM 답변 vs grounded 답변),
   실제 API 호출/응답 스크린샷(Document Parse, Information Extract, Solar)
7. **라이브 데모** — `docs/demo_script.md` 순서대로 진행
8. **서비스 임팩트 & 확장성** [Service Impact 20pt] — 7장 내용, 학교/교육청 배포
   시나리오, 지자체 예산 근거자료화
9. **한계와 로드맵** — 범죄 데이터 좌표 정밀도 제약과 safemap 등급 조인 계획,
   PostGIS 전환, 전국 확장 계획 (데이터 한계를 스스로 인지했다는 점을 강조해
   Solution Depth 신뢰도를 높임)
10. **팀 소개 & Q&A**

## 발표 전달 체크리스트 [Presentation & Documentation 15pt]

- 각 슬라이드는 PROJECT_PLAN.md의 문장을 그대로 재사용해 발표 내용과 문서 간
  논리 불일치가 없도록 한다.
- 데모는 반드시 사전에 `docs/demo_script.md` 시나리오로 1회 이상 리허설한다.
- Upstage API 호출 로그/응답 예시를 캡처해 슬라이드에 첨부하면 "기술 적용 결과의
  기여도" 평가에 유리하다.
