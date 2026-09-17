# 댓글 표본 정책 — 채널 단위 영상·댓글 선정

- 작성일: 2026-09-17
- 상태: **제안 (사람 승인 전)**. 프리셋 선택과 예산 상한은 6장의 결정이 필요하다.
- 구현: `backend/app/pipeline/comment_sampling.py` (순수 함수),
  `backend/app/pipeline/observable_collect.py` 의 `record_plan` / `collect_planned` (선택 경로)
- 테스트: `backend/tests/test_comment_sampling.py` (합성 데이터만)
- 근거 문서: [Control Tower checkpoint](../reports/control-tower-checkpoint-2026-09-15.md),
  [Outcome-side audit](../reports/outcome-side-audit-2026-09-15.md),
  [관측 변수 우선 계획](observable-first-analysis-plan.md), [결정 기록](youtube-trend-decisions.md),
  [Reaction closeout·재개](../reaction-track-closeout-2026-09-17.md),
  [Phase 1 checkpoint](../reaction-phase1-checkpoint.md)

이 문서는 정책과 그 근거·비용 추정을 적는다. 실제 수집·판정을 실행하지 않았고, 유료 API를 부르지
않았고, 댓글 원문을 열지 않았다. 아래 금액은 전부 **추정치**다.

---

## 1. 문제

지금까지 채널마다 댓글은 영상 2편에서만 받았다 (영상당 200개, Phase 2는 50개).
침착맨 Development 90편 중 댓글 관측이 있는 영상은 8편(8 `capped`, 82 `not_sampled`)이라
`unique_commenters`·`participant_breadth`·`threads`·`reply_rate` 같은 댓글 기반 지표가
coverage caveat 또는 NOT_READY 상태다. 기존 `sample_ids`는 게시 월 × 길이축에서 시간순
1/3·2/3 위치를 고르는 규칙이라 **유형과 성과 수준을 보지 않는다.**

필요한 것은 두 가지다.

1. 유형 × 길이 × 성과 수준을 고루 덮는 영상 선정 — 어느 칸도 0편이 되지 않게.
2. 영상마다 "무엇을, 어떤 순서로, 몇 개까지 받았고, 끝까지 받았는가"를 남기는 기록 —
   표본이 비확률 표본이라는 사실을 숨기지 않고 가중치·민감도 분석으로 되돌릴 수 있게.

## 2. 영상 선정

### 2.1 자격 (먼저 거른다)

순서대로 보고 처음 걸린 사유 하나를 `reason`에 남긴다. 제외된 영상도 결정 줄을 받는다.

| 사유 | 조건 | 비고 |
|---|---|---|
| `comments_disabled` | 댓글 사용 중지 | 실패가 아니라 건너뛸 사유 (결정 기록 2장) |
| `live` | `is_live` 참 (`exclude_live=True`일 때) | **주의**: `classify_live`는 아직 판정하지 않고 항상 0을 돌려준다(결정 기록 3장 미결). 지금은 이 규칙이 사실상 아무것도 거르지 않는다 |
| `comment_count_unknown` | 수집 시점 댓글 수 없음 | |
| `below_comment_threshold` | `comment_count < min_comments` (기본 20) | `comment_count`는 답글 포함 값이다 |

`min_comments`는 댓글 수라는 **행동 지표**로 자르는 규칙이라, 댓글이 적은 영상의 반응은
표본에서 체계적으로 빠진다. 제외 편수는 결정 줄로 남으므로 "몇 편이 이 이유로 빠졌는가"는
언제나 셀 수 있다. 임계값은 사람이 정할 항목이다(6장).

### 2.2 split 규칙

split은 **읽기만 한다.** 침착맨 300편의 Discovery 90 / Development 90 / Holdout 120을 다시
섞지 않는다(Control Tower 결정). split마다 규칙 하나를 둔다. split이 없는 채널은 `*` 규칙을 쓴다.

| mode | 뜻 | 성과값 사용 |
|---|---|---|
| `census` | 자격 있는 영상 전부 | 층 기록만 (선정에 영향 없음) |
| `stratified` | 유형 × 길이 × 성과 층으로 `target` 편 | 사용 |
| `blind` | 유형 × 길이로만 `target` 편 | **사용하지 않음** |
| `skip` | 이번 실행에서 받지 않음 | — |

**Holdout 보호 (코드로 강제한다)**

- `holdout_splits`(기본 `holdout`)에 `stratified`를 걸면 `ValueError`다.
- 성과 층 경계는 holdout이 **아닌** 영상의 성과값으로만 자른다. holdout 영상의 성과값은
  들어와도 읽지 않고 층을 `blind`로 둔다.
- 테스트 `test_holdout_performance_never_changes_the_plan`: holdout 영상의 성과값을 임의로
  바꾸거나 지워도 경계와 모든 결정 줄이 바이트 단위로 같다.

holdout 댓글을 **수집**하는 것은 holdout을 여는 것이 아니다. 봉인 해제(`--unseal-holdout`)는
Finding 실행 단계의 일이고, 이 정책은 거기에 관여하지 않는다. 다만 holdout 댓글 **판정 비용**을
지금 쓸지는 6장의 결정 항목이다.

### 2.3 층화

- **칸(cell)** = `type_code` × 길이 묶음. 유형이 없으면 `UNTYPED`.
  길이 묶음은 `shorts` → `shorts`, `standard`·`long`·`longform` → `longform`, 그 밖은 `unknown`.
  결정 기록의 "쇼츠 / 롱폼 두 판"과 같은 구분이다.
- **층(stratum)** = 칸 × 성과 층. 성과 층은 `performance_field`(기본 `view_multiple`)를 길이 묶음마다
  `n_tiers`(기본 3) 분위로 나눈 `t1`(하위) … `t3`(상위). 값이 없으면 `unknown`
  (침착맨 Development는 90 중 81편만 numeric). 분위 경계는 보간 없는 최근접 순위 값이다.
- **배분**
  1. 칸마다 `min(min_per_cell, 칸 크기)`를 먼저 준다 (기본 2).
  2. 남은 편수는 칸 크기 비례로 한 편씩 D'Hondt 방식(크기 / (받은 수 + 1)이 가장 큰 칸, 동률은
     이름순)으로 준다. 이 방식은 target을 늘렸을 때 어느 칸의 몫도 줄지 않는다.
  3. 칸 안에서는 편수가 층 수 이상이면 층마다 1편을 먼저 주고 나머지를 같은 방식으로 나눈다.
     (칸 몫이 층 수를 막 넘는 경계에서는 큰 층의 몫이 한 편 줄 수 있다 — 2번의 단조성은 칸 단위다.)
  4. 최소치 합이 target을 넘으면 **최소치를 지키고** 경고를 남긴다(target 초과).
     칸 크기가 최소치보다 작으면 전부 뽑고 경고를 남긴다.
- **층 안의 순번** = `sha256(seed \0 split \0 video_id)` 오름차순. `feature_discovery/split_dataset.py`와
  같은 방식이다. 입력 순서와 무관하고, 같은 seed면 언제나 같다.
- **포함 확률** `inclusion_prob` = 층에서 뽑힌 편수 / 층의 자격 있는 편수. census는 1.0.
  층별 가중치(1/p)로 채널 전체 추정치를 되돌리거나, 가중·비가중 결과를 나란히 보는 데 쓴다.

**성과로 층화하는 것의 한계**

- 성과 층화는 "성과 수준마다 댓글 관측이 있다"를 보장하려는 것이지, 성과와 행동의 연관을
  표본 설계로 만들어 내려는 것이 아니다. 층마다 선정 확률이 다르므로 **연관 분석은 포함 확률을
  함께 써야** 한다(가중 또는 층 고정).
- 기본 성과값 `view_multiple`은 현재 cross-split peer로 계산된 **provisional/legacy** 값이다
  (Control Tower C 트랙). holdout 성과를 직접 읽지는 않지만, 비-holdout 영상의 배수 분모에 holdout
  peer의 조회수가 섞여 있을 수 있다. 별도 reference population 기반 canonical normalization이
  생기면 `performance_field`를 그 값으로 바꾼다. 이 정책은 그 계산을 대신하지 않는다.
- Development는 권장 프리셋에서 `census`라 성과 층이 **선정에 쓰이지 않는다.** Finding이 소비하는
  split의 표본이 성과에 의존하지 않게 하려는 선택이다.

## 3. 영상당 댓글

### 3.1 수집 상한과 판정 상한을 분리한다

| 값 | 뜻 |
|---|---|
| `collect_cap` | 받을 원댓글 상한. 페이지 수 = `ceil(collect_cap / 100)` |
| `label_cap` | Claude 판정에 보낼 원댓글 상한. 수집분에서 `sha256(seed \0 video_id \0 comment_id)` 순서로 고른다 (`label_subset`) |

수집은 YouTube 유닛(무료, 일일 한도)이고 판정은 돈이다. 둘을 같은 숫자로 두면 비용 때문에 수집을
줄이게 되고, 수집이 줄면 아래 3.2의 순서 편향이 커진다. 그래서 **넉넉히 받고, 판정은 해시로 균등하게
덜어 낸다.** 수집 상태가 `complete`면 판정 표본은 수집 시점 원댓글 전체에서의 균등 추출이고,
`capped`면 수집된 앞부분 안에서의 균등 추출일 뿐이다 — 이 구분은 `completeness`로 언제나 드러난다.

### 3.2 정렬 — `order=time`과 `order=relevance`

| | `time` (기본) | `relevance` |
|---|---|---|
| 무엇을 받나 | 최신 원댓글부터 | YouTube가 순위 매긴 원댓글부터 |
| 상한에 걸렸을 때 편향 | **늦게 단 사람** 쪽. 오래된 영상은 게시 직후 반응이 빠지고 재방문·알고리즘 유입 시청자가 남는다. 수집 시점이 다르면 같은 영상도 다른 구간을 본다 | **노출 편향**. 좋아요 많고 일찍 달린 댓글, 답글 많은 댓글, 채널 운영 신호가 반영된다. 시청자가 실제로 **보는** 댓글에 가깝지만 무작위도 대표도 아니다 |
| 재현성 | 같은 시점이면 순서가 정해져 있다. `complete`면 편향 없음 | 순위 알고리즘이 공개되지 않았고 시간에 따라 바뀐다. 같은 요청이 나중에 다른 결과를 낸다 |
| 이 저장소의 이력 | 결정 기록: "시간순, 관련도순의 편향 회피" | Phase 2: relevance-ranked exposure sample로 명시 |

기본은 `time`이다. **YouTube 클라이언트의 `order="time"` 기본값은 바꾸지 않았다**; 정책의 `order`는
`collect_sample(order=...)` 인자로만 흐른다. `relevance`를 쓰면 결과 문서에 "노출 표본"이라고 적는다.

정렬 편향을 줄이는 가장 확실한 방법은 **끝까지 받는 것**이다(`complete`). 그래서 `collect_cap`은
대부분의 영상이 `complete`가 되도록 잡고(아래 5.3: 카더정원 댓글 수 중앙값 87, 500 이상 22%),
판정 비용은 `label_cap`으로 통제한다.

### 3.3 원댓글과 답글

- 표본의 단위는 **원댓글(thread)** 이다. `label_cap`은 원댓글만 센다. Phase 2와 같은 단위다.
- 답글 수는 `commentThreads`의 `totalReplyCount`로 **모든 수집 thread에 대해 추가 비용 없이** 기록된다
  (`observation_threads.api_replies`).
- 답글 본문은 thread마다 `comments.list` 1유닛이 든다. 원댓글이 수백 개면 이것이 유닛 대부분이다.
  그래서 답글은 **수집 순서 앞의 `reply_threads`개 thread**에 대해서만, thread당 `reply_pages`
  페이지까지 받는다. 나머지 답글 있는 thread는 `replies_not_fetched`로 남는다.
- `time` 순서의 앞 thread는 최신이라 답글이 적은 편이다 — 답글 본문 표본은 큰 thread를 덜 담는다.
  답글 **수** 기반 지표는 `api_replies`로 완전하지만, 현재 `observable.py`의 `reply_rate`·
  `max_thread_size`는 **수집된** 답글로 계산하므로 이 정책 아래에서는 하한값이다.
  `reply_incomplete_threads`가 그만큼 올라가 표시된다. 계산식 변경은 이번 범위 밖이다(7장).

### 3.4 완결성 어휘

영상마다 `observation_sampling.completeness` 하나:

| 값 | 뜻 |
|---|---|
| `complete` | 원댓글 페이지가 다 떨어졌다 (그 시점 원댓글 전부) |
| `capped` | `collect_cap`에서 멈췄다. 다음 페이지 토큰은 `observation_collection.next_page_token` |
| `not_sampled` | 결정이 `not_sampled` 또는 `excluded` (사유는 `decision`/`reason`) |
| `disabled` | 선정됐지만 수집 시 댓글 사용 중지 응답 |
| `error:<예외>` | 수집 중 오류 (할당량 소진 포함). 다시 실행하면 이 영상부터 다시 받는다 |
| `pending` | 선정됐고 아직 받지 않음 |

thread 단위는 기존 `observation_threads.status`(`complete` / `capped` / `count_changed` /
`unknown_reply_count`)에 `replies_not_fetched`가 더해진다.

## 4. 기록과 재현성

새 테이블 **`observation_sampling`** 하나만 추가했다. `comments` 테이블과 기존 observation 테이블의
스키마는 바꾸지 않았다.

| 열 | 내용 |
|---|---|
| `run_id`, `video_id` | PK |
| `split`, `stratum`, `tier`, `mode` | 어느 칸·층·규칙으로 판단했나 |
| `decision`, `reason`, `inclusion_prob`, `rank_key` | 결과, 사유, 포함 확률, 해시 순번 |
| `ordering`, `collect_cap`, `top_pages`, `reply_threads`, `reply_pages`, `label_cap` | 영상에 적용한 상한 |
| `policy_name`, `policy_version`, `seed`, `decided_at` | 정책 식별 (`comment-sampling-v0.1`) |
| `completeness`, `collected_at` | 3.4의 상태와 수집 시각 |

`observation_runs.policy_json`에는 정책 전체(JSON), 성과 층 경계, 경고가 들어간다. 같은 입력
메타 + 같은 `policy_json`이면 `plan()`이 같은 결정을 낸다. 댓글 판정 결과의 재현 키
(대상, prompt_version, model)는 기존 규칙 그대로다.

재개: `collect_planned`는 같은 run에서 `complete`/`capped`/`disabled`인 영상을 건너뛴다. 결정 줄은
`INSERT OR IGNORE`라 재개 중 결정이 바뀌지 않는다.

## 5. 할당량과 비용 (추정)

### 5.1 가정

| 항목 | 값 | 근거 |
|---|---|---|
| YouTube 일일 한도 | 10,000유닛, 클라이언트가 95%에서 멈춤 → 실사용 9,500 | `youtube.py` |
| `commentThreads.list` / `comments.list` / `videos.list` | 호출당 1유닛. 페이지당 최대 100 / 100 / 50 | `youtube.py` `COST` |
| 메타 갱신 | 300편 `videos.list` = 6유닛 | 50편당 1 |
| 기본 모델 | `claude-sonnet-5` | 결정 기록, `claude.py DEFAULT_MODEL` |
| 단가 ($/백만 토큰, 입력/출력) | Sonnet 5: 2 / 10, Opus 5: 5 / 25, Haiku 4.5: 1 / 5 | Anthropic 공개 단가(2026-06 기준 스냅샷). **청구 전 재확인 필요.** 저장소 `claude.py PRICES`에는 Opus 5만 확인값으로 있다 |
| Batches API | 50% 할인 | 아직 저장소에 붙이지 않음 (`claude.py` 주석) |
| 입력 토큰 / 원댓글 | **165** | 프롬프트 `comment_label.md` 4,555바이트 ≈ 2,000토큰을 묶음 20건으로 나눠 100 + 댓글 본문(카더정원 400건 평균 32자, 중앙값 20자, p90 57자 — 길이만 집계) ≈ 50 + 줄 번호·제목 등 ≈ 15 |
| 출력 토큰 / 원댓글 | **80** | JSON 한 항목(번호·감성·확신도·반어·주제) ≈ 40에 여유. Reaction·Target 판정기는 항목이 더 크다 |
| 사고(thinking) 토큰 | **위 80에 넣지 않음** | Sonnet 5는 `thinking`을 생략하면 adaptive로 돈다. `claude.py`는 이 인자를 넘기지 않는다. 아래 5.4 민감도 참고 |

추정식 (`comment_sampling.estimate`):

```
원댓글 페이지 = Σ_선정 max(1, ceil(min(comment_count, collect_cap) / 100))
답글 호출 상한 = Σ_선정 reply_threads × reply_pages
판정 건수     = Σ_선정 min(comment_count, label_cap)
비용          = 판정 건수 × (165 × 입력단가 + 80 × 출력단가) / 1,000,000
```

Sonnet 5 기준 원댓글 1건 = 165 × 2 + 80 × 10 = 1,130 / 1,000,000 = **$0.00113** (Batches $0.000565).

### 5.2 프리셋 — 침착맨 모양 300편 (Discovery 90 / Development 90 / Holdout 120), 상한 시나리오

상한 시나리오 = 모든 영상이 자격 있고 댓글 수가 상한 이상. 실제로는 더 적게 든다(5.3).

| | light | **standard (추천, 미승인)** | full |
|---|---|---|---|
| Development | census 90 | census 90 | census 90 |
| Discovery | skip | stratified 45 | census 90 |
| Holdout | skip | blind 60 | census 120 |
| split 없는 채널 (`*`) | stratified 60 | stratified 150 | census |
| 선정 영상 | 90 | 195 | 300 |
| `collect_cap` (페이지) | 100 (1) | 500 (5) | 2,000 (20) |
| `reply_threads` × `reply_pages` | 0 × 0 | 20 × 1 | 50 × 2 |
| `label_cap` | 50 | 100 | 300 |

유닛:

| | light | standard | full |
|---|---:|---:|---:|
| 원댓글 페이지 | 90 × 1 = 90 | 195 × 5 = 975 | 300 × 20 = 6,000 |
| 답글 호출 상한 | 0 | 195 × 20 × 1 = 3,900 | 300 × 50 × 2 = 30,000 |
| 메타 갱신 | 6 | 6 | 6 |
| **합계 상한** | **96** | **4,881** | **36,006** |
| 필요 일수 (9,500/일) | 1 | 1 | 4 |

판정 (Sonnet 5):

| | light | standard | full |
|---|---:|---:|---:|
| 판정 건수 | 90 × 50 = 4,500 | 195 × 100 = 19,500 | 300 × 300 = 90,000 |
| 입력 토큰 | 742,500 | 3,217,500 | 14,850,000 |
| 출력 토큰 | 360,000 | 1,560,000 | 7,200,000 |
| 동기 호출 | 4,500 × $0.00113 = **$5.08** | 19,500 × $0.00113 = **$22.04** | 90,000 × $0.00113 = **$101.70** |
| Batches | $2.54 | $11.02 | $50.85 |
| 참고: Opus 5 동기 | $12.71 | $55.09 | $254.25 |
| 참고: Haiku 4.5 동기 | $2.54 | $11.02 | $50.85 |

full에서 `label_cap`을 없애고 수집분 전부(최대 300 × 2,000 = 600,000건)를 판정하면
600,000 × $0.00113 ≈ $678 (Batches ≈ $339)이다.

### 5.3 실제 댓글 수 분포를 넣으면 — 카더정원 300편 메타

`backend/data/carden.db`의 영상 메타(유형 300/300, `view_multiple` 291/300, 수집 시점 댓글 수)만 넣어
`estimate`를 돌렸다. 댓글 원문은 읽지 않았다. 카더정원에는 split이 없으므로 **추정용으로만**
video_id 해시로 30/30/40 가짜 split을 만들었다(실제 split이 아니다). 댓글 수 중앙값 87,
25% 33, 75% 391, 500 이상 22%, 2,000 이상 3%, 20 미만 13%.

| | light | standard | full |
|---|---:|---:|---:|
| 제외 (`below_comment_threshold` 등) | 38 | 38 | 38 |
| 선정 영상 | 74 | 179 | 262 |
| 유닛 상한 | 80 | 4,056 | 27,262 |
| 판정 건수 | 3,354 | 13,814 | 42,404 |
| Sonnet 5 동기 / Batches | $3.79 / $1.90 | $15.61 / $7.80 | $47.92 / $23.96 |

standard에서 경고 5건(최소치에 못 미치는 칸)이 났다 — 유형 14개 × 길이 2묶음 중 편수가 적은 칸이다.
답글 호출은 여전히 상한값(선정 × 20)이라 실제로는 더 적다. 침착맨은 영상당 댓글이 카더정원보다 많을
가능성이 높아 5.2의 상한에 더 가까울 것이다 — 확인되지 않은 추정이다.

### 5.4 민감도

- **사고 토큰**: 원댓글당 출력이 100토큰 늘어 180이 되면 1건 = 165 × 2 + 180 × 10 = $0.00213.
  standard 19,500건 → $41.54 (Batches $20.77). full 90,000건 → $191.70.
- **프롬프트 캐시**: `claude.py`는 system에 `cache_control`을 붙인다. system(≈2,000토큰)이 모델의 최소
  캐시 길이를 넘으면 입력 비용의 절반 이상이 캐시 읽기 단가로 내려간다. 위 표는 캐시 할인을 **넣지 않았다.**
- **판정기 교체**: Reaction·Target 판정 프롬프트(Phase 3)는 아직 크기가 정해지지 않았다. 입력 토큰이
  두 배면 입력 비용 부분만 두 배다(Sonnet 5 standard: 입력 $6.44 → $12.87).

## 6. 사람이 정할 것

아래는 추천이며 **승인된 결정이 아니다.** 코드의 `PRESETS`는 이 추천값을 담고 있을 뿐, 어느 실행에도
자동으로 쓰이지 않는다(`collect_planned`는 명시적으로 불러야 돈다).

| # | 결정 | 추천 기본값 | 이유 / 대안 |
|---|---|---|---|
| 1 | 프리셋 | **standard** | Development 90편 전부의 `not_sampled`를 없애고, Discovery·Holdout에 유형·길이 칸을 덮는 표본을 남긴다. 하루 할당량 안(상한 4,881유닛), Sonnet 5 동기 상한 약 $22. light는 Discovery 발견 작업에 댓글을 주지 못하고, full은 4일·약 $100이 든다 |
| 2 | 채널당 판정 예산 상한 | **채널당 $30 (Sonnet 5, 동기 기준)**, 넘으면 `label_cap`을 낮추고 멈춰서 묻기 | 사고 토큰 민감도(5.4)를 고려한 standard 상한 + 여유. Batches를 붙이면 같은 상한으로 약 2배를 판정할 수 있다 |
| 3 | Holdout 댓글을 지금 판정할지 | **수집만, 판정은 봉인 해제 결정 때** | 수집은 유닛만 든다. 판정 비용(standard에서 60 × 100건 ≈ $6.78)은 holdout 검증이 승인될 때 쓴다 |
| 4 | `min_comments` | 20 | 낮추면 댓글 적은 영상의 반응이 들어오지만 판정 1건당 정보가 적다. 높이면 행동 지표 기준 선택 편향이 커진다 |
| 5 | `order` | `time` | 결정 기록과 같다. `relevance`는 노출 표본 연구가 목적일 때만 |
| 6 | `min_per_cell` / `n_tiers` | 2 / 3 | 유형 수가 많은 채널(카더정원 14개)은 칸이 잘게 쪼개져 최소치 경고가 난다. 유형을 합칠지는 유형 체계 쪽 결정이다 |
| 7 | 성과 층에 쓸 값 | 지금은 provisional `view_multiple` | canonical normalization(C 트랙)이 생기면 교체 |
| 8 | 판정 모델 | `claude-sonnet-5` (결정 기록) | 바꾸면 해석 키가 달라져 새로 쌓인다. 첫 적용 시 같은 묶음을 두 모델로 비교하라는 기존 권고 유지 |

## 7. 구현 범위와 하지 않은 것

**구현**

- `comment_sampling.py`: `SamplingPolicy`/`SplitRule`, `PRESETS`, `plan()`(자격 → split 규칙 → 층화 →
  영상별 결정), `tier_cutpoints`, `apportion`, `label_subset`, `estimate`.
- `observable_collect.py`:
  - `collect_sample`에 키워드 인자 `top_pages`, `order`, `max_reply_threads`를 더했다.
    **기본값에서는 예전과 같은 호출·같은 상태값이다** (`test_collect_sample_defaults_unchanged`).
  - `observation_sampling` 테이블, `record_plan`, `collect_planned`, `sync_completeness`.
- 테스트 24개: 제외 사유, census, skip, 층화 target·칸 최소치·층 대표성, 최소치 초과 경고, 포함 확률,
  D'Hondt 배분의 단조성, holdout 성과 불변성·stratified 거부, split 불변, 결정성(입력 순서·seed),
  `label_subset`, 프리셋 편수, 예산 산식, 수집 연결(페이지·답글 thread 상한·재개·완결성 기록).

**하지 않은 것**

- 실제 수집·판정 실행, 유료 API 호출, 댓글 원문 열람.
- `YouTubeClient`의 `order="time"` 기본값, `comments` 테이블 스키마, `backend/scripts/phase2_collect.py`,
  `backend/fixtures/phase2-reaction/`, Reaction 문서 변경.
- `backend/scripts/collect_chim_observable.py`는 그대로 두었다. 이 정책으로 돌리려면 스크립트에서
  `plan(videos, preset("standard"))` → `collect_planned(c, yt, run, plan)`를 부르면 된다. 이때 영상 dict에
  `split`(split CSV), `type_code`, `view_multiple`, `comment_count`를 붙여야 한다.
- `observable.py`의 `reply_rate`·`max_thread_size`를 `api_replies` 기반으로 바꾸는 일(3.3), 포함 확률 가중
  집계, Batches API 연결.
