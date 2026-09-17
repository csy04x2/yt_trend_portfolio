# YT Trend

유튜브 채널 URL 하나를 넣으면 영상을 콘텐츠 유형으로 나누고, 유형별 성과와 댓글 피드백을 한 장의 리포트로 돌려주는 분석 파이프라인.

## 폴더 구조

```
README.md
docs/
  design/     구상 · 결정 · 아키텍처 · 아이디어 · 분석 계획 (읽는 순서는 아래 표)
  reports/    진행 보고(판 번호) · 팀원 개발 정리 · 소개 슬라이드
  diagrams/   아키텍처 · 파이프라인 흐름 · 파이프라인 현황 (HTML 한 장짜리)
  prototype/  리포트 화면 시제품 — 템플릿, 빌드 산출물, evidence JSON, 스크린샷
backend/
  app/        파이프라인 코드 (clients · db · pipeline · prompts)
  scripts/    채널별 일회성 실행 스크립트
  fixtures/   사람이 _expect를 단 표본과 라벨 결과
  feature_outcome/  특징 × 성과 — 급등 영상 표시·분모 재계산·전체/제외 두 판·홀드아웃 봉인 (판정 파일은 입력)
  exports/    DB 없이 검수하는 라벨·리포트 내보내기
  tests/
```

## 현재 인간 확정 방법론 정본

아래 정본을 먼저 읽는다. 이전 설계·보고서는 당시 상태를 보존하며 상충하는 과거 표현은 현재 결정을 대체하지 않는다. 이번 문서 복구는 구현 완료를 의미하지 않는다.

| 정본 | 보존 범위 |
|---|---|
| [Reaction Phase 1 Checkpoint](docs/reaction-phase1-checkpoint.md) | Reaction 10·Target 5+UNKNOWN 정의, H1~H4, Phase 2 새 채널 2×100 고정 프로토콜 |
| [Woni discovery checkpoint](docs/reports/woni-reaction-discovery-checkpoint.md) | 종료된 독립 discovery, 27 후보, correction audit |
| [Content Feature Structure](docs/design/content-feature-structure.md) | A-1/A-2/A-3와 인간 discovery → AI 자동 추출 → 인간 검증 |
| [Architecture 현재 경계](docs/design/youtube-trend-architecture.md) | Stage 08 사실·관계 계산 / Stage 09 Insight 해석 |
| [Data Ledger](docs/data-ledger.md) | 데이터 provenance·사용 이력 및 Phase 2 채널 제외 정책 구분 |
| [Control Tower checkpoint](docs/reports/control-tower-checkpoint-2026-09-15.md) | 변경 없이 유지하는 별도 고정 reference population 정책 |
| [Reaction Phase 2 수집 보고](docs/reports/phase2-reaction-sampling-2026-09-17.md) | 슈카월드·MBCNEWS 200댓글 표본 수집 방식과 봉인 해시 (원문·판정 없음) |

## 이전 설계·진행 문서

| 파일 | 내용 |
|---|---|
| [youtube-trend-pipeline-concept.md](docs/design/youtube-trend-pipeline-concept.md) | 구상안 초안 v0.1. 문제 정의, 데이터 소스와 제약, 파이프라인 8단계, 한계 |
| [youtube-trend-decisions.md](docs/design/youtube-trend-decisions.md) | 아키텍처 설계 전 확정한 결정 사항, 기본값, 실패·재개 정책, 미결 사항 |
| [youtube-trend-architecture.md](docs/design/youtube-trend-architecture.md) | 아키텍처 v0.1. 모듈 구성, SQLite 스키마, 작업 상태 흐름, API 명세, Claude 호출 설계, 구현 순서 |
| [ideas.md](docs/design/ideas.md) | 아직 결정이 아닌 아이디어. 채택되면 결정·아키텍처 문서로 옮긴다 |
| [docs/reports/2026-09-17-progress-report_v4.html](docs/reports/2026-09-17-progress-report_v4.html) | 진행 보고 (최신). 09-17 확정 정본(Reaction 10 + Target 5, Phase 2) 반영, 원천 자료 두 PC 분산, 다음 조치 6가지 |
| [docs/reports/2026-09-10-progress-report_v3.html](docs/reports/2026-09-10-progress-report_v3.html) | 진행 보고 3판. 영상 유형 두 축, 쇼츠/롱폼 성과 역전, 2판 수치 정정 |
| [docs/reports/2026-09-09-progress-report_v2.html](docs/reports/2026-09-09-progress-report_v2.html) | 진행 보고 2판. 댓글 판정 282건과 호응·논쟁 지표 |
| [docs/reports/2026-09-09-dev-summary.html](docs/reports/2026-09-09-dev-summary.html) | 팀원 개발 정리. 선점 필터 PR, 감성 3분류의 한계, Reaction taxonomy 초안 |

보고서는 크게 고칠 때마다 `_v2`, `_v3`으로 번호를 올리고 이전 판을 남긴다.
위 표는 항상 최신판을 가리킨다.

현재 방법론은 위 정본 표를 우선하고, 이전 설계·진행 문서는 역사적 맥락으로 읽는다.

## 과거 상태 (2026-09-09 기록)

- 2026-09-09: 구상, 결정, 아키텍처 문서 작성 완료. 구현 전.
- 2026-09-09: 세 문서와 다이어그램 교차 검수 후 반영. 해석 테이블 키에 모델 추가, 댓글 커서
  이원화, 조회 배수 분모를 미결로 되돌림, 워커 블로킹 명시, Claude 거절 처리 추가.
- 다음 단계: 구현 1단계 (수집 모듈). YouTube Data API 키와 첫 대상 채널 URL 필요.
  결정 문서 3장의 미결 사항 중 **라이브·프리미어 판정**과 **약관의 데이터 보관 조항**은
  수집 코드를 쓰기 전에 정해야 한다.

## 기술 스택 (확정)

- 백엔드: Python, FastAPI, SQLite
- 분석: YouTube Data API v3, Claude API
- 프론트: Next.js (직접 디자인·구현)
- 실행: 로컬 우선, 배포는 추후
