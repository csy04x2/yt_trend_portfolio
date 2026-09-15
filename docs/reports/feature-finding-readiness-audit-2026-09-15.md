# Feature → Finding Readiness Audit

2026-09-15 · 기준 commit `ca7bb1b9c2d9655461c66b37faa441ca6da542b9`
· branch `integration/feature-discovery-observable` · 문서만 변경.

## Current contract

현재 흐름은 후보 registry → 사람이 operational definition/evidence/0·1·U 경계를 확정
→ 별도 Development 판정 파일 → frozen envelope + split CSV + outcome evidence
→ `feature_outcome.runner` → `findings.json`, `manifest.json`이다.
Discovery harness에는 operationalization/실제 label 생성·저장 자동화가 없다.
`feature_outcome labels`의 제목 정규식은 자리표시자이며 실제 판정 대체물이 아니다.

### Registry / eligibility

- [schema](../../backend/feature_discovery/feature_registry/schema.json)와
  [validator](../../backend/feature_discovery/registry.py): 내부 registry 필수값은
  `schema_version="0.1"`, 비어 있지 않은 `notice`, 하나 이상의 `features`다.
  feature 필수값은 `feature_id`, `name`, `version`, `scope`, `value_type`, `definition`,
  `inclusion_examples`, `exclusion_examples`, `required_evidence`, `source`, `status`다.
  예시/evidence 배열은 비어 있지 않은 문자열을 하나 이상 요구한다.
  `source`는 human/llm/both, `status`는 candidate/testing/validated/rejected다.
- [loader](../../backend/feature_outcome/labels.py)는 envelope의 `registry`를 검증하고,
  `freeze_metadata`에 `definitions_frozen_before_development=true`, `freeze_status="frozen"`,
  truthy `registry_version`·`dataset`, `testing_feature_count == len(features)`를 요구한다.
  모든 feature는 `value_type="categorical"`, `categories=["0","1","U"]`여야 한다.
  기존 Claude registry는 binary/candidate인 plain registry이므로 직접 Runner 입력이 될 수 없다.
- 내부 registry와 feature는 `additionalProperties=false`다. `provenance` 같은 새 필드는
  거부되며 `source="comment-derived"`, `status="preserve"`/`"insufficient_support"`/`"frozen"`도 거부된다.
  반면 바깥 envelope는 strict schema가 없다. 기존 테스트처럼
  `feature_metadata[feature_id].provenance`에 comment-derived 출처를 넣으면 loader가
  `_envelope`에 보존한다. Runner manifest에는 전체 metadata 대신 입력 경로/해시가 기록된다.
- **정의 동결과 feature 검증 자격은 다르다.** loader/engine은 feature별 status를
  필터링하지 않는다. frozen envelope 안의 candidate/testing/rejected도 계산 대상이며
  테스트 자체가 testing feature를 사용한다. preserve는 schema에서 거부되지만
  status를 바꿔 포함하면 별도 승격 자격 검사는 없다. validated/frozen-only 원칙은 완전히 enforce되지 않는다.

### Labels / split / outcomes

- [Runner](../../backend/feature_outcome/runner.py)는 Development만 허용하며 입력을 열기 전
  다른 split을 거부한다. plain/위조 `_envelope`/unfrozen registry를 거부하고
  [frozen.prepare](../../backend/feature_outcome/frozen.py)로 선택 ID를 먼저 투영한다.
  split CSV에서 실제 필수 열은 `video_id,split`; seed/created_at은 읽어 검증하지 않는다.
  중복 membership, population 밖 evidence ID, Development evidence/feature label 누락은 거부한다.
- 라벨은 `{"labels":{"video_id":{"feature_id":0 또는 1 또는 "U"}}}` 또는 내부 mapping.
  문자열 "0"/"1"도 정수로 정규화하며 bool/float/null/미등록 feature는 거부한다.
  모든 Development 영상에 모든 feature 키가 필요하다. U는 binary 관계와 chain의
  target/control 양쪽에서 제외하고 따로 센다. behavior→performance는 feature와 무관한
  관계여서 해당 feature가 U인 영상도 유효 숫자쌍이 있으면 포함한다. U를 0으로 바꾸는 것은 아니다.
- 입력 evidence는 영상 배열 또는 `{"videos":[...]}`이며 Runner 계산 최소 필드는 `video_id`,
  유한 숫자 `view_multiple`, 하나 이상의 유한 숫자 Audience metric이다. binary 관계는
  metric이 관측된 1/0 그룹 각각 최소 1편, Spearman은 최소 2쌍과 양쪽 변동이 필요하다.
  누락 metric은 제외되며 충분하지 않으면 계산 불가로 남는다. 표본 품질/검증 통과를 뜻하지 않는다.
- [finding.py](../../backend/feature_outcome/finding.py)의 허용 Audience 필드는 `like_rate`,
  `comment_rate`, `unique_commenters`, `author_missing_rate`, `observed_repeat_share`,
  `participant_breadth`, `collection_to_api_ratio`, `threads`, `replies_collected`,
  `api_replies_sampled_threads`, `reply_rate`, `reply_incomplete_threads`, `reply_fetch_coverage`,
  `max_thread_size`다. nested Reaction/timestamp나 raw comment는 입력 metric이 아니다.
  feature→performance/behavior는 중앙값 차이, behavior→performance는 Spearman이며
  세 추정치가 계산 가능하면 exploratory association chain을 출력한다. 유의성/효과크기 문턱은 없다.
- [observable.py](../../backend/app/pipeline/observable.py)의 like/comment rate는 조회수 대비 비율,
  view_multiple은 같은 길이축·유사 게시 나이의 비라이브 peer 조회수 중앙값 대비 배수다.
  `compare(v, videos)`는 split을 모르며 전체 영상에서 peer를 고른다.
  `observed_repeat_share`도 전체 수집 영상의 author 집합을 사용한다. frozen adapter는 이미 계산된
  값을 재정의하지 않으므로 **행 분리가 upstream metric의 split 독립성을 보증하지 않는다.**
- 공유 evidence/labels JSON은 전체 decode 및 해시 읽기를 하지만 분석은 선택된 Development 행만 한다.
  별도 Holdout 파일을 자동 탐색/unseal하지 않는다. `build_findings` 직접 호출은 split 이름과
  `_envelope` 존재만 검사하므로 실제 membership/진짜 freeze 검증은 Runner 경로에 의존한다.
  기존 plain `feature_outcome run` 경로는 전체 집계 후 split 필터를 적용하므로 동일한 보장이 없다.

## Ready

- 계약을 맞춘 frozen 입력에 대한 Development 전용 Runner, 완전한 0/1/U 라벨 검사,
  U 제외, 관측값 누락 집계, 세 association·LOO 출력, 입력 해시와 새 출력 폴더 보존.
- comment-derived provenance를 바깥 envelope metadata에 보존하는 기존 경로.
- 별도 [Outcome CLI](../../backend/feature_outcome/__main__.py)의 frozen 모드는
  [outcome.py](../../backend/feature_outcome/outcome.py)에서 전체/급등 제외 두 판을 제공한다.
  이는 Finding Engine 전체의 breakout 검증 완료를 의미하지 않는다.

## Missing / blocked

| 구분 | 확인된 항목 / 필요한 후속 조치 |
|---|---|
| BLOCKER | 14F Human Registry와 원본 Discovery 판정이 아직 없다. 수신 시 원본을 먼저 보존해야 한다. JSON 하나만 도착해도 승인된 operational definitions, 동결 split, Development 판정, 호환 outcome evidence가 자동으로 갖춰지는 것은 아니다. 이는 분석 입력 blocker이며 원본 수신/비교 작업 자체를 막는 구현 blocker는 확인되지 않았다. |
| BEFORE DEVELOPMENT | Human 원본을 보존한 별도 계약 변환이 필요하다: operationalization, categorical 0/1/U envelope, 출처, 승인된 feature 목록, Development 전 영상 라벨. 자동 변환/실제 판정기는 없다. 이름·고정 크루·유사 후보 경계 및 댓글 없는 독립 판정 근거를 확정해야 한다. |
| BEFORE DEVELOPMENT | feature eligibility gate 부재. definitions_frozen와 Development에서 검증된 feature를 구별하여 기존 인간 승인/동결 기준과 입력 목록을 대조해야 한다. testing을 validated로 임의 변경하거나 동결 metadata만으로 승격해서는 안 된다. |
| BEFORE DEVELOPMENT | upstream view_multiple peer와 repeat-share 모집단이 Discovery/Holdout에 의존할 수 있다. 승인된 baseline 정책·입력 provenance와 split을 대조해야 한다. 현재 projection과 테스트는 이 독립성을 검증하지 않는다. |
| BEFORE DEVELOPMENT | Finding Engine 세 관계/chain의 breakout 포함·제외 비교가 없다. Runner는 flags/events를 받지 않고 CLI findings도 전체 selected videos를 그대로 사용한다. LOO는 breakout 제외 대체물이 아니다. 기존 Outcome CLI가 export하는 재계산 배수도 outcome/findings 추정에 전달되지 않는다. 필요한 validation layer 항목으로만 기록한다. |
| BEFORE HOLDOUT | same-corner persistence/feature×corner 겹침 검사가 없고 frozen projection은 corner를 보존하지 않는다. 채널별 별도 실행은 가능하지만 양방향 적용 라벨·동일 정의 대조·교차채널 지속성 판정 자동화는 없다. 구조 후보 선별 전에 별도 validation이 필요하다. |
| BEFORE HOLDOUT | Finding Runner/Engine은 Holdout 분석을 지원하지 않는다. 기존 Outcome CLI의 명시적 unseal은 가능하지만 일회성 사용 이력/재실행 금지는 enforce하지 않는다. 생존 후보와 한 번의 검증 절차는 기존 인간 기준에 따라 통제해야 한다. |
| OPTIONAL | operationalization/label 변환 자동화, Finding bootstrap, 세 번째 성장 채널은 현재 MVP 계산 경로의 필수 구현이 아니다. |

## No-action findings

- Step 3.5 PASS와 후보 처리는 [comment-pilot.md](../../backend/fixtures/labeled/discovery-chim-claude-20260914/comment-pilot.md)에 기록했다. 기존 JSON은 4편×40개, vocabulary 14개인 관찰 artifact다. 이를 282개 재분류 결과나 validated feature set으로 바꾸지 않는다.
- 기존 fixture README의 재분할/사건 없음/일회 unseal 설명은 실행을 보증하는 코드 계약이 아니다.
  이번 audit은 기존 split·인간 판정·동결 기준을 변경하거나 그 절차를 실행하지 않는다.
- `feature_id/version` 중복만 검사하여 같은 ID의 다른 버전은 통과할 수 있지만 라벨은 ID만 키로 쓴다.
  향후 입력 검토에서 한 실행의 ID 유일성을 확인해야 한다.
- 테스트 보장: `test_finding_engine.py` 4건은 세 관계/chain, U의 target/control 제외,
  Holdout 이름·plain registry 거부, 불충분 그룹 처리다. 실제 split membership과 feature별
  validated eligibility는 보장하지 않는다. `test_finding_runner.py`는 비Development 사전 거부,
  안전하지 않은 옵션 거부, 진짜 frozen envelope, 결과 재현/입력 보존을 확인한다.
  `test_frozen_feature_outcome.py`는 집계 전 Development 투영, U coercion 거부,
  누락 입력/덮어쓰기 거부와 명시적 Holdout 선택을 확인한다. status별 자격 거부,
  upstream baseline 격리, Finding breakout/corner/cross-channel 검증 테스트는 없다.
- 위 세 기존 테스트 파일: **39 passed** (2026-09-15). 기본 pytest 임시 폴더 접근 오류로
  최초 및 권한 재시도는 14 passed/25 setup errors; 쓰기 가능한 별도 `--basetemp`로 전부 통과했다.
  실행은 `python -B -m pytest backend/tests/test_finding_engine.py backend/tests/test_finding_runner.py backend/tests/test_frozen_feature_outcome.py -q -p no:cacheprovider --tb=short --basetemp <새 임시 경로>`.
  합성 fixture 테스트만 실행했으며 실제 실험·Holdout 입력은 실행하지 않았다. 새 테스트는 없다.

## Exact next step when 14F Human Registry arrives

1. Human Registry/판정 원본, 작성자·날짜·버전 및 기존 split 출처를 그대로 보존하고 사람이 동결을 확인한다. 원본을 수정하지 않는다.
2. 그 다음 승인된 Discovery packet으로 독립 LLM Discovery를 수행하고 Human/LLM 후보의 겹침·유사·고유를 비교한다. comment-derived 관찰은 보조 출처로만 연결한다.
3. 성과를 보지 않고 허용 evidence, 0/1/U 경계, 유사 후보 중복/coverage를 operationalize한다. 기존 인간 승인 기준에 따라 분석 대상과 정의 동결 기록을 별도 확정한다.
4. 원본을 남긴 파생 envelope로 schema를 맞추고, 동결된 Development split만 실제 evidence로 labeling한다. U는 유지하며 후보 상태를 임의 승격하지 않는다.
5. Development outcome evidence의 baseline/관측 모집단 provenance, ID 완전성, feature eligibility와 위 BEFORE DEVELOPMENT 항목을 확인·해결한다. artifact 도착만으로 READY를 선언하지 않는다.
6. 조건 충족 후 `python -m feature_outcome.runner --registry <envelope> --labels <labels> --split <split.csv> --evidence <evidence> --out feature_discovery/outputs/experiment-analysis/<새-run>`을 backend에서 실행한다. 결과는 association으로만 해석한다.
7. breakout·same-corner·양방향 cross-channel 검증과 생존 후보 확정 후 기존 승인 절차로 Holdout 단계에 간다. 자동 unseal/재분할하지 않는다.
