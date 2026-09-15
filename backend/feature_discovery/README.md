# Blind Feature Discovery Harness v0.1

콘텐츠를 보고 특징을 정의하는 Content Feature Discovery와 성과를 확인하는
Outcome Validation을 분리하는 **실험 전용 도구**다. 이번 버전은 split,
blind content packet, feature registry 검증까지만 제공한다. 성과를 보고
특징 정의를 사후 조정하는 분석 흐름을 만들지 않는다.

## 저장소 조사와 독립 구조

- 기존 Python 코드는 `backend/app`, pytest 함수형 테스트는 `backend/tests`에 있다.
  같은 snake_case 관례를 따르되 `backend/feature_discovery`를 별도 패키지로 둔다.
- DB 기본 경로는 backend에서 실행할 때 `data/yt_trend.db`이며, 이 clone에는
  실제 DB가 없다. 영상 키는 SQLite `videos.video_id`다.
- `videos`에는 `title`, `description`, `duration_sec`, `published_at`, `length_axis`
  등이 있다. 길이 축은 기존 값 `shorts/standard/long`을 그대로 사용하며 재계산하지 않는다.
- 현재 스키마에는 영상별 `transcript`, `corner`, `playlist` 컬럼이 없다.
  재생목록 코너는 `segments.py`가 수집하고 `video_taxonomies`의 segment 축과
  `video_type_labels`에 표현된다. 해석·라벨 의존성을 피하기 위해 이를 join하지 않는다.
  별도로 준비한 순수 콘텐츠 JSON에서는 해당 문자열을 받을 수 있다.
- `video_stats_snapshots`에 조회/좋아요/댓글 수, `video_metrics`에
  `views_per_day`, `view_multiple`, `comment_rate_multiple`과 `*_basis`,
  `type_metrics`에 `med_*` 성과가 있다. `comment_labels`,
  `comment_engagement`, `video_comment_metrics`, `type_comment_metrics`에는
  sentiment, positive/negative/neutral, approval, contention, labeled_ratio,
  topic_counts_json 및 대표 댓글·비율이 있다. 이 테이블들은 읽지 않는다.
- 기존 생성물은 `backend/exports`, `backend/data`를 사용한다. 이번 생성물은
  `feature_discovery/outputs` 아래에 격리하며 모듈의 `.gitignore`로 제외한다.
- `app.db.connection.connect`는 schema 실행과 열 추가를 하므로 사용하지 않는다.
  자체 adapter가 SQLite URI `mode=ro`와 `query_only`를 사용한다. DB 생성,
  migration, production import, API 호출, production 파일 변경이 없다.

## 실행 순서 (저장소의 backend 폴더에서)

Python 3.11 이상, 실행 자체는 표준 라이브러리만 필요하다.

```powershell
python -m feature_discovery.split_dataset --input feature_discovery/fixtures/content.json --output feature_discovery/outputs/demo/split.csv --seed 42
python -m feature_discovery.export_blind_discovery --input feature_discovery/fixtures/content.json --split feature_discovery/outputs/demo/split.csv --output-dir feature_discovery/outputs/demo/packet
python -m feature_discovery.registry feature_discovery/feature_registry/examples.json
```

10개 합성 영상 fixture로 3 discovery / 3 development / 4 holdout이 생성된다.
실제 DB를 쓰려면 두 명령의 `--input`을 해당 `.db` 파일 경로로 바꾸고
별도 output 경로를 사용한다. DB의 **전체 videos 집합**을 대상으로 한다.
JSON 입력은 content 객체 배열이어야 한다. 통계가 섞인 기존 export를 그대로
넣으면 실패한다. CSV 입력은 지원하지 않는다.

## Split 동결 정책

`video_id,split,seed,created_at` CSV를 저장한다. 사람이 검토하기 쉬운 CSV를
기본으로 사용했다. 기존 artifact는 기본적으로 거부하며 명시적인 `--force`만
재생성을 허용한다. 재생성은 기존 실험 split의 연속성을 깨므로 새 실험으로 취급한다.
blind packet은 덮어쓰기 flag 없이 새 디렉터리를 사용해야 한다.

기본 seed 42. ID를 seed와 함께 SHA-256으로 순서화하므로 입력 행 순서에
의존하지 않는다. 배정 결과는 동일 입력·seed·stratification 설정에서 동일하다.
`created_at`은 실제 생성 시간이라 강제 재생성한 CSV의 바이트까지 같지는 않다.

전체 목표 개수를 30/30/40의 largest remainder로 정한 뒤, 각 length_axis의
floor 할당과 남은 비율 부족분을 전역 잔여 용량 내에서 결정적으로 배분한다.
동률은 축 이름, split 순서(discovery/development/holdout)로 해결한다.
작은 strata에서는 각 split에 모두 들어갈 수 없지만 전체 목표 개수는 유지한다.
없는/null/빈 length_axis는 하나의 그룹이며, `--no-stratify`로 층화를 끌 수 있다.
빈 입력이나 중복 ID는 거부한다. export 시 source와 split의 ID 집합이 정확히
일치해야 하므로 영상 추가/삭제가 있으면 실패한다. 콘텐츠 내용 변경 자체를 동결하는
해시 manifest는 v0.1에 없으므로 재현용 원본 입력도 별도로 보존해야 한다.

## Outcome 차단

`blind.py` 한 곳에서 정확한 allowlist와 forbidden family pattern을 관리한다.
출력 열은 다음 9개다.

```text
video_id,title,description,transcript,duration_sec,length_axis,corner,playlist,published_at
```

SQLite에서는 이 목록과 실제 videos 컬럼의 교집합만 SELECT한다. 원본 DB에
성과 컬럼/테이블이 존재하는 것은 정상이며 이를 선택하지 않는다. videos에 있는
`comments_disabled`, 댓글 수집 cursor, `comments_complete`도 선택하지 않는다.
JSON source 및 export schema에 outcome/미등록 필드가 유입되면 쓰기 전에
ValueError로 실패한다. 개발/holdout 행에만 유입돼도 실패한다. 중첩 객체를
문자열 필드에 넣는 것도 거부한다. 새 필드를 자동 허용하지 않는다.

실제 컬럼 외에도 baseline/comparison, reply/thread, timestamp 집계,
participant/repeat, Reaction 등 family를 차단한다. `published_at`은 콘텐츠
게시 시각이므로 허용한다. 없는 선택 필드는 JSONL에서 null, CSV에서 빈칸이다.
CSV는 표준 CSV 인코딩이므로 스프레드시트에서는 텍스트로 가져오는 것이 적절하다.

이 차단은 구조적 컬럼 유출을 방지한다. 제목·설명·자막 본문 자체에 저자가 적은
성과 언급까지 의미적으로 제거하지는 않는다. 외부 사이트에서 video_id를 조회해
성과를 보거나 holdout 내용을 수동 열람하는 행위까지 막는 접근 통제도 아니다.
Discovery 작업자에게는 packet만 전달하고 원본 DB와 전체 source는 전달하지 않는다.

## Feature registry

`feature_registry/schema.json`이 JSON Schema 계약이며 `registry.py`는 이 파일이
사용하는 type/required/properties/additionalProperties/enum/minLength/minItems/
items/local ref 부분집합을 표준 라이브러리로 검증한다. 범용 JSON Schema 엔진은 아니다.
추가로 feature_id/version 중복과 categorical categories 존재를 검사한다.

`examples.json`의 guest_present와 first_person_past_experience는
**production taxonomy가 아닌 schema/example fixture**다. 검증된 특징이 아니다.
새 registry는 별도 JSON에 정의하고 위 CLI로 검증한다. source는 human/llm/both/comment-derived,
status는 candidate/testing/validated/rejected다. 이 status는 기록용 메타데이터이며
validator 통과가 성과 관계의 validated 상태를 보증하지 않는다.

`comment-derived`는 댓글을 discovery evidence로 사용하여 underlying video/content
property 후보를 발견했다는 provenance다. 댓글 자체가 feature는 아니다. 댓글은
후보 발견 단계에서만 사용할 수 있으며 operationalization 이후 video-level 0/1/U
labeling 및 validation evidence로 사용할 수 없다. 다른 source와 동일한 Feature
Registry / frozen validation / Finding Engine 계약을 따르며 source별 특별 처리는 없다.
`human`과 `llm`의 기존 의미는 유지한다. `both`는 Human과 LLM 양쪽의 독립 발견만
의미하며 comment-derived를 포함하지 않는다. 이 경계는 evidence 사용 계약이며
source enum 검증만으로 실제 사용한 evidence까지 자동 검사하는 것은 아니다.

### sponsored_product_integration — operationalization DRAFT

- feature_id: `sponsored_product_integration`
- source/provenance: `comment-derived`
- 상태: **testing candidate / operationalization draft**. 최종 testing registry에
  편입되지 않았고 validated/frozen feature도 아니다. 14F Human Registry가 아직
  도착하지 않았으므로 최종 testing set/frozen registry를 만들지 않는다. 14F
  Human/LLM/comment-derived 후보 비교 및 Step 3 freeze 이후 최종 채택 여부를 결정한다.

개념: 특정 상업 제품·브랜드·서비스가 단순 노출을 넘어 영상의 실제 진행, 활동
또는 실질적인 대화/소개 소재에 통합되어 있는가.

- **1:** 특정 제품/브랜드/서비스의 사용, 시식, 시연, 소개 또는 이에 준하는 활동이
  영상의 실질적인 진행/콘텐츠를 구성한다.
- **0:** 그러한 content integration이 없다. 단순 배너, 짧은 sponsor mention,
  일회성 제품 노출처럼 핵심 콘텐츠와 분리 가능한 광고 노출만 있는 경우도 0이다.
- **U:** 허용된 content evidence만으로 integration 존재 여부를 판정할 수 없다.

이는 “유료 광고인가”와 동일한 feature가 아니다. commercial disclosure 자체가
아닌 content integration을 측정한다. title-only에서 제품/광고 언급이 없다는
이유만으로 0을 부여하지 않는다. 0 판정에도 충분한 content evidence가 필요하다.
댓글은 발견 provenance일 뿐 실제 0/1/U labeling evidence로 사용하지 않는다.

required_evidence 초안: 영상 본문을 판단할 수 있는 transcript 또는 이에 준하는
content evidence. 제목/메타데이터만으로 충분히 명시적인 positive case는 1 판정의
보조 evidence가 될 수 있지만 title-only absence는 0의 근거가 될 수 없다.
이 초안은 문서에만 존재하며 production registry JSON에는 추가하지 않는다.

### 종료된 Step 3.5 결정 보존

Feasibility probe는 PASS 및 종료됐다. 재실행, 댓글 재분류·추가 수집은 하지 않는다.

- guest/collaboration: 기존 `guest_external`의 independent discovery corroboration.
  신규 feature를 생성하지 않는다.
- `repeated_in_video_catchphrase`: preserve 유지. `recurring_bit`과의 경계가
  해결되지 않았으므로 지금 operationalize하지 않는다.
- `promised_actual_runtime_mismatch`: preserve 유지. coverage 우려가 있으므로
  지금 operationalize하지 않는다.
- channel/campaign context: insufficient_support 유지.
- generic reaction signals: content feature로 승격하지 않는다.

binary 값은 정수 0=없음, 1=있음, 문자열 U=자료 부족이다. 자료 부족을 0으로
바꾸지 않는다. `validate_value` 함수는 이 계약을 검사하며 numeric 유한 숫자,
categorical categories 문자열로 확장할 수 있다. U는 모든 유형에서 판정 불가다.
현재 label 생성·저장 기능은 없다.

## 테스트

pytest가 설치된 환경에서 저장소 최상위 기준:

```powershell
python -m pytest backend/tests/test_feature_discovery.py -q -p no:cacheprovider
python -m pytest backend/tests -q -p no:cacheprovider
```

테스트 DB와 artifact는 pytest 임시 디렉터리에만 생성한다.

## 구현하지 않은 범위

LLM API 호출, feature 자동 discovery, Human/LLM label comparison,
Feature × Outcome relationship, holdout relationship validation, Insight Agent,
report UI integration, production DB migration. 기존 comment labeling 브랜치
cherry-pick, pipeline stage 의미 변경, report 수정, main merge도 수행하지 않는다.
