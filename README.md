# YT Trend

유튜브 채널 URL 하나를 넣으면 영상을 콘텐츠 유형으로 나누고, 유형별 성과와 댓글 피드백을 한 장의 리포트로 돌려주는 분석 파이프라인.

## 문서

| 파일 | 내용 |
|---|---|
| [youtube-trend-pipeline-concept.md](youtube-trend-pipeline-concept.md) | 구상안 초안 v0.1. 문제 정의, 데이터 소스와 제약, 파이프라인 8단계, 한계 |
| [youtube-trend-decisions.md](youtube-trend-decisions.md) | 아키텍처 설계 전 확정한 결정 사항, 기본값, 실패·재개 정책, 미결 사항 |
| [youtube-trend-architecture.md](youtube-trend-architecture.md) | 아키텍처 v0.1. 모듈 구성, SQLite 스키마, 작업 상태 흐름, API 명세, Claude 호출 설계, 구현 순서 |

읽는 순서는 위 표 순서와 같다.

## 현재 상태

- 2026-09-09: 구상, 결정, 아키텍처 문서 작성 완료. 구현 전.
- 다음 단계: 구현 1단계 (수집 모듈). YouTube Data API 키와 첫 대상 채널 URL 필요.

## 기술 스택 (확정)

- 백엔드: Python, FastAPI, SQLite
- 분석: YouTube Data API v3, Claude API
- 프론트: Next.js (직접 디자인·구현)
- 실행: 로컬 우선, 배포는 추후
