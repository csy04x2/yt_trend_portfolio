# Reaction / Audience Behavior track closeout — 2026-09-17

## Final status

**Reaction taxonomy track: CLOSED**

- Reaction vNext: 10 labels (R1–R10)
- Target: T1–T5 + UNKNOWN
- Phase 1: CLOSED
- Phase 2: CLOSED
- 새로운 증거나 downstream 실제 문제가 생기기 전까지 재개하지 않는다.

## Final Reaction vNext

| 코드 | 의미 |
| --- | --- |
| R1 | 평가·칭찬 |
| R2 | 관계·정서 |
| R3 | 즐거움·놀이 |
| R4 | 비판·불만 |
| R5 | 시청 어려움·회피 |
| R6 | 당혹·의문 |
| R7 | 내용 참여 |
| R8 | 요청·제안 |
| R9 | 행동 지향 |
| R10 | 성과 참여 |

R9만 구조적으로 수정했다. 기존 `행동 유발`을 `행동 지향`으로 확장하여, 콘텐츠를 본 뒤 현실 행동을 했거나 하려는 의향, 또는 다른 개인·집단·기관의 구체적 현실 행동을 요구·촉구하는 반응을 포함한다. 콘텐츠 제작 요청은 R8이다. 단순 의견·해석은 R9가 아니다.

R7은 의미 있는 의견·해석·정보·경험·실제 답을 구하는 질문을 포함한다. 단순 관찰·장면 포착은 R7로 강제하지 않으며, 다른 Reaction이 없으면 `Reaction=None`을 허용한다.

## Target

Target은 5개와 UNKNOWN을 유지한다.

- T1 콘텐츠 전체
- T2 내용·소재
- T3 인물
- T4 제작·표현
- T5 채널·커뮤니티
- UNKNOWN

기관·정부·UN을 별도 Target으로 만들지 않는다. 특정 장면·표현 포착은 Reaction/Target이 아니며, 명시적 timestamp는 raw/metadata 정보로 보존한다.

## Phase 1 — CLOSED

Phase 1은 침착맨 댓글 300개 Boundary Stress Test다. 인간 확정 H1–H4를 유지한다.

- 단순 관찰·포착을 R7에 과포섭하지 않음
- 특정 장면을 Reaction/Target으로 추가하지 않음
- raw와 analysis eligibility를 분리
- 채널 자신의 댓글은 Audience Behavior 집계에서 제외
- parent/reply 관계를 보존
- 희귀 Reaction을 희귀하다는 이유로 삭제·병합하지 않음

## Phase 2 — CLOSED

Phase 2는 슈카월드 100개와 MBCNEWS 100개, 총 200개 top-level comments다. 채널당 2 videos × 50 comments이며, YouTube Data API v3 `commentThreads.list`, `order=relevance`로 수집했다. 따라서 random/uniform representative sample이 아니라 YouTube relevance-ranked exposure sample이다. replies는 제외했다.

Phase 2 AI coding 분포는 single-AI-pass coding distribution이며 accuracy/pass rate가 아니다. `review_flag=false`도 정답을 의미하지 않는다.

- Reaction: R1 18, R2 6, R3 55, R4 75, R5 0, R6 20, R7 91, R8 1, R9(구 정의) 4, R10 0, None 11
- Target: T1 9, T2 142, T3 51, T4 18, T5 6, no target 4
- multi-Reaction 75/200
- multi-Target 30/200
- review_flag 29/200
- review audit: APPLICATION_ERROR 5 / DEFINITION_BOUNDARY 6 / STRUCTURE_CANDIDATE 18
- 제3자·기관·대중 대상 행동 요구·촉구 중첩 집계: 19건

이 결과의 인간 확정 verdict는 `STRUCTURE_REVIEW_REQUIRED → R9 definition revision`이다. Reaction 11은 추가하지 않았고, Target은 유지했다.

Phase 2 200개는 R9 수정에 사용되었으므로 **fresh-blind validation eligibility = NO**다. 수정된 vNext의 독립 성능 증거로 재사용하지 않는다.

## Data provenance

- source: YouTube Data API v3
- channels: 슈카월드, MBCNEWS
- 4 videos total, 50 comments/video
- collected: 2026-09-17
- analysis_eligible: 200/200
- own_channel: 0
- duplicate comment_id: 0
- ordering: relevance-ranked, not random/uniform
- replies: excluded
- use history: Phase 2 AI coding + review audit + R9 structural revision evidence
- status: Phase 2 completed / Reaction track CLOSED

Repository에는 Phase 2의 raw/coded/audit 원문 파일을 새로 만들지 않는다. 기존 수집 보고서와 `docs/data-ledger.md`의 provenance를 정본으로 사용한다.

## Product decision

전체 Reaction classifier는 MVP Finding의 Audience Behavior 입력으로 사용하지 않는다. R3 애착·응원, R2 비판·불만 등 selective semantic signal은 후보로만 보존하며 production-ready 또는 empirically valuable이라고 선언하지 않는다. 다음 제품 우선순위는 observable Audience Behavior와 Finding input contract다.
