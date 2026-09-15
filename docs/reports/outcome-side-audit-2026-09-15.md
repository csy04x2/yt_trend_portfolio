# Outcome-side audit — Finding input contract

2026-09-15 · 기준 commit `27b0f5d` (`docs: close comment signal probe and audit finding readiness`)
· branch `integration/feature-discovery-observable`

## 검증 범위

지정 저장소 경로, 브랜치, 최근 commit, 실제 소스 존재를 확인했다.
소스와 합성 테스트만 조사했으며 제시된 audit 사실과 충돌은 없다.
실제 실험 데이터/결과, Holdout 파일은 열거나 실행하지 않았다.

## Data lineage

1. `app/pipeline/observable_collect.py`는 별도 run-scoped observation 테이블에
   댓글·thread·수집 상태를 저장한다. `sample_ids`는 게시 월/길이축별 시간순
   1/3·2/3 위치의 영상을 선택한다. `collect_sample`은 최신 최상위 댓글 한 페이지
   (최대 100개)를 가져오고 각 sampled thread의 답글은 기본 최대 2페이지를 가져온다.
   API 페이지당 답글 상한은 100개다. 따라서 모든 댓글 합계가 100개 이하라는 뜻은 아니다.
2. `app/pipeline/observable.py::build`는 영상별 최신 snapshot의 조회·좋아요·댓글 수,
   snapshot 시점의 게시 나이와 observation run의 댓글/thread 자료를 결합한다.
   `compare(video, videos)`가 전체 전달 영상 목록에서 peer를 골라 view_multiple을 만든다.
   audience 및 observation-quality scalar는 반환값의 `videos`에 함께 유지된다.
   별도 `observable_evidence` 테이블에는 이 함수의 feature evidence payload가 저장된다.
3. `feature_outcome/runner.py`는 frozen registry envelope, label, split CSV,
   supplied evidence JSON을 읽는다. `frozen.prepare`가 먼저 Development ID를 선택하고
   허용 필드만 투영한다. 품질 scalar도 기존처럼 유지하며 peer ID/전체 summary는 투영하지 않는다.
4. `finding.build_findings`는 공급된 view_multiple과 eligible audience scalar로
   세 association 및 calculable chain을 생성한다. 입력 값을 재계산하지 않는다.
   Runner는 새 디렉터리에 findings와 입력 경로/hash를 담은 manifest를 저장한다.
   별도 Outcome CLI도 frozen Development 경로에서 같은 engine을 호출한다.

## 세 view_multiple 정의

| 구현 | 분모 peer 조건 | 최소 peer / 주요 차이 |
|---|---|---|
| `normalize.py::view_multiple` | 같은 length_axis, 같은 게시 분기, 자기 자신 및 live peer 제외 | 기본 3개. truthy view_count만 사용하며 0은 제외 |
| `observable.py::compare` | 같은 length_axis, target age_days에서 ±20% (최소 ±2일), 자기 자신 및 live peer 제외 | 5개. non-null view_count에 0도 포함. live target은 값 없음 |
| `breakout.py::recompute_multiples` | 같은 length_axis, 같은 게시 분기, 자기 자신 및 breakout으로 표시된 peer 제외 | 기본 5개. 자체 live 필터 없음. 별도의 breakout 제외 분모 |

모두 조회수를 peer 중앙값으로 나누지만 서로 교환 가능한 값이 아니다.
Outcome CLI의 재계산 배수는 breakout.csv 등에 별도로 내보내며 Finding 입력 값을
대체하지 않는다. 세 계산의 코드와 기본값은 이번에 변경하지 않았다.

## Finding canonical Relative Performance

**current views / median current views of non-live, same-length-axis,
similarly-aged peers; minimum 5 peers.**

Finding 계약은 `observable.compare` 정의다. 현재 snapshot의 cross-sectional relative
performance이며 예측/기대 조회수나 동일 게시 후 7일 성과가 아니다.
자기 자신은 제외하고 나이 허용폭은 max(2일, target age_days의 20%)다.
live target, non-null 조회수 peer 5개 미만, target 조회수 누락 또는 중앙값이
0 이하이면 배수를 만들지 않는다. Finding에서 이 계산을 재구현하지 않는다.

`input_contract.relative_performance`는 요구되는 source/정의와
`provenance_verified=false`를 기록한다. supplied scalar만으로 실제 upstream source를
확인할 수 없으므로 이 metadata는 검증 인증이 아니다. 다른 분모의 값을 넣어도 현재
Runner는 source 불일치를 자동 거부하지 않는다. 이는 이번 범위 밖의 입력 검증 한계다.

## Audience signal / observation quality

Association 대상 `AUDIENCE_METRICS`:

- like_rate, comment_rate, unique_commenters, observed_repeat_share,
  participant_breadth, threads, replies_collected, reply_rate, max_thread_size.

`OBSERVATION_QUALITY_METRICS` (Feature→Behavior, Behavior→Performance,
chain candidate 대상에서 제외):

- author_missing_rate, collection_to_api_ratio, api_replies_sampled_threads,
  reply_incomplete_threads, reply_fetch_coverage.

품질 값은 observable 생성/저장 및 frozen 선택행 evidence 투영에 유지한다.
품질 기준에 따른 새 행 필터나 가중치를 도입하지 않았다. 유효한 숫자가 있어도
품질 지표는 available_behaviors에 들어가지 않는다. 나머지 metric의 계산은 그대로다.

## Sampling-sensitive 지표와 출력 metadata

`SAMPLING_SENSITIVE_METRICS`는 unique_commenters, participant_breadth, threads,
replies_collected, max_thread_size를 명시한다. 영상 선택, 최신 댓글 표본,
답글 페이지 상한과 수집 상태의 영향을 받으며 검증된/불편 추정량으로 해석하지 않는다.
participant_breadth는 관측 unique authors / views이고 전체 시청자의 참여율을 보장하지 않는다.

기존 calculation/candidate의 metric 또는 behavior_metric으로
`input_contract.metrics[metric]`를 조회하면 category, expected_source,
association_eligible, sampling_sensitive를 찾을 수 있다. 지정된 다섯 지표는 true이며
나머지는 null이다. null은 sampling-independent 판정이 아니다. 특히 observed_repeat_share와
reply_rate도 수집 범위에 의존한다. 이 목록은 모든 편향의 완전한 분류가 아니다.
출력 계약 버전은 `finding-input-v0.1`; engine 버전과 기존 계산 구조는 유지한다.
이 metadata는 실제 run의 sampling policy 값이나 수집 품질 원자료를 복제하지 않는다.

## 현재 한계 / 추가 위험

- Development 행 투영이 upstream baseline의 split 독립성을 보장하지 않는다.
  observable peer 모집단과 repeat-share의 author-video 집합은 다른 split에 의존할 수 있다.
  이번에 peer/반복 참여 모집단을 변경하거나 frozen artifact를 다시 만들지 않았다.
- 조회 snapshot과 댓글 수집 시점이 다를 수 있고 표본은 비확률 표본이다.
  일부 수집 실패/미수집 표현이 0 또는 None으로 다르며 이번에 보정하지 않았다.
- category는 탐색 association 자격이며 audience construct의 검증/대표성 인증이 아니다.
- 통계 추정치가 calculable이라는 것은 신뢰성 검증이 아니다. Feature와 무관한
  Behavior→Performance에는 숫자쌍이 있는 U 영상도 포함되며 binary leg/chain의
  target/control에서는 U를 제외한다.
- feature status별 eligibility, breakout 비교, same-corner 및 cross-channel 검증,
  upstream source 강제 검증은 여전히 별도 후속 과제다.
- 기존 결과 파일은 변경하지 않는다. 새 실행에는 품질 metric leg/chain이 빠지고
  additive input_contract가 생기므로 이전 결과와 전체 JSON이 같지는 않다.
  엄격한 downstream JSON consumer는 새 필드 수용 여부를 확인해야 한다.

## 의도적으로 하지 않은 것

observable/normalize/breakout 수식 변경·삭제·통합, 통계기법/유의성·효과크기 문턱 추가,
sampling 정책 변경, 데이터 결과를 이용한 사후 정의 조정, 실제 실험 재실행,
Holdout 열기/unseal, registry·label·split 변경, 대규모 refactor, commit은 하지 않았다.
Development-only, U 제외, no-threshold, frozen output isolation을 유지한다.

## 검증

합성 Engine/Runner 테스트로 모든 audience metric의 association/candidate 유지,
품질 scalar 제외와 입력 보존, 선택행 metadata 유지, JSON sampling metadata 보존,
0 효과에서도 chain 출력, 기존 U/Development/frozen isolation 계약을 확인한다.
저장소 루트에서 실행:

```text
python -B -m pytest backend/tests/test_finding_engine.py backend/tests/test_finding_runner.py backend/tests/test_frozen_feature_outcome.py backend/tests/test_observable.py -q -p no:cacheprovider --tb=short --basetemp C:\Users\EZ\OneDrive\Documents\ChatGPT\yt_trend\outcome-audit-tests-20260915
```

결과: **48 passed** (0.48초). 신규 테스트 4개와 기존 테스트 44개가 통과했다.
기존 frozen 테스트의 unseal 사례도 pytest 임시 디렉터리의 합성 fixture만 사용한다.
실제 Holdout 입력 또는 실험 산출물에는 접근하지 않았다.
`git diff --check`는 exit 0, whitespace 오류 없음.
observable.py, normalize.py, breakout.py에는 diff가 없다.
