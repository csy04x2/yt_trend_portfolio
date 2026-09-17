# Reaction Phase 1 Checkpoint

- 이 문서는 Reaction + Target Phase 1 종료 후 인간 검토로 확정된 기준을 기록한다.
- 이 기준은 Phase 2에 들어가기 전에 확정된 것이다.
- Phase 2에서는 이 기준을 고정해서 적용하며, 결과를 보면서 중간에 taxonomy나 판정 기준을 변경하지 않는다.
- Phase 2 종료 후 문제 사례를 모아 별도로 검토할 수 있다.
- 따라서 이것은 영구적인 최종 taxonomy가 아니라 Phase 2 검증을 위한 frozen checkpoint이다.

이 문서는 Reaction/Target 정의, H1~H4 및 현재 Phase 2 고정 프로토콜의 canonical checkpoint다. 2026-09-17 인간 확정 원문에 따라 보존 공백을 복구했으며 Phase 2 결과에 따른 개정이 아니다. 과거 R1–R8 및 Woni 27 후보는 현재 taxonomy를 대체하지 않는다.

## Reaction taxonomy

현재 Reaction 구조는 다음 10개다.

### 1. 평가·칭찬

콘텐츠, 인물, 제작 결과물 등의 **질·능력·완성도·유용성 등에 대한 긍정적 평가**.

단순 애정이나 응원은 `관계·정서`와 구분한다.

### 2. 관계·정서

인물 또는 채널을 향한 **호감, 애정, 애착, 응원, 팬심 등 관계적·정서적 반응**.

콘텐츠 품질 자체에 대한 칭찬과 구분한다.

### 3. 즐거움·놀이

웃음, 재미와 함께 댓글에서 이루어지는 **따라하기, 재연, 변형, 말장난, 댓글/팬덤 놀이, 창작적 상상 등 놀이성 반응**.

단순히 어떤 장면을 발견하거나 포착했다는 이유만으로 자동 부여하지 않는다.

### 4. 비판·불만

콘텐츠, 품질, 제작, 진행 등에 대한 **부정적 평가·비판·불만**.

### 5. 시청 어려움·회피

콘텐츠를 계속 보거나 소비하는 데 느끼는 **어려움, 부담, 이탈, 스킵, 회피 등 시청 지속의 문제**.

일반적인 콘텐츠 비판과 구분한다.

### 6. 당혹·의문

이상함, 혼란, 뜻밖임, 이해되지 않음 등의 **당혹 또는 의문 반응**.

실제로 답을 얻기 위해 정보를 요청하는 질문은 `내용 참여`와 구분한다.

### 7. 내용 참여

콘텐츠의 내용·주제에 대해 시청자가 **실질적인 인지적 기여(substantive cognitive contribution)**를 하는 반응.

포함:

* 의미 있는 의견·생각
* 해석·추론
* 정보·지식 추가
* 자기 경험을 내용과 실질적으로 연결
* 실제 답을 얻기 위한 질문

단순 관찰, 장면 포착, 짧은 연상·연결만으로는 내용 참여가 아니다.

다른 Reaction도 성립하지 않는 단순 관찰·포착 댓글에는 `Reaction=None`을 허용한다.

### 8. 요청·제안

향후 제작자가 할 수 있는 **콘텐츠, 구성, 출연, 진행 등 미래 행동에 대한 요청이나 제안**.

### 9. 행동 지향

콘텐츠를 본 뒤 댓글 작성자가:

* 현실의 행동을 하거나 했다고 보고하거나,
* 현실 행동을 하려는 의향을 표현하거나,
* 다른 개인·집단·기관 등의 구체적 현실 행동을 요구·촉구하는 반응.

콘텐츠 바깥 현실 행동 또는 그 행동 촉구를 포함한다. 단순 의견·해석은 행동 지향이 아니며, 콘텐츠 제작 행위에 대한 요청은 `요청·제안`과 구분한다.

### 10. 성과 참여

조회·댓글·좋아요 등 콘텐츠 성과를 **직접 높이려는 참여 또는 다른 사람에게 그러한 참여를 요청하는 행동**.

단순히 조회수나 성과 상태를 관찰하는 것은 성과 참여가 아니다.

## Reaction 공통 규칙

* 복수 Reaction 허용.
* 하나의 댓글에 독립적으로 성립하는 Reaction이 여러 개면 multi-label 가능.
* Reaction이 성립하지 않는 댓글에는 `Reaction=None` 허용.
* `None`은 “반응이 없음”이고 `UNKNOWN`과 다르다.
* UNKNOWN은 정보 부족·모호성 등으로 판정할 수 없는 경우다.
* Positive / Negative sentiment는 Reaction taxonomy가 아니다.

## Target taxonomy

Target은:

> **시청자가 무엇에 반응하고 있는가**

를 기록한다.

Content Feature의 존재를 증명하는 분류가 아니다.

### Target 1. 콘텐츠 전체

특정 세부 요소보다 **영상·콘텐츠 전체**를 대상으로 하는 반응.

### Target 2. 내용·소재

영상에서 다루는 **주제, 정보, 사건, 주장, 이야기, 소재 등 내용 자체**를 대상으로 하는 반응.

### Target 3. 인물

출연자, 진행자, 게스트 등 **영상 속 사람**을 대상으로 하는 반응.

### Target 4. 제작·표현

편집, 자막, 촬영, 연출, 음악, 표현 방식 등 **콘텐츠가 만들어지고 표현된 방식**을 대상으로 하는 반응.

### Target 5. 채널·커뮤니티

특정 영상의 내용보다 **채널 자체, 팬덤, 댓글 공동체, 채널의 역사·관계적 맥락**을 대상으로 하는 반응.

### Target UNKNOWN

댓글만으로 무엇을 대상으로 한 반응인지 충분히 판정할 수 없는 경우.

공통:

* 복수 Target 허용.
* Reaction과 Target은 서로 다른 축이다.
* Target은 Content Feature 라벨이 아니다.

## H1

`내용 참여`는 substantive cognitive contribution이 필요하다.

단순 관찰·포착·짧은 연상만으로 내용 참여를 부여하지 않는다.

다른 Reaction도 없다면 Reaction=None 가능.

기존 Phase 1 예시인 “저 장면 뭐야ㅋㅋ” 같은 단순 장면 포착, “OO 닮았다” 같은 짧은 연상·관찰도 이 경계를 따른다.

`관찰·포착`이라는 별도 Reaction을 만들지 않는다.

## H2

`특정 장면/표현 포착`을 Reaction이나 Target으로 추가하지 않는다.

댓글에 **명시적인 timestamp가 존재하면 별도의 raw/metadata 정보로 보존한다.**

예:

`timestamp=32:19`

Timestamp는 **어디/언제**이고 Target은 **무엇**이므로 서로 다른 정보다.

timestamp가 없는 댓글에 대해 **AI가 영상을 보고 특정 장면이나 timestamp를 추정하도록 하지 않는다.**

향후 highly watched/replayed segment 데이터와 결합하는 것은 별도 가능성으로 남긴다.

## H3

모든 수집 댓글은 raw 데이터에 보존한다.

Reaction 분석 포함 여부는 별도의 `analysis_eligible` 또는 동등한 상태로 관리한다.

* 영상 채널 자신의 댓글 → raw 보존, Audience Behavior/Reaction 집계 제외
* 확인된 spam 또는 잘못 수집된 데이터 → raw 보존, 분석 제외, exclusion reason 기록
* 제외된 채널 parent/pinned comment는 viewer reply의 context로 보존 가능
* 실제 viewer reply는 분석 가능
* 직원/부계정/사칭/상업 계정으로 의심된다는 이유만으로 근거 없이 자동 제외하지 않는다.

구체적인 필드명은 구현 단계에서 정할 수 있으며 raw preservation과 analysis eligibility를 개념적으로 분리한다. 더 정교한 spam/commercial-noise detection은 후속 과제로 둔다.

## H4

Phase 1 추가 250개에서:

* 시청 어려움·회피: 3
* 성과 참여: 0

그러나 두 Reaction을 삭제하거나 병합하지 않는다.

Phase 2의 다른 채널에서 계속 관찰한다.

이를 발견하기 위해 의도적으로 oversampling하지 않는다.

## Phase 2 운영 원칙

Phase 2에서는 Reaction 10 + Target 5와 H1~H4를 고정해서 적용한다. taxonomy 설계에 사용되지 않은 새로운 댓글을 사용하며, 기존 Phase 1/개발 노출 데이터는 fresh blind validation 데이터로 취급하지 않는다.

Phase 2 목적:

> Phase 1에서 정리한 Reaction 10 + Target 5 구조가 taxonomy 설계에 사용하지 않은 다른 채널에서도 작동하는지 검증한다.

### 데이터

기본 설계:

* 새로운 채널 2개
* 채널당 댓글 100개
* 총 200개

Reaction taxonomy 설계에 이미 사용한 다음 채널은 **채널 단위로 Phase 2에서 제외한다.**

* 14F
* Woni / 안원잘부
* 침착맨

침착맨 sentiment/topic 400은 댓글 단위로 미사용일 수 있으나 Phase 2는 채널 일반화 검증을 위해 침착맨 채널 전체를 제외한다. 댓글 사용 이력 및 미확정 fresh 상태는 [데이터 장부](data-ledger.md)에 별도로 보존한다. 데이터 삭제 또는 오염 확정이라는 뜻이 아니다.

### 표본

희귀 Reaction을 찾기 위해 댓글을 의도적으로 골라 넣지 않는다.

일반 표본으로 진행한다.

### 실행 중 기준 변경 금지

Phase 2 시작 후 200개가 끝날 때까지:

* Reaction 추가 금지
* Reaction 삭제/병합 금지
* Target 추가/삭제 금지
* 경계 변경 금지

문제 사례가 발견되면 issue/candidate로 별도 기록한다.

200개 실행 종료 후 한꺼번에 검토한다.

## Phase 2 종료 및 최종 closeout

Phase 2는 완료되었으며, 결과에 따라 R9를 `행동 유발`에서 `행동 지향`으로 최소 수정했다. Reaction 11이나 Target 6은 추가하지 않았다. 최종 상태와 Phase 2 표본의 fresh-blind 사용 금지는 [Reaction track closeout](reaction-track-closeout-2026-09-17.md)에 기록한다.

## 문서 성격

- Human-approved: yes
- Phase 1 checkpoint: yes
- Frozen for Phase 2: yes
- Permanent final taxonomy: no (최종 track 상태는 closeout 문서에 기록)
- Mid-Phase-2 revision allowed: no