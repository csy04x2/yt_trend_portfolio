# Reaction 결과를 리포트에 연결 — Stage 08 수치 · Stage 09 문장 · 대시보드

- 작성일: 2026-09-17 · branch `feat/reaction-report` (base `integration/feature-discovery-observable` `cde9851`)
- 상태: **구현 완료, 기준값은 [제안] (사람 승인 전)**. 실제 판정 결과는 아직 없다 — 모든 DB의 `comment_reactions`가 비어 있거나 표가 없다.
- 기준 정본: [Reaction track closeout](../reaction-track-closeout-2026-09-17.md) 「2026-09-17 재개 결정」 범위 3, [Phase 3 판정기](reaction-classifier-phase3.md), [분석 포함 여부](comment-eligibility.md), [댓글 표본 정책](comment-sampling-policy.md), [Reference population](reference-population.md), [아키텍처 Stage 08/09 경계](youtube-trend-architecture.md)
- 구현: `backend/app/pipeline/reaction_metrics.py` (Stage 08), `backend/app/interpret/reaction.py` (Stage 09), `backend/app/interpret/reaction_report.py` (화면 블록), `backend/scripts/export_reaction_report.py` (내보내기), `backend/app/cli.py reaction-metrics`
- 테스트: `backend/tests/test_reaction_metrics.py`, `backend/tests/test_reaction_interpret.py` (합성 데이터만)

taxonomy(R1–R10, T1–T5 + UNKNOWN)와 정의는 바꾸지 않았다.

## 1. 지위 — 이 결과로 할 수 있는 것과 없는 것

재개 결정의 제품 사용 조건을 코드와 화면에 그대로 옮겼다.

| 규칙 | 어디서 지키나 |
|---|---|
| 독립 fresh 표본 검증 전까지 모든 값은 「검증 전 AI 판정」 | `reaction_metrics.validation_status` 열(기본값·저장 값), 수치 행·문장·화면 블록마다 `validation_status`, 문장 접두어 `[검증 전 AI 판정]`, 대시보드 배지 |
| MVP Finding 입력으로 쓰지 않는다 | `feature_outcome/`은 Reaction 모듈을 import 하지 않는다(테스트로 확인). 문장·블록에 `finding_input = false` |
| 해석은 Stage 09에서만 | `reaction_metrics.py`는 문장을 만들지 않는다. 문장은 `app/interpret/`에만 있고 `app/pipeline/`의 집계 코드는 이를 import 하지 않는다(테스트). `aggregate.py`는 건드리지 않았다 |
| 침착맨 Phase 1 300건은 체계 설계에 쓰였다 | 대시보드 Reaction 절에 이 채널의 판정은 판정기 독립 검증 근거가 아니라고 적는다 |

## 2. Stage 08 수치 — `reaction_metrics`

### 2.1 입력과 분석 대상

- `comment_reactions` 중 **한 (prompt_version, model)** 만 접는다. 버전을 주지 않으면 DB에 있는 조합마다 따로 만들고 섞지 않는다.
- 댓글은 `comments.analysis_eligible = 1` 만 쓴다. 채널 본인 댓글은 eligibility가 이미 0으로 두지만, 표시가 어긋난 옛 행에 대비해 `exclusion_reason = 'own_channel'` 또는 `author_is_channel_owner = 1`이면 한 번 더 뺀다 (`is_audience`).
- 원문(`text`)과 `rationale`은 읽지 않는다. 표·화면 블록에 comment_id도 싣지 않는다.

### 2.2 범위(scope)

| scope | group_key | length_axis | 비고 |
|---|---|---|---|
| `video` | video_id | 그 영상의 묶음 (shorts / longform) | 화면 블록에는 싣지 않는다 |
| `channel` | `channel` | shorts / longform / all | Stage 09가 「나머지」를 계산하는 기준 |
| `type` | type_code | shorts / longform / all | 활성 체계마다(topic·segment), `taxonomy_id`로 구분. 유형 없는 영상은 넣지 않는다(`aggregate`와 같다) |
| `tier` | t1 / t2 / t3 / unknown | shorts / longform / all | 성과 층. 아래 2.4 |

길이 묶음은 `classify_videos.view_group`과 같다: shorts = 180초 이하, longform = standard + long.

### 2.3 비율 정의 (다중 라벨)

| 값 | 정의 |
|---|---|
| `n_comments` | 판정된 분석 대상 댓글 수. Reaction=None·UNKNOWN 포함 |
| `n_eligible_comments`, `labeled_ratio` | 판정이 있는 영상들의 분석 대상 댓글 수(판정 여부 무관)와 `n_comments ÷ n_eligible_comments` |
| `reaction_shares[Rk]` | Rk를 **가진** 댓글 ÷ `n_comments`. R1·R7을 함께 가진 댓글은 양쪽에 1씩 → 합이 1을 넘을 수 있다 |
| `none_share` | Reaction=None(`[]`) 댓글 ÷ `n_comments` |
| `unknown_share` | Reaction=`["UNKNOWN"]`(판정 불가) ÷ `n_comments` |
| `target_shares[T1..T5, UNKNOWN]` | 그 Target을 가진 댓글 ÷ `n_comments`. Reaction=None이라 Target이 빈 댓글 수는 `no_target_count` |
| `multi_reaction_count`, `review_flag_count` | 코드 2개 이상인 댓글 수, review_flag 수 (참고) |

None과 UNKNOWN은 다른 값이다(Phase 1 checkpoint Reaction 공통 규칙). 둘 다 분모에 남기고 따로 표시한다. 저장소에 없는 코드(R11 등)가 표에 있으면 조용히 세지 않고 오류를 낸다.

유형·층 묶음은 영상별 비율을 평균하지 않고 **댓글을 다시 센다** (`aggregate.type_comment_rollup`과 같은 원칙).

### 2.4 성과 층

- 기본: `video_metrics` 최신 실행의 `view_multiple` (normalize 정의). **provisional/legacy** 값이라 `performance_json`에 `canonical: false`, `canonical_status: "provisional_legacy"`, `source_run_id`를 남긴다.
- 동결 reference manifest를 줄 때만(`--reference-manifest`) `reference.canonical_view_multiple`을 쓴다. manifest 해시를 먼저 검증하고 `reference_manifest_sha256`, 규칙 버전·상태, `final_eligible`(규칙 승인 시에만 true), 영상별 status 개수를 남긴다.
- 층 = 길이 묶음마다 값이 있는 채널 영상 전체로 3분위(최근접 순위, 보간 없음 — `comment_sampling.tier_cutpoints`와 같은 규칙). 값이 없으면 `unknown`. 경계는 `performance_json.cutpoints`.

### 2.5 작은 표본 가림

`n_comments < 10`이면 `masked = 1`, 모든 비율 null, 수는 남기고 `basis`에 이유를 적는다. 10은 `aggregate.AggregateConfig.min_labels`와 같은 값이고, 비율만 비우고 수를 남기는 것도 `video_comment_metrics`와 같은 규칙이다.

### 2.6 표본 설계 출처

`observation_sampling`이 있으면(기본은 가장 최근 결정 실행, `--sampling-run`으로 지정) 묶음 영상의 완결성(`complete`/`capped`/…), 결정, 포함 확률 최소·최대, 정책 버전, 정렬, `label_cap`을 `sampling_json`에 남긴다. 없으면 `source: null`. **어느 경우에도 가중하지 않는다** (`weighted: false`). 영상과는 `video_id`로만 이어진다 — 주의: `observation_sampling`은 `observation_comments` 수집 기록이고, `comment_reactions`는 `comments` 표 댓글을 가리킨다(6장).

### 2.7 표 `reaction_metrics`

`backend/app/db/schema.sql`. PK = (channel_id, run_id, prompt_version, model, scope, taxonomy_id, group_key, length_axis). `taxonomy_id`는 type이 아니면 0 (PK 열에 NULL을 두지 않는다). 열: `n_videos`, `n_eligible_comments`, `n_comments`, `labeled_ratio`, `reaction_counts_json`, `reaction_shares_json`, `none_count`, `none_share`, `unknown_count`, `unknown_share`, `target_counts_json`, `target_shares_json`, `no_target_count`, `multi_reaction_count`, `review_flag_count`, `masked`, `basis`, `performance_json`, `sampling_json`, `metrics_version`(`reaction-metrics-v0.1`), `validation_status`(기본 `'검증 전 AI 판정'`), `computed_at`.

## 3. Stage 09 문장 — `app/interpret/reaction.py`

묶음(type·tier)과 **같은 길이 묶음의 채널에서 그 묶음을 뺀 나머지**를 비교한다. 나머지는 수로 빼서 만든다(비율끼리 빼지 않는다).

### 3.1 문장이 나가는 조건 (전부 만족, [제안])

| 조건 | 기본값 | 이유 |
|---|---|---|
| 묶음·나머지 각각 판정 댓글 수 | ≥ 50 | Stage 08의 10은 「비율을 적어도 되는가」, 이것은 「차이를 말해도 되는가」 |
| 묶음·나머지 각각 영상 수 | ≥ 5 | `aggregate.min_videos_headline`과 같다. 댓글은 영상 안에서 뭉친다 |
| 묶음·나머지 각각 UNKNOWN 비율 | ≤ 20% | 판정 불가가 많으면 다른 라벨 비율이 흔들린다 |
| 비율 차이 절댓값 | ≥ 10%p | 유의성 검정이 아니다. 댓글이 영상 안에서 독립이 아니라 댓글 단위 검정은 과신한다 |

- 대상 라벨: R1–R10, T1–T5. None·UNKNOWN 차이는 문장으로 만들지 않는다(판정 품질 신호).
- 성과 `unknown` 층은 해석하지 않는다. 조건 미달 묶음은 `withheld`에 이유와 함께 남는다.
- 기준값을 바꾸면 `INTERPRET_VERSION`(`reaction-interpret-v0.1`)을 올린다. 기준값은 결과(`thresholds`)와 함께 나간다.

### 3.2 문장 모양

```
[검증 전 AI 판정] 롱폼 「○○」 유형 영상 댓글에서 R7 내용 참여 비율이 채널의 나머지 롱폼 영상 댓글보다 높다 (60.0% 대 30.0%, 댓글 60건·영상 6편 대 60건·6편).
[검증 전 AI 판정] 조회 배수 상위 층(t3) 영상 댓글에서 대상이 T3 인물인 댓글 비율이 … 낮다 (…). 조회 배수는 임시값(provisional)이다.
```

관계만 말한다. 원인·조언·전망은 쓰지 않는다. 결과에는 네 가지 주의가 붙는다: 검증 전, 인과 아님, 다중 비교(묶음 × 15개 라벨), 비가중 비율.

## 4. 대시보드

### 4.1 evidence JSON `reaction_report` 블록

`backend/scripts/export_reaction_report.py --db <DB> [--render]` 가 DB를 **읽기 전용**(`mode=ro`)으로 열어 수치 → 문장 → 블록을 만들고 `docs/prototype/chim-evidence.json`에 `reaction_report` 키 하나만 넣는다(다른 키의 직렬화는 그대로). 버전을 안 주면 가장 최근 판정 조합 하나를 쓰고 나머지는 `source.versions_available`에 이름만 남긴다.

| 키 | 내용 |
|---|---|
| `validation_status`, `finding_input` | `"검증 전 AI 판정"`, `false` |
| `state` | `available` / `empty` |
| `empty_message` | `"아직 판정 결과 없음 — 판정 실행 후 채워짐"` |
| `codes` | Reaction 10, Target 6 (코드·이름) |
| `source` | DB 파일 이름, channel_id, prompt_version, model, versions_available, 판정 표 존재 여부, `n_labeled_comments` |
| `rows` | channel·type·tier 행 (video 행 제외). `empty`면 `[]` |
| `taxonomies`, `performance`, `sampling` | 유형 이름, 성과 정의, 채널 전체 표본 출처 |
| `interpretation` | 3장 결과 (sentences, withheld, thresholds, caveats) |
| `display_rules`, `how_to_fill` | 아래 표시 규칙, 채우는 명령 |

### 4.2 표시 규칙

1. Reaction 값이 나오는 모든 자리에 「검증 전 AI 판정」 배지를 단다 (한눈에 보기 카드, 참여와 반응 구간의 Reaction 절·해석 절, 분석 신뢰도 카드).
2. MVP Finding 카드로 올리지 않는다.
3. 비율 = 그 라벨을 가진 댓글 ÷ 판정된 분석 대상 댓글. 한 줄 합이 100%를 넘을 수 있다고 적는다.
4. Reaction 없음(None)과 판정 불가(UNKNOWN)를 다른 열로 둔다. Target은 T1–T5·판정 불가 6열 + 대상 없음 건수.
5. 가려진 묶음은 비율 칸을 「—」, 이름 아래 「표본 부족 · 최소 10건」.
6. **판정이 없으면 숫자를 만들지 않는다.** 코드 목록과 「아직 판정 결과 없음 — 판정 실행 후 채워짐」, 채우는 순서만 보인다.
7. 화면의 길이 필터 181~1200초·1200초 초과는 Reaction에서는 181초 이상(longform) 하나로 합쳐 보이고, 그렇다고 적는다.
8. 성과 층 표에는 조회 배수가 provisional인지 canonical인지 적는다.

지금 저장소의 `chim-evidence.json`은 `state: "empty"`다 (`chim.db`에 `comment_reactions` 표가 없음). 합성 블록으로 유형·Target·성과 층 표와 문장이 그려지는 것을 로컬에서 Edge headless로 확인했다(합성 데이터는 커밋하지 않았다).

## 5. 실제 숫자를 채우려면 (사람이 돌린다)

`backend/`에서. `<DB>`는 `./data/<채널>.db`.

```bash
python -m app.cli --db <DB> export-reaction-batch rx --out ./data/batches/reaction      # 비용 0
# 각 묶음 .md 를 Claude Code 로 판정해 rx_NNN.result.json 으로 저장
python -m app.cli --db <DB> import-reaction-batch rx_001 --out ./data/batches/reaction  # → comment_reactions
#   (또는 API: label-reactions --dry-run 으로 규모 확인 후 label-reactions — 돈이 나간다)
python -m app.cli --db <DB> reaction-metrics [--reference-manifest <manifest.json>]      # → reaction_metrics
python scripts/export_reaction_report.py --db <DB> --render                              # evidence JSON + report-prototype.html
```

## 6. 사람이 정할 것

- **해석 기준값 네 개**(50건 / 5편 / UNKNOWN 20% / 10%p)와 Stage 08 가림 기준 10건.
- **가중 여부.** 지금은 비가중. `observation_sampling.inclusion_prob`(영상)와 `label_cap` 추출(댓글)을 반영한 가중 비율을 함께 낼지.
- **침착맨 35편 표본의 판정 경로.** 확장 표본 댓글은 `observation_comments`에 있고, 판정기 DB 경로(`label_reactions.pending`)와 `comment_reactions` 외래키는 `comments` 표를 본다. `chim.db`의 `comments`는 옛 2편 400건뿐이다. observation 댓글을 `comments`로 옮길지, 판정 대상을 observation 표로 넓힐지 정해야 채널 수준 수치가 의미를 갖는다.
- **Reaction UNKNOWN을 분모에 둘지.** 지금은 둔다(수가 남아 있어 다른 분모로 다시 계산할 수 있다).
- **나머지 비교 대신 채널 전체 비교**가 필요한지. 지금은 묶음 자신을 뺀 나머지와 비교한다.
- 다중 비교를 어떻게 다룰지(문장 수 상한, 반복 표본 확인 등).
- 성과 층을 3분위로 둘지, 조회 배수 1.0 기준 고정 구간으로 둘지.
