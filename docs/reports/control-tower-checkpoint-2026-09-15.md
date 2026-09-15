# Control Tower checkpoint — A/B/C/D

2026-09-15 · branch `integration/feature-discovery-observable`
· 확인한 HEAD `d0ce44a50275c7adb3176fe3e0f7d2f96137892e`

오늘 확정된 사실·정책·blocker·재개 조건의 단일 통합 기록이다. 수치와 데이터 준비
판정은 오늘 전문 트랙에서 확정되어 Control Tower로 전달된 결과이며 이 maintenance에서
분석을 재실행하지 않았다. 기존 기술 audit은 아래 링크의 기준 commit 당시 기록으로 보존한다.

## 사실 / 현재 상태

| 트랙 | 확인된 사실 | 상태 / blocker |
|---|---|---|
| A — Content Feature | 침착맨 Development는 evidence/split 기준 N=90. 현재 registry는 12개 binary/candidate feature이며 승인된 frozen Human Registry가 아니다. 90×12 labels는 `title-regex placeholder`다. | **BLOCKED**: 실제 frozen Finding에 사용할 승인 registry와 Development 판정이 없다. 14F Human Registry/JSON 외부 입력을 기다리는 작업이 있다. |
| B — Audience Behavior | `like_rate`, `comment_rate`는 Development 90/90 numeric. 댓글 observation 기반 metric은 8/90만 관측되며 missing 82편은 explicit null. collection status는 8 `capped`, 82 `not_sampled`. | 두 rate는 **READY**. `unique_commenters`, `participant_breadth`, `replies_collected`, `reply_rate`, `max_thread_size`는 계산 가능하나 sampled/capped coverage caveat가 있다. `threads`는 관측 8편 모두 100으로 고정되어 현재 association용 **NOT_READY**. `observed_repeat_share`는 split 밖 author를 포함한 observation population과 분해 불가능한 provenance 때문에 **NOT_READY**. 실제 observation/DB 입력이 더 필요하다. |
| C — Relative Performance | Finding은 upstream normalization 결과인 `view_multiple`을 소비한다. Development 90 중 81편이 numeric이며 현재 baseline에는 Discovery/Holdout peer가 포함된다. 보존된 침착맨 evidence 300편은 Discovery 90 + Development 90 + Holdout 120으로 전부 배정되어 별도 reference pool은 확인되지 않는다. | **BLOCKED FOR FINAL FINDING**: 별도 고정 reference population 및 canonical normalization이 아직 없다. 프로젝트 전체 실패 판정은 아니다. |
| D — Finding Engine | Development 90 ID completeness 확인: 누락·중복·split 밖 ID 없음. Engine/Runner readiness audit 완료. 기존 report는 candidate registry + title-regex placeholder + `u_as_control=true` 기반이다. | 핵심 실행 blocker는 engine wiring 자체보다 승인된 frozen registry/labels 및 upstream Audience/Performance 입력이다. 기존 report는 frozen Finding 결과가 아니다. **실제 validated inputs 준비 전 final Finding/Holdout 실행 금지.** |

## 결정

- **C 정책을 canonical 방향으로 채택한다.** experimental Discovery/Development/Holdout
  split과 별개의 고정 normalization reference population을 둔다. 별도 historical/reference
  population 확보 후, 결과를 보기 전에 선정 규칙을 고정하고 canonical normalization을 계산한다.
- 현재 cross-split `view_multiple`은 **provisional/legacy outcome**으로 보존한다.
  strict final Finding/Holdout validation용 canonical outcome으로 확정하지 않는다.
- 기존 300편 split을 사후 재편하여 reference pool을 만들지 않는다.
- 승인된 인간 판정·동결 기준은 유지한다. numeric/calculable 또는 audit 완료만으로
  입력 승인·feature validation·final Finding 준비 완료를 선언하지 않는다.

## 기존 기록과의 충돌 / 불확실성

- [Outcome-side audit](outcome-side-audit-2026-09-15.md)의
  “Finding canonical Relative Performance”는 당시 `observable.compare` 정의를 canonical로
  기술한다. **오늘 C 정책과 현재 cross-split 값의 final 사용 자격에서 차이가 있다.**
  이 checkpoint는 새 정책 결정을 기록하며, 현재 코드가 별도 reference 정책을 구현했다고
  주장하지 않는다. 기존 audit 문구·계산·산출물을 소급 수정하지 않는다.
- [Feature → Finding audit](feature-finding-readiness-audit-2026-09-15.md)은 `ca7bb1b` 기준이고,
  Outcome-side audit은 `27b0f5d` 기준이다. 현재 HEAD까지 input contract hardening,
  comment-derived provenance, discovery labeling, human-approved freeze workflow 커밋이
  추가되었다. 따라서 이전 audit의 “자동화 없음”·허용 metric/metadata 등 구현 설명을
  현재 코드 전체의 계약으로 그대로 간주하지 않는다. 이번에는 새 구현을 재감사하지 않았다.
  workflow 코드의 존재는 실제 승인된 Human Registry/Development labels 확보를 의미하지 않는다.
- B의 READY는 해당 metric의 현재 numeric 입력 준비 상태다. 8편의 관측만으로 모집단
  대표성이나 안정적인 association을 보장하지 않는다. repeat-share provenance 분해와
  별도 normalization reference pool의 확보 여부는 미해결이다.
- 기존 audit의 breakout, same-corner, cross-channel 및 Holdout 통제 후속 항목은
  이 checkpoint로 해결 처리하지 않는다. 최종 검증 전 확인이 필요하다.
- 시작 시 `git status --short`에 변경 항목은 없었으나 `backend/.pytest_cache/` 접근 경고가
  있었다. 해당 디렉터리는 이번 작업에서 탐색·수정하지 않으며 내부 상태는 확인하지 않는다.

## 재개 조건

| 외부 trigger | 재개할 트랙 / 필요한 확인 |
|---|---|
| 14F Human Registry/JSON | **A**: 원본·출처·인간 승인/동결 상태 보존 및 확인 → 독립 discovery 비교 → operationalization → 승인된 Development labeling. 도착 자체로 기존 침착맨 placeholder를 승인하지 않는다. |
| Audience observation/DB | **B**: Development ID별 관측 상태·null·수집 상한·coverage 확인, threads 변동 및 repeat-share author population/provenance 검증. 데이터 존재만으로 NOT_READY 해제하지 않는다. |
| 별도 historical/normalization reference data | **C**: 기존 300편 split 유지, 실험 split과 별개인 reference population 확인, 결과 열람 전 선정 규칙 동결 → canonical normalization과 provenance 준비. |
| 승인된 A 입력과 검증된 B/C 입력이 모두 준비됨 | **D**: frozen registry/labels·Development ID·upstream provenance·남은 validation 요건을 확인한 뒤 Finding 재개 여부를 판단한다. final Holdout은 별도 승인된 검증 조건 충족 전 실행하지 않는다. |

## 현재 하지 않는 것 / 이번 변경 범위

새 기능·새 실험·새 feature 개발·새 taxonomy·데이터 재수집·기존 코드 의미 변경은 없다.
timestamp operationalization, 새 Comment-derived Content Signal taxonomy, 300편 split 재편,
provisional outcome을 이용한 final Holdout claim을 진행하지 않는다.

이번 maintenance는 이 문서 한 개의 작성·diff 확인·별도 commit만 수행한다.
Documentation-only이므로 테스트를 실행하지 않는다. 기존 두 audit을 대체하거나 복제하지 않고
트랙 간 현재 결정과 blocker를 한 곳에서 복구할 수 있도록 연결한다.
