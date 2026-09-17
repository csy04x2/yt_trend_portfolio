# 관측 가능한 변수 우선 관계 분석: 실행 프로세스

현재 방법론 정본: [Stage 08/09 책임 경계](youtube-trend-architecture.md), [Feature A-1/A-2/A-3 구조](content-feature-structure.md), [Reaction/Target 및 Phase 2](../reaction-phase1-checkpoint.md). 아래 실행 계획은 과거 기록이며 구현 완료를 뜻하지 않는다. 현재 Feature 작업은 Reaction보다 후순위로 일시 정지돼 있다.

## 당시 결정 (과거 실행 계획)
개인서사·진정성·정보밀도 semantic feature는 보류한다. 관측 변수로 콘텐츠 특성 → 행동 차이 → 성과 차이 → 시간 변화 → 신뢰도를 먼저 계산한다. 이는 관측된 관계 분석이며 성공 원인이나 조회수 보장으로 표현하지 않는다. 설명되지 않는 패턴이 반복될 때만 semantic feature를 추가한다.

## 실행 순서와 완료 기준

| 순서 | 작업·산출물 | 완료 기준 |
|---|---|---|
| 1 | 지표 계약: 영상/댓글/thread/snapshot 키, 분자·분모·관측시각·결측 사유·출처·버전 정의 | 모든 지표에서 0과 미수집을 구분하고 원자료까지 추적 가능 |
| 2 | 수집 보강: 댓글 author 식별키, parent_id, replies pagination, 게시시각, 수집시각, 영상 통계 snapshot | 답글 일부 반환을 전수로 취급하지 않으며 수집 실패·중단·coverage 기록 |
| 3 | 영상 단위 결합 테이블: 길이, 포맷, 코너, 게시시점/간격 + 행동/성과 + 신뢰도 | 영상 중복 없음; 재생목록 중복은 다중 소속으로 보존; 연간 모음은 코너에서 제외 |
| 4 | 조회배수·초과성과 + Reaction lift + reply/thread + timestamp cluster 계산 | 아래 A+ 계약 충족; 실데이터와 작은 정답 fixture로 검증 |
| 5 | feature별 관계 계산: 비교군, 효과크기, 영상 단위 분산/구간, leave-one-video-out | 작은 표본·결측·한 영상 의존도를 결론 옆에 표시; 탐색적 다중 비교 명시 |
| 6 | snapshot 누적 후 rolling·feature 효과 변화·변곡 후보 | 동일 관측 나이/정의로 비교; 과거 24h 조회수를 현재 누적치에서 역산하지 않음 |
| 7 | 08 사실·관계 계산/evidence JSON → 09 Insight 결과 선택·해석 → 조회·대시보드 | LLM 문장마다 evidence_id; 숫자는 계산 결과 인용; 부족한 근거는 보류; 원문/그래프 클릭 가능 |

신뢰도는 마지막 부가기능이 아니라 1단계부터 모든 결과에 붙인다. 현재 댓글 2개 영상 표본은 수집·집계 검증용이며 관계 효과 검증에 부족하다. 기간·길이축·코너를 나눈 표본 확장 계획을 먼저 확정한다. 정확한 목표 n은 관측 분산과 검출하려는 최소 효과로 정하며 n≥5만으로 신뢰성을 인정하지 않는다.

## A+ 다섯 축의 계약

| 축 | 계산·필요 데이터 | 검증/표현 기준 |
|---|---|---|
| 조회배수 / 초과성과 | 동일 채널·포맷·업로드 후 관측 나이 비교군 baseline. views/baseline 및 actual−expected. expected는 우선 단순 비교군 기준 | baseline 구성/n/기간 공개. 예측 모델은 시간순 holdout과 과거 데이터만 사용. 비교군 부족 시 NULL |
| Reaction lift | 영상별 R 비중 − 비교 영상별 R 비중 평균, %p 단위. 댓글 수 가중값은 별도 표기 | taxonomy/protocol/모델/인간 gold 구분. 영상 단위 불확실성. 큰 댓글 영상 하나가 기준을 독점하지 않도록 함 |
| reply/thread | 고유 원댓글 thread와 parent 관계, replies/top-level, thread 참여자·크기·집중도 | 총 API replyCount와 실제 수집 replies를 구분. 중복 제거. 수집분 지표인지 전수인지 표시 |
| timestamp cluster | 유효 영상 시각을 초/영상길이로 변환, 시간창별 고유 댓글/작성자 집계 | 같은 댓글의 반복 시각 중복 억제, 길이 밖 시각 제외, 창 크기 공개·민감도 확인. 시청 유지율로 해석하지 않음 |
| feature 효과의 시간 변화 | 위 효과를 기간별 같은 정의로 계산. 게시 cohort와 업로드 후 나이를 분리 | 기간별 n/coverage/분산과 구성 변화 표시. 변곡은 충분한 기간 확보 후 후보로 제시 |

## 변수 채택 원칙
- 우선 수집: 길이·게시시각·통계 snapshot·원댓글/답글 식별자·작성자 식별키·본문/시각·수집상태. 업로드 간격은 수집 범위 경계에서 이전 영상 누락 여부를 표시한다.
- 코너는 실제 시리즈 목록을 검토해 정의한다. topic은 보조. Shorts 여부가 길이 규칙 추정이면 실제 포맷 확인값과 분리한다.
- 게스트는 명시된 메타데이터/수동 확인부터 사용한다. 이름 미검출을 게스트 없음으로 바꾸지 않는다.
- 반복 참여는 수집된 댓글 작성자의 반복이며 전체 시청자의 재방문이 아니다. unique commenter rate도 관측된 참여 폭이다.
- Reaction은 이미 semantic labeling이므로 새 콘텐츠 semantic feature 보류와 구분한다. gold와 모델 판정을 혼합해 정확도를 주장하지 않는다.
- 사후 Reaction/답글을 같은 시점 최종 조회수 예측에 사용하면 정보 누출이다. 사후 설명과 사전 예측 데이터셋을 구분한다.

## 신뢰도 및 LLM 입력
각 관계에 feature, outcome, comparison_group, observation_window, estimate, unit, video_n, comparison_n, collected/available coverage, missing_rate, label_source/version/confidence, variance/interval, leave_one_out_effect_range, time_coverage, evidence_ids를 저장한다. coverage 분모를 알 수 없으면 unknown이다. 한 영상 의존도는 제거 전후 효과를 공개하고 부호 전환도 표시한다. 낮은 모델 confidence는 보조 신호이며 검증 정확도가 아니다.

LLM은 통계를 직접 만들어내지 않고 이 레코드를 요약한다. 예: 효과 +24%p / n=4 / 수집 coverage 31% / 특정 영상 제거 시 효과 소멸 → 흥미로운 후보지만 근거 부족. 현재 생성된 리포트의 문장 다듬기 기능을 이 evidence 계약으로 확장하는 작업이 필요하다. 조회 화면 자체가 이 분석 엔진 역할을 대신하지 않는다.

## 현재 상태와 다음 구현 단위
2026-09-10: 침착맨·카더정원 각각 영상 300개, 댓글 400개(2개 영상) 기존 sentiment/topics v2 반영 완료. 판정 출처 보존과 제목 confidence 복원, 유형 성과 재집계, 저확신도 결론 보류를 적용했다. A+ 5축이 모두 구현됐다는 의미는 아니다.

새 원격 feat/offline-comment-labeling 브랜치 fe333ae에서 Reaction v0.2.3 / protocol v0.2 checkpoint를 확인했다. v0.1 gold120 평가는 93/120(77.5%)이며 v0.2 성능으로 전용하지 않는다. blind holdout 60의 봉인 예측은 열지 않았고 gold 평가 전이다. 아직 main에 병합하지 않았다.

다음 구현은 지표 계약 + reply/snapshot 수집 구조 + 영상 단위 evidence 테이블을 한 묶음으로 진행한다. 이후 A+ 계산기를 붙이고 마지막에 대시보드 mock 데이터를 실제 evidence로 교체한다. 이번 문서는 실행 설계이며 아직 수행하지 않은 수집/Reaction 평가/시간 분석을 완료로 표시하지 않는다.
