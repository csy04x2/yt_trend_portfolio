# 고정 Reference Population과 canonical view_multiple

2026-09-17 · branch `feat/reference-population` (base `integration/feature-discovery-observable` `b6fc5cc`)

[Control Tower checkpoint](../reports/control-tower-checkpoint-2026-09-15.md)의
**C — Relative Performance: BLOCKED FOR FINAL FINDING**을 풀기 위한 설계다.
정책(인간 확정, 이 문서에서 바꾸지 않음):

- 기존 300편 split(Discovery 90 / Development 90 / Holdout 120)은 그대로 둔다.
- 300편을 사후 재편해 reference pool을 만들지 않는다.
- 실험 split과 별개인 historical/reference population을 확보한다.
- split 결과를 보기 **전에** 선정 규칙을 동결하고, 그 다음 canonical normalization을 provenance와 함께 계산한다.

이 문서에서 **[제안]** 표시가 붙은 값·선택은 사람 승인 전이다. 코드의 규칙 객체도
`rules_status = "proposal"`로 시작하며, 이 상태로 계산한 값은 `final_eligible = false`다.

## 1. 문제

Finding은 upstream이 공급한 `view_multiple`을 소비한다. 지금 이 값의 분모 peer는
split 300편 전체에서 나온다. Development 영상의 분모에 Discovery/Holdout 영상이 섞이고,
Holdout 검증 때도 Development 영상이 분모에 들어간다. 게다가 정의가 셋이며 서로
교환되지 않는다 ([Outcome-side audit](../reports/outcome-side-audit-2026-09-15.md)).

| 현재 구현 | 분모 peer | 최소 |
|---|---|---|
| `normalize.py::view_multiple` | 같은 길이 축 · 같은 게시 분기 · 자기/live 제외 | 3 |
| `observable.py::compare` | 같은 길이 축 · 게시 후 나이 ±max(2일, 20%) · 자기/live 제외 | 5 |
| `breakout.py::recompute_multiples` | 같은 길이 축 · 같은 게시 분기 · 자기/급등 영상 제외 | 5 |

## 2. Reference population 정의

### 2.1 후보 출처

**같은 채널의 과거 업로드 중 split 최초 게시 시각(boundary) 이전에 게시된 영상.**
YouTube Data API로 **메타데이터·통계만** 받는다 (`channels.list` 1회 +
`playlistItems.list` 페이지 + `videos.list` 묶음, 모두 1유닛). 댓글 엔드포인트는 쓰지 않는다.

- boundary = split 300편 중 가장 이른 `published_at`. 침착맨 로컬 DB 기준 `2026-03-19T10:00:33Z`.
- split 밖이지만 boundary **이후**에 게시된 업로드(표본에 안 뽑힌 최근 영상)는 쓰지 않는다
  (`not_before_boundary`). split 기간과 겹치는 영상을 섞으면 "split과 별개인 과거 모집단"이라는
  성격이 흐려지고, 표본 추출 방식에 따라 split과 체계적으로 달라질 수 있어서다. **[제안]**
- 대안(사람 판단): boundary 이후 split 밖 업로드도 허용. 현재 코드는 지원하지 않는다.

### 2.2 적격 규칙 (`ref-rules-v0.1`, **[제안]**)

순서대로 처음 걸린 사유 하나로 제외하고 사유별 개수를 manifest에 남긴다.

| 순서 | 사유 | 규칙 |
|---|---|---|
| 1 | `channel_mismatch` | 채널 ID가 다름 |
| 2 | `in_split` | split 영상. **어떤 경우에도 포함하지 않는다** |
| 3 | `not_before_boundary` | boundary 이후 게시 |
| 4 | `outside_window` | boundary 이전 `window_days`(365일) 밖 **[제안]** |
| 5 | `live_or_premiere` | `is_live` 또는 `liveStreamingDetails` 근거 있음(프리미어 포함) — `classify_live`가 미확정이라 보수적으로 제외 **[제안]** |
| 6 | `upcoming_or_live_now` | `liveBroadcastContent`가 live/upcoming |
| 7 | `duration_unknown` | 길이 0/누락 → 길이 축 불가 |
| 8 | `captured_at_unknown` | 스냅샷 시각 없음 |
| 9 | `not_matured` | 스냅샷 시점 게시 후 `maturity_days`(90일) 미만 **[제안]** |
| 10 | `views_unavailable` | 조회수 비공개/누락 |

- 길이 축: `normalize.py`와 같은 경계(≤180초 shorts, ≤1200초 standard, 그 초과 long).
- **선정은 조회수 값을 보지 않는다.** 조회수는 스냅샷으로 기록될 뿐이고, 값의 크기로
  포함 여부가 바뀌지 않는다 (테스트로 고정). 비공개(값 없음)만 제외한다.
- 채널 성장기(구독자 증가)가 다르면 과거 영상의 성숙 조회수 수준도 다르다. window를
  1년으로 제한하는 이유이며, 분기별 개수(`by_quarter`)를 manifest에 남겨 사람이 쏠림을 본다.

### 2.3 최소 크기

- 층(stratum) = **길이 축**. 축별 reference `min_per_axis = 20`편 **[제안]**.
- 모자라는 축은 manifest에서 `insufficient`이고, 그 축의 대상 영상은 canonical 배수를
  내지 않는다 (`reference_insufficient`). 다른 축에서 빌려오지 않는다.
- 분기는 매칭 층이 아니다. historical reference는 정의상 split과 분기가 겹치지 않는다.
  분기별 개수는 참고용이며 분기 최소치는 강제하지 않는다 **[제안]**.
- 침착맨 split의 standard 축은 6편뿐이라 reference도 부족할 가능성이 높다. 이 경우
  standard는 결측으로 두는 것이 정책상 맞다 (값을 만들지 않는다).

### 2.4 동결 절차

1. 이 문서의 규칙 값을 사람이 승인 → 코드의 `ReferenceRules` 기본값에 `rules_status="approved"`,
   필요 시 `rules_version` 올림 → 커밋. **승인 전에는 split 결과와 비교하지 않는다.**
2. `fetch`로 업로드 메타·통계 스냅샷 JSON 저장 (네트워크 단계, 명시적 `--confirm-api`).
3. `build` dry-run으로 개수·해시만 확인 (ID·조회수 출력 없음).
4. `build --write`로 manifest 저장 → **split 결과와 비교하기 전에** manifest(와 스냅샷 JSON)를 git 커밋.
5. 그 이후에만 canonical 배수를 계산한다. manifest의 `manifest_sha256`은
   `manifest_sha256` 필드를 뺀 전체를 정렬된 JSON으로 직렬화한 SHA-256이다.
   규칙·boundary·split ID 해시·업로드 ID 해시·제외 개수·축별 개수/중앙값·reference 행
   (ID, 게시시각, 길이, 축, 조회수, 스냅샷 시각, 나이)이 모두 들어간다. 커밋 후 한 글자라도
   바뀌면 `verify_manifest`가 거부한다.

manifest 저장 위치(예: `docs/reference/` 또는 `backend/fixtures/reference/`)는 **[제안]**,
사람이 정한다. 조회수 스냅샷은 공개 통계이며 댓글·제목·설명은 넣지 않는다.

### 2.5 갱신 정책 **[제안]**

- 동결된 manifest는 수정하지 않는다. 갱신은 **새 버전 manifest**(새 스냅샷·새 해시)로만 한다.
- 갱신 사유: 규칙 변경 승인, 새 split(새 실험), 또는 최초 동결 후 12개월 경과.
- 하나의 Finding/Holdout 실행은 정확히 한 manifest 해시를 기록한다. Development와 Holdout
  검증은 **같은 manifest**를 쓴다. 결과를 본 뒤 manifest를 갈아끼우지 않는다.
- 대상(split) 영상 조회수 스냅샷은 성숙 조건을 만족하도록 **다시 받을 수 있다** (split 재편이
  아니라 같은 ID의 통계 재관측). 재스냅샷 일자도 결과 열람 전에 정한다.

## 3. Canonical `view_multiple` (단 하나)

**`view-multiple-reference-v0.1`** — `app.pipeline.reference.canonical_view_multiple`

> 대상 영상의 스냅샷 조회수 ÷ 동결 reference population 중 **같은 길이 축** 영상들의
> 스냅샷 조회수 **중앙값**.
> 대상도 reference와 같은 조건을 통과해야 한다: live/premiere 아님, 스냅샷 시점 게시 후
> `maturity_days` 이상. 축별 reference가 `min_per_axis` 미만이면 값 없음.

- 분모에 split 영상은 구조적으로 없다 (reference 선정이 split ID를 제외). 자기 자신도 없다.
- "성숙한 누적 조회수 대 성숙한 누적 조회수" 비교다. 같은 게시 후 나이 N일 시점 성과가 아니다.
  과거 영상의 N일 시점 조회수는 API로 얻을 수 없으므로 나이 매칭 대신 성숙 기준을 양쪽에 건다.
- 값을 못 내면 `None`과 status: `target_in_reference`, `target_live_or_premiere`,
  `target_axis_unknown`, `target_views_missing`, `target_age_unknown`, `target_not_matured`,
  `reference_insufficient`, `reference_median_nonpositive`. 0이나 1로 채우지 않는다.
- provenance 필드: `definition`, `canonical=true`, `length_axis`, `target_view_count`,
  `target_age_days`, `maturity_days`, `reference_n`, `reference_median_views`,
  `reference_manifest_sha256`, `reference_rules_version`, `reference_rules_status`,
  `final_eligible`(규칙 승인 시에만 true), `basis`(사람이 읽는 문장).

### 3.1 기존 세 정의와의 관계

세 정의는 삭제하지 않고 **non-canonical**로 표시해 둔다 (코드 주석·Finding legacy contract의
`canonical=false`, `canonical_status="provisional_legacy"`).

| 기존 | canonical과 같은 점 | 다른 점 / 앞으로의 용도 |
|---|---|---|
| `normalize.view_multiple` | 길이 축 층, 중앙값, 자기·live 제외 | 분기 층·split 내부 peer·최소 3·성숙 조건 없음. 리포트/프로토타입 탐색용 |
| `observable.compare` | 길이 축 층, 중앙값, 자기·live 제외, 최소 n 미달 시 None | 나이 ±20% 매칭·split 내부 peer·최소 5. 2026-09-15 audit의 "Finding canonical"은 **provisional/legacy**로 격하. 기존 산출물은 소급 수정하지 않음 |
| `breakout.recompute_multiples` | 길이 축 층, 중앙값 | 분기 층·급등 peer 제외·live 필터 없음. 급등 민감도 확인용 보조 분모. canonical에서 급등 제외 버전이 필요하면 reference 안의 급등 규칙을 **별도로 동결**해야 한다 **[제안: 지금은 넣지 않음]** |

같은 영상에서 세 값과 canonical 값은 수치가 다를 수 있다. 서로 대입·혼합하지 않는다.

## 4. 구현 (이번 브랜치)

| 파일 | 내용 |
|---|---|
| `backend/app/pipeline/reference.py` | 순수 함수. `select_reference`(규칙·manifest·SHA-256), `verify_manifest`, `canonical_view_multiple`, `upload_from_api_item`, `manifest_summary`(개수만) |
| `backend/scripts/build_reference_population.py` | `fetch`(네트워크, `--confirm-api` 없으면 예상 유닛만 출력) / `build`(오프라인, 기본 dry-run, `--uploads-json` 또는 `--uploads-db` read-only, `--write`는 덮어쓰기 거부) |
| `backend/feature_outcome/finding.py` | `build_findings(..., reference_manifest=None)` opt-in. 기본값이면 기존과 동일(legacy contract에 non-canonical 표시만 추가). 지정 시 manifest 해시 검증 후 공급된 `view_multiple` 대신 canonical 값 사용, `input_contract.relative_performance`에 해시·규칙 상태·status 개수·영상별 근거 기록 |
| `backend/feature_outcome/runner.py` | `--reference-manifest` opt-in. 지정 시 run manifest에 파일 SHA-256과 manifest 해시 기록 |
| `backend/feature_outcome/frozen.py` | 선택 행 투영에 `is_live`, `live_evidence`, `captured_at` 추가 (canonical의 live·성숙 판정용. peer·타 split 정보 아님) |
| `backend/tests/test_reference_population.py` | 합성 데이터 테스트 |

실행 예 (backend에서, **이번 작업에서는 fetch를 실행하지 않았다**):

```text
python scripts/build_reference_population.py fetch --channel "<채널 URL>" --max-uploads 1500 --out <경로>/chim-uploads-YYYYMMDD.json
python scripts/build_reference_population.py fetch --channel "<채널 URL>" --max-uploads 1500 --out <경로>/chim-uploads-YYYYMMDD.json --confirm-api
python scripts/build_reference_population.py build --uploads-json <경로>/chim-uploads-YYYYMMDD.json --split fixtures/labeled/discovery-chim-claude-20260914/split.csv
python scripts/build_reference_population.py build ... --write <동결 경로>/chim-reference-manifest.json
python -m feature_outcome.runner --registry R --labels L --split S --evidence E --out O --reference-manifest <동결 경로>/chim-reference-manifest.json
```

`--max-uploads 1500`의 최대 예상 사용량은 61유닛(일일 10,000 중). 업로드 재생목록은 최신순이라
split 기간(약 6개월)과 window(1년)를 덮을 만큼 받아야 한다. 부족하면 manifest의
`outside_window` 개수가 0이 된다 — 즉 창 시작까지 도달하지 못했을 수 있다는 신호다.

## 5. 로컬 데이터 가능성 점검 (2026-09-17, read-only, 개수만)

`C:/Users/EZ/Desktop/yt-trend/backend/data/chim.db`를 `mode=ro`로 열었다 (전후 mtime·크기 동일).

- videos 300, channels 1, video_stats_snapshots 602 (영상 300편 모두 스냅샷 있음, 최신 captured_at 2026-09-10).
- split CSV(`discovery-chim-claude-20260914/split.csv`)와 대조: DB 300편 **전부 split 소속, split 밖 0편**.
  backups의 두 DB(`chim-20260910T074639Z.db`, `chim-observable-20260910T075631Z.db`)도 300편 전부 split 소속.
- `build --uploads-db` dry-run: `reference_n = 0`, 제외 `in_split 300`, 세 축 모두 `insufficient`.
- split 게시 범위 2026-03-19 ~ 2026-09-09. → **로컬에는 reference 후보가 없고, API 메타데이터 수집이 필요하다.**
- 성숙 조건 영향(게시 시각만 사용, 조회수 미열람): 기존 스냅샷(2026-09-10) 기준 Development 90편 중
  게시 후 90일 이상은 49편(long 19 / shorts 29 / standard 1). 60일 기준 65편, 28일 기준 79편.
  마지막 split 영상 기준 90일이 지나는 2026-12-08 이후 split 통계를 재스냅샷하면 90편 모두 성숙 조건을 만족한다.

## 6. 사람 결정이 필요한 항목

1. 규칙 값 승인: `window_days=365`, `maturity_days=90`, `min_per_axis=20`, 층=길이 축만, 프리미어 포함 live 근거 제외.
2. boundary 이후 split 밖 업로드를 reference에서 빼는 선택 유지 여부.
3. 성숙 기준 적용 방식: (a) 2026-12-08 이후 split 통계 재스냅샷 후 계산, (b) 기존 스냅샷으로 계산하고 미성숙 영상은 결측, (c) 더 짧은 성숙 기준.
4. canonical에 급등(breakout) 제외를 넣을지 — 넣는다면 reference 안의 급등 규칙을 별도 동결.
5. manifest·업로드 스냅샷 저장 위치와 git 커밋 여부, fetch 실행 승인(API 키 사용).
6. standard 축처럼 reference가 부족한 축을 결측으로 두는 것에 대한 확인.
7. `observable.compare`를 canonical로 기술한 2026-09-15 audit 문구를 legacy로 읽는다는 이 문서의 해석 확인.

## 7. 하지 않은 것

split 파일·sealed fixture·Reaction 문서·댓글 수집 코드 변경, 300편 재편, DB 쓰기, API 호출,
실제 Finding/Holdout 실행, Finding 기본 경로 전환, 기존 세 정의의 수식 변경.
