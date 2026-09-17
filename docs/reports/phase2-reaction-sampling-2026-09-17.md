# Reaction Phase 2 표본 수집 보고 — 2026-09-17

댓글 본문은 이 문서에 없다. Reaction·Target 판정은 하지 않았다.

## 설계 (사람이 확정, 해석하지 않음)

- 채널 2개 × 영상 2개 × 원댓글 50개 = 200개
- 사용 금지 채널: 14F, 안원잘부 / Woni, 침착맨, Carden / 카더정원
- 기준 체계: `docs/reaction-phase1-checkpoint.md` (Phase 2 동결, 수정하지 않음)
- 교체 없음: 분석 대상에서 빠진 댓글을 51번째 댓글로 채우지 않는다

## 채널과 영상

| 슬롯 | 채널 | channel_id | video_id | 게시(UTC) | 길이(초) | 수집 원댓글 |
|---|---|---|---|---|---:|---:|
| A1 | 슈카월드 | `UCsJ6RuBiTVWRX156FVbeaGg` | `tmYmdAykjuQ` | 2026-09-16T10:50:18Z | 1566 | 50 |
| A2 | 슈카월드 | `UCsJ6RuBiTVWRX156FVbeaGg` | `q836AS_27GE` | 2026-09-15T10:11:11Z | 2091 | 50 |
| B1 | MBCNEWS | `UCF4Wxdo3inmxP-Y59wXDsFw` | `bM1KNajYwK0` | 2026-09-17T01:50:38Z | 402 | 50 |
| B2 | MBCNEWS | `UCF4Wxdo3inmxP-Y59wXDsFw` | `J2qqlnRZPFI` | 2026-09-17T00:53:33Z | 351 | 50 |

## 표본

- 원자료 표본: 200개
- 분석 대상(analysis_eligible): 200개
- 제외 사유별: 없음

## 정렬과 선정 방식

- 댓글 정렬: YouTube Data API v3 commentThreads.list order=relevance 기준. YouTube 웹 UI의 Top comments와 동일한 결과인지는 검증하지 않았다.
- 원댓글만 수집(commentThreads의 topLevelComment). 답글은 표본에 넣지 않았다.
- 영상 선정: 업로드 재생목록 최신 200편을 게시 시각 역순으로 보며, 수집 시점 댓글 통계 50 미만·원댓글 50 미만·댓글 사용 중지인 영상은 건너뛰었다. 댓글 내용은 선정에 쓰지 않았다.
- 댓글이 50개 이상인데 라이브·프리미어·180초 이하인 영상이 선정 순번에 오면 멈추도록 했고, 이번 수집에서는 그런 영상이 선정 순번에 오지 않았다.
- 수집 시각(UTC): 2026-09-17T02:43:49+00:00 ~ 2026-09-17T02:43:58+00:00

## 칸별 채움 (200개 중)

| 칸 | 채워진 수 |
|---|---:|
| `channel_id` | 200 |
| `channel_name` | 200 |
| `video_id` | 200 |
| `video_title` | 200 |
| `video_channel_id` | 200 |
| `comment_id` | 200 |
| `text` | 200 |
| `published_at` | 200 |
| `updated_at` | 200 |
| `author_channel_id` | 200 |
| `parent_id` (원댓글이면 비어 있어야 정상 — 비어 있는 수) | 200 |
| `collected_at` | 200 |
| `collection_method` | 200 |
| `ordering_method` | 200 |
| `provenance` | 200 |
| `text_original_returned` | 200 |

저장하지 않은 칸: 작성자 표시 이름, 프로필 이미지, 작성자 채널 URL (요구 칸이 아니다).

## 무결성

- 봉인 표본 SHA-256: `197f9b07028ceb6daf4be7dde66c1642828535483dec4995c30347e1b6737910`
- 원자료 SHA-256: `a3f2d521d4db1ab647bea41b677b78aa7c2733cbe3128ef042c31349fae20202`

## 파일

- 원자료 (원문 포함, Git 제외 경로): `backend/data/phase2-reaction/2026-09-17/raw_collection.json`
- 봉인 표본 (원문 미포함, 원문 해시 포함): `backend/fixtures/phase2-reaction/sealed_sample.jsonl`
- manifest (원문 미포함): `backend/fixtures/phase2-reaction/manifest.json`
- 이 보고서 (원문 미포함): `docs/reports/phase2-reaction-sampling-2026-09-17.md`

## 블라인드

수집 스크립트는 댓글 본문과 영상 제목을 화면에 출력하지 않았다. 댓글 내용으로 영상이나 댓글을 고르거나 바꾸지 않았고, 키워드 검색·감성·주제·Reaction·Target 판정을 하지 않았다.
