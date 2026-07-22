# Claude 경로 디버그 핸드오프 (재덤프 — 선릉로 특수 경로 제거 후)

작성: Cursor. appKey 제외. OD 동일: 개나리SK뷰 ↔ 필수학학원.

## 적용한 수정 (코드)

1. **선릉로 특수 경로 제거** — `_is_seolleung_sidewalk_commute` / `_seolleung_sidewalk_route` / `_SEOLLEUNG_EAST_SIDEWALK_VIAS` 삭제. `get_route_candidates`는 항상 main → (선택) alt → 우회.
2. **왕복 감지기** — `_has_backtrack` + `_drop_backtracking_candidates`를 `_finalize_candidates` 앞에서 적용.
3. **via 사전 검증** — `_via_is_reachable` (pedestrian 스냅 >20m 이면 폐기)를 우회 passList 전에 호출.
4. **matchToRoads 기본 OFF** — `TMAP_ROAD_MATCH_ENABLED=false` (범인은 아니었지만 방향 유지).

## 재덤프 결과 (같은 OD)

| | 이전 (특수 via) | 지금 |
|--|-----------------|------|
| 최종 후보 id | `route-seolleung-sidewalk` | `route-tmap-pedestrian-main` |
| 거리 | 941 m | **433 m** |
| 좌표 수 | 46 | **19** |
| has_backtrack | 있음 (왕복 2구간) | **false** |
| 후보 수 (finalize 후) | 1 (조기 return) | **1** (main==alt 중복 제거) |
| 안전점수 | (상수화 위험) | 61.3 (후보 1개라 min-max 의미 없음) |

원문 pedestrian도 433m / 19점 — **앱 최종 == 원문**.

### 후보가 1개인 이유
- main (`searchOption=4`)과 alt (`10`)가 **동일 기하** → 중복 제거로 alt 탈락.
- 우회: 로컬 SQLite에 사고다발/문서 위험이 비어 있거나, via 검증으로 버려져 **detour 0개**.
- → 데모 OD에서 “여러 경로 점수 비교”는 아직 안 켜짐. **searchOption 0/4/10 실험** 또는 절대 스케일 점수가 다음 단계.

### geojson.io
1. `tmap_raw_linestrings.geojson` — 433m
2. `candidate_route-tmap-pedestrian-main.geojson` — 동일 (특수 경로 없음)
3. (삭제됨) `candidate_route-seolleung-sidewalk.geojson`

`report.json` → `candidates[]`에 distance / safety_score / has_backtrack.

## 이전 덤프에서 확정된 범인 (참고)
- via 3점이 선릉로(127.051x)가 아니라 **70~100m 서쪽 골목** → 막다른 스냅 → 왕복 458m≈늘어난 길이의 90%.
- matchToRoads / 파싱 / CSV WGS84: **무죄** (`coords_changed: false`).

## Claude 다음
1. min-max → **절대 스케일** + 가중치 (후보 1~N 모두 의미 있게)
2. searchOption **0 / 4 / 10** 병렬 + 폴리라인 해시 중복 제거 → 실제 후보 수 확인
3. (이후) 문서 구간 pedestrian, Kakao address.json, 기둥 중복 WKT 정리
