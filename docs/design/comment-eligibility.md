# 댓글 분석 포함 여부 (analysis eligibility)

근거: [Reaction Phase 1 checkpoint](../reaction-phase1-checkpoint.md)의 **H2**(명시적 timestamp는 raw/metadata로 보존, 추정 금지)와 **H3**(raw 보존과 분석 포함 여부 분리).
구현: `backend/app/pipeline/eligibility.py`, 테스트: `backend/tests/test_eligibility.py`.
Phase 2 전용 수집기(`backend/scripts/phase2_collect.py`)의 `comment_record`가 먼저 같은 개념을 썼고, 본 파이프라인 수집기로 개념만 옮겼다. Phase 2 스크립트와 봉인 표본은 건드리지 않았다.

## 원칙

- **제외는 삭제가 아니라 표시다.** 수집한 댓글은 전부 `comments`(와 `observation_comments`)에 원문 그대로 남는다.
- 시청자 반응(Audience Behavior/Reaction)을 세는 집계만 `analysis_eligible = 1` 인 행을 쓴다.
- 수집 사실(받아둔 댓글 수, API 댓글 수 대비 수집 비율, thread·답글 수집 상태, 작성자 결측률)은 raw 전체로 센다. 시청자 행동이 아니라 수집 기록이기 때문이다.
- **의심만으로는 제외하지 않는다.** 직원·부계정·사칭·상업 계정으로 보인다는 이유, 반복 의심(`suspect_repeat`), 모델 선별의 `drop`은 제외 사유가 아니다.

## 필드

`comments` 표에 붙은 열이다. `observation_comments`에는 `parent_id`가 이미 있어 나머지 다섯 열이 같은 이름으로 붙는다.

| 열 | 값 | 뜻 |
|---|---|---|
| `parent_id` | TEXT / NULL | 답글이면 부모 댓글 id. 1단계 수집기(`commentThreads`)는 최상위 댓글만 받으므로 지금은 항상 NULL |
| `author_is_channel_owner` | 1 / 0 / NULL | 작성자 채널 = 영상 채널이면 1. 작성자나 영상 채널을 모르면 NULL (0은 "아님을 확인함"이라 쓰지 않는다) |
| `analysis_eligible` | 1 / 0 | 시청자 반응 집계에 넣는가. 기본값 1 |
| `exclusion_reason` | NULL / 아래 목록 | 왜 뺐는가. `analysis_eligible = 1` 이면 항상 NULL |
| `exclusion_source` | `collect` / `migration` / `comment_screens:<prompt_version>/<model>` | 누가 이 판정을 내렸는가 |
| `timestamps_json` | JSON 배열, 기본 `[]` | 원문에 적힌 timestamp. `[{"text": "32:19", "seconds": 1939}]` |

## 제외 사유 (닫힌 목록)

| `exclusion_reason` | 규칙 | 언제 정해지나 | H3 문장 |
|---|---|---|---|
| `misplaced_data` | API가 돌려준 댓글의 `videoId` ≠ 요청한 영상 | 수집 시점 | 잘못 수집된 데이터 → raw 보존, 분석 제외, 사유 기록 |
| `own_channel` | `author_channel_id` = 영상의 `channel_id` | 수집 시점 (옛 DB는 마이그레이션) | 영상 채널 자신의 댓글 → raw 보존, 집계 제외 |
| `spam_confirmed` | 해당 댓글의 **가장 최근 규칙 판정**(`comment_screens`, `model='rule'`)이 `promo` | `rules --save` 직후 | 확인된 spam → raw 보존, 분석 제외, 사유 기록 |

- 우선순위는 `misplaced_data` > `own_channel` > `spam_confirmed`. 먼저 붙은 사유를 뒤의 것이 덮지 않는다.
- `spam_confirmed`는 규칙을 다시 돌리면 다시 계산된다. 새 규칙 버전이 `keep`이면 표시가 풀린다. `exclusion_source`에 `comment_screens:rules-v1/rule`처럼 판정 행의 키가 남아, `comment_id`와 함께 근거 행을 다시 찾을 수 있다.
- `irrelevant`(선점 댓글 "1등" 등)는 규칙 문서대로 스팸이 아니므로 사유 목록에 없다. 라벨 대상에서 빠지는 것은 원래대로 규칙 판정(`SENDABLE`)이 맡는다.
- 사유를 늘릴 때는 이 표와 `eligibility.EXCLUSION_REASONS`를 함께 고친다.

## 답글과 부모

판정은 댓글마다 독립이다. `decide()`는 부모의 판정을 입력으로 받지 않는다.

- 채널이 단 고정 댓글(부모)은 `own_channel`로 빠지고, raw에 남아 답글의 맥락이 된다.
- 그 아래 시청자 답글은 `analysis_eligible = 1`이다 (H3: 실제 viewer reply는 분석 가능).
- 채널이 직접 단 답글은 그 답글만 `own_channel`이다.

## timestamp (H2)

- 원문에 **글자 그대로** 있는 `m:ss`, `mm:ss`, `mmm:ss`, `h:mm:ss`만 뽑는다. 앞뒤에 숫자나 콜론이 붙어 있으면 뽑지 않는다.
- 초·분 자리가 60 이상이면 시각이 아니므로 버린다 (`1:99`). "3분 20초" 같은 서술형은 뽑지 않는다.
- 같은 문자열은 한 번만, 나온 순서대로 남긴다.
- **영상 길이로 거르지 않는다.** 길이를 넘는 값을 버릴지는 읽는 쪽이 정한다 (`observable.timestamps`는 여전히 길이로 거른다).
- timestamp가 없는 댓글에 장면이나 시각을 추정해 넣지 않는다.
- `comment_features.timestamps_json`(추출기 버전별 초 배열, 아직 채우는 코드 없음)과는 별개다. 이쪽은 수집 시점의 raw metadata다.

## 옛 DB

`connect()`가 없는 열을 붙이고(`LATE_COLUMNS`), `analysis_eligible`을 **막 붙인 경우에만** 한 번 채운다.

- `author_is_channel_owner`와 `own_channel`: `videos.channel_id`와 비교해 채운다. `exclusion_source = 'migration'`.
- `misplaced_data`: 옛 행에는 API의 `videoId`가 저장돼 있지 않아 알 수 없다. 추정하지 않고 eligible, 사유 NULL로 둔다.
- `timestamps_json`: 원문에서 다시 뽑는다.
- `spam_confirmed`: 이미 저장된 규칙 판정이 있으면 반영한다.

`observation_comments`는 `observable_collect.ensure_schema()`가 같은 방식으로 채운다.

## 이 표시를 보는 곳

| 위치 | 바뀐 것 |
|---|---|
| `label_comments.pending` (API 라벨 대상) | `analysis_eligible = 1`만 |
| `cli export-batch` (오프라인 라벨 대상) | DB에서 읽을 때 제외 행을 뺀다. 표본 파일(열 없음)은 포함으로 본다 |
| `engagement.read_label_counts`, `engagement.run` | 라벨 집계와 분모(`labeled_ratio`)를 분석 대상 댓글로 |
| `aggregate._read_labels`, `aggregate.run` | 영상별 라벨 집계와 분모를 분석 대상 댓글로 |
| `observable.build` | `unique_commenters`, `observed_repeat_share`, `participant_breadth`, timestamp cluster, 옛 감성 라벨 수를 분석 대상 댓글로. `eligible_comments`, `excluded_comments`, `summary.eligible_comment_n` 추가 |

그대로 둔 것: `cli rules`(스팸 판정은 전체 댓글을 봐야 한다), `screen_comments.pending`(규칙 통과분만 보내므로 확정 스팸은 이미 빠져 있다), `exports.fetch`, `scripts/resume_channel_analysis.py`, 수집 커버리지 계열 지표.

## 지표 변화

- `comment_engagement.labeled_ratio`, `video_comment_metrics`의 basis 분모: "수집 댓글 수" → "분석 대상 댓글 수". 제외 행이 있는 영상에서만 값이 달라진다(분모가 줄어 비율이 오른다).
- 긍정·부정·중립 수, `approval`, `contention`, 비율: 제외 행에 이미 라벨이 붙어 있던 경우에만 달라진다.
- basis 문구 "수집 N건" → "분석 대상 N건".
- 옛 DB에서 `own_channel`·확정 스팸 행이 없으면 모든 수치가 이전과 같다. 저장소의 `backend/data/carden.db` 사본으로 확인한 결과 댓글 400건 중 제외 0건(수치 변화 없음), 원문 timestamp가 있는 댓글 23건이었다.

## 남은 질문

- 모델 선별(`comment_screens`, `screen-v1`)의 `drop`을 확정 스팸으로 볼 기준. 지금은 `drop`의 이유가 스팸 외에도 있어 제외하지 않는다.
- `misplaced_data` 행에 API가 보고한 `videoId` 자체를 따로 남길지. 지금은 사유만 남는다.
- 1단계 수집기가 답글(`comments.list`)까지 받을지. 받게 되면 `parent_id`가 채워지고 같은 규칙이 그대로 적용된다.
