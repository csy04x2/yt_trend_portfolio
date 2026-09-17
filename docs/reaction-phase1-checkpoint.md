# Reaction Phase 1 Checkpoint

- 이 문서는 Reaction + Target Phase 1 종료 후 인간 검토로 확정된 기준을 기록한다.
- 이 기준은 Phase 2에 들어가기 전에 확정된 것이다.
- Phase 2에서는 이 기준을 고정해서 적용하며, 결과를 보면서 중간에 taxonomy나 판정 기준을 변경하지 않는다.
- Phase 2 종료 후 문제 사례를 모아 별도로 검토할 수 있다.
- 따라서 이것은 영구적인 최종 taxonomy가 아니라 Phase 2 검증을 위한 frozen checkpoint이다.

## Reaction taxonomy

Phase 1 종료 시 구조는 Reaction 10개를 유지한다.

1. 평가·칭찬
2. 관계·정서
3. 즐거움·놀이
4. 비판·불만
5. 시청 어려움·회피
6. 당혹·의문
7. 내용 참여
8. 요청·제안
9. 행동 유발
10. 성과 참여

- 복수 Reaction 허용.
- Reaction이 성립하지 않는 댓글에는 Reaction=None을 허용.
- UNKNOWN은 기준상 판정이 불가능하거나 불충분한 경우를 위한 별도 상태로 유지.
- Reaction=None과 UNKNOWN을 임의로 같은 의미로 합치지 말 것.

## Target taxonomy

Target은 다음 5개를 유지한다.

1. 콘텐츠 전체
2. 내용·소재
3. 인물
4. 제작·표현
5. 채널·커뮤니티

- 복수 Target 허용.
- Target은 “시청자가 무엇에 반응하고 있는가”를 나타내는 축이다.

## H1 — `내용 참여` 경계 강화

Phase 1 인간 검토 결과 `내용 참여`의 적용 범위를 좁힌다.

단순 관찰·포착만으로는 `내용 참여`가 아니다.

예:

- “저 장면 뭐야ㅋㅋ” 같은 단순 장면 포착
- “OO 닮았다” 같은 짧은 연상·관찰

이런 댓글에 다른 Reaction이 성립하지 않으면 Reaction=None을 허용한다.

`내용 참여`는 댓글이 내용에 대해 실질적인 인지적 기여를 하는 경우에 적용한다.

포함 가능한 유형:

- 의미 있는 생각이나 해석
- 정보·지식의 추가
- 개인 경험을 내용과 연결
- 실제 답을 구하는 질문

별도의 `관찰·포착` Reaction을 신설하지 않는다.

## H2 — `특정 장면`을 Reaction/Target으로 만들지 않음

`특정 장면` 또는 `특정 장면/표현 포착`을 독립 Reaction으로 신설하지 않는다.

Target에도 `특정 장면`을 추가하지 않는다.

Target 5 구조를 그대로 유지한다.

댓글에 `32:19` 같은 명시적인 timestamp가 존재하면 Reaction/Target과 별개의 raw/metadata 정보로 보존할 수 있다.

AI가 댓글만 보고 영상의 어느 장면을 의미하는지 추론하기 위해 영상을 시청하도록 요구하지 않는다.

향후 timestamp 정보는 highly watched/replayed segment 등 별도의 영상 구간 데이터와 결합할 가능성은 열어두되, 현재 Reaction/Target taxonomy에는 포함하지 않는다.

## H3 — raw 보존과 분석 포함 여부 분리

수집된 댓글 자체는 raw data에 보존한다.

Audience Behavior / Reaction 집계에 사용할 수 있는지는 별도의 analysis eligibility 상태로 관리한다.

원칙:

- 해당 영상/채널 자신의 댓글은 raw에는 보존한다.
- 그러나 Audience Behavior / Reaction 집계에서는 제외한다.
- 제외된 parent/pinned comment에 달린 실제 시청자 reply는 분석 대상이 될 수 있다.
- 확인된 spam 또는 잘못 수집된 데이터도 raw에는 보존하되 분석에서는 제외하고 exclusion reason을 기록한다.
- 직원 계정, 부계정, 사칭 계정, 상업 계정 등으로 의심된다는 이유만으로 자동 제외하지 않는다.
- 신뢰할 만한 근거가 없는 경우 임의로 해당 계정을 Audience Behavior에서 제거하지 않는다.
- 더 정교한 spam/commercial-noise detection은 후속 과제로 둔다.

구체적인 필드명은 구현 단계에서 정할 수 있으나, 개념적으로 raw preservation과 analysis eligibility를 분리한다.

## H4 — 희귀 Reaction을 성급하게 삭제하지 않음

Phase 1의 추가 250개 댓글 검토에서:

- `시청 어려움·회피`: 3건
- `성과 참여`: 0건

이 결과만으로 두 Reaction을 삭제하거나 다른 Reaction에 병합하지 않는다.

Phase 2에서 다른 채널에 동일 기준을 적용하면서 추가 관찰한다.

희귀 Reaction을 찾기 위해 댓글을 의도적으로 oversampling하지 않는다.

즉 자연스럽게 수집된 Phase 2 표본에서 실제 출현 여부를 본다.

## Phase 2 운영 원칙

Phase 2에서는 위 Reaction 10 + Target 5와 H1~H4를 고정해서 적용한다.

Phase 2 도중 결과가 마음에 들지 않는다는 이유로:

- Reaction을 추가/삭제/병합하거나
- Target을 추가/삭제하거나
- H1~H4의 경계를 변경하지 않는다.

문제가 있는 댓글은 별도로 기록하고, Phase 2 실행이 끝난 뒤 함께 검토한다.

Phase 2의 목적은 이 checkpoint가 새로운 댓글/채널에서도 작동하는지 검증하는 것이다.

Phase 2에는 taxonomy 설계에 사용되지 않은 새로운 댓글을 사용해야 한다.

기존 Phase 1/개발 노출 데이터는 fresh blind validation 데이터로 취급하지 않는다.

## 문서 성격

- Human-approved: yes
- Phase 1 checkpoint: yes
- Frozen for Phase 2: yes
- Permanent final taxonomy: no
- Mid-Phase-2 revision allowed: no
