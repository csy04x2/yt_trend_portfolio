# YT-Trend Data Ledger

## 1. 목적과 관리 원칙

이 장부의 목적은 언제든 다음 질문에 답할 수 있게 하는 것이다.

1. YT-Trend가 어떤 데이터를 보유하고 있는가?
2. 어느 채널의 데이터인가?
3. 몇 개 영상/댓글/행인가?
4. 원본(raw)은 어디에 있는가?
5. 가공·분석 결과는 어디에 있는가?
6. 어떤 실험이나 분석에 이미 사용됐는가?
7. 사람이 이미 내용을 본 데이터인가?
8. 새로운 blind 검증에 사용할 수 있는가?
9. 같은 데이터의 파생본을 별도 데이터로 잘못 세고 있지 않은가?

**파일 수와 독립 데이터 수를 구분한다.** 같은 comment_id 집합의 여러 분석 결과는 새로운 데이터셋으로 세지 않는다. 영상·댓글을 합산하지 않으며 subset, derivative, backup을 독립 데이터로 중복 계산하지 않는다. 파일명 속 숫자만으로 규모를 확정하지 않는다.

이 문서는 데이터 자산의 출처, 위치, 사용 이력 및 blind 재사용 상태를 기록한다. 데이터 분석, taxonomy 설계, Reaction 판정, Finding Engine 및 Relative Performance 방법론 변경은 수행하지 않는다. 댓글 원문, 개인정보, author_name은 기록하지 않는다.

### 기록 근거와 확인 범위

- 기록일: 2026-09-17.
- 아래 데이터 규모, ID audit, 과거 사용 이력 및 외부 보존 위치는 이번 요청에서 제공된 **인간 확정 사실/기존 audit 결과**를 근거로 기록했다. 이번 문서 작업에서 DB나 댓글 원문을 재분석한 결과로 표현하지 않는다.
- 이번에 직접 확인한 Git 상태: 저장소 루트 `C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/yt-trend-integration`, remote `https://github.com/bbamindol-dev/yt-trend.git`, branch `integration/feature-discovery-observable`, HEAD `12248c5287e291f094df27bd560a0886836ace38`. 작성 전 `git status --short` 출력은 비어 있었다.
- 사실과 판단을 구분한다. `NO` 및 조건부 후보 상태는 아래 확정 이력에 따른 관리 판단이다. 미확정 값은 **확인 필요**로 남긴다. 검색에서 사용 증거를 찾지 못했다는 사실은 사용되지 않았다는 증명이 아니다.
- 사람의 내용 노출 범위와 human gold validation 수행 여부는 별개다. 인간 gold 검증이 없었다고 인간이 내용을 보지 않았다고 간주하지 않는다.
- 상태는 `usable`, `conditional`, `used`, `source check needed`만 사용한다. `used`는 이미 사용된 자산을 뜻하며 다른 목적의 모든 재사용을 금지한다는 의미는 아니다.

### 경로 표기

- `REPO` = `C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/yt-trend-integration`
- `BASE` = `C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20`
- `OUTPUTS` = `BASE/outputs` (Git repo 밖)
- `LEGACY` = `BASE/yt-trend`
- 별도 표시 없는 `backend/...`, `docs/...`는 REPO 기준 경로다. historical DB/batch 경로는 과거 논리적 경로이며 현재 존재를 보증하지 않는다.

## 2. 데이터 장부

A–F는 데이터 계보 식별자다. B-V는 B 댓글과 별개인 영상 자산이다. G/H는 파생·보존 자산 묶음이며 독립 댓글 모집단이 아니다. 이 표의 행 수를 독립 데이터셋 수로 해석하지 않는다.

| 데이터명 | 채널 | 규모 | 데이터 유형 | raw 존재 | raw 위치 | 주요 가공본/분석 위치 | 기존 사용 이력 | 인간 내용 노출 | Reaction fresh blind | 현재 상태 | 주의사항 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A. 14F 댓글 | 14F 일사에프 | 282 unique comments / 2영상 | 댓글·라벨·Reaction 실험 | 현재 raw DB 존재 확인 필요 | historical `backend/data/yt_trend.db` | `backend/exports/comment-labels.json`, `.csv`; 74/117 fixture 및 gold/holdout 계보 | Reaction, comment-pilot 등 | 과거 실험 노출 확정; 인간의 구체적 열람 범위 확인 필요 | NO | used | 모든 historical Reaction 모집단은 동일 282; 파생본 합산 금지 |
| B. Woni Reaction 댓글 | Woni / 안원잘부 | 400 unique comments / 2영상 / 200건씩 | 댓글·discovery·라벨 | raw 별도 보존 여부 확인 필요 | 확인 필요 | `backend/fixtures/woni-reaction-open-discovery-400.json`; `backend/fixtures/labeled/comment-labels_woni_400.json` | independent Reaction open discovery, 27 initial candidates 및 comment-level assignments, taxonomy/vNext 설계 | 인간의 구체적 열람 범위 확인 필요 | NO | used | 두 파일 shared IDs=400; 800건 아님 |
| B-V. Woni Content Feature | Woni / 안원잘부 | 정확한 규모 확인 필요 | 영상 Content Feature | 확인 필요 | 확인 필요 | `backend/fixtures/labeled/video-types_woni_107.json` | 정확한 provenance/use 확인 필요 | 확인 필요 | 확인 필요; 댓글 후보로 자동 등록하지 않음 | source check needed | 파일명 107만으로 규모 확정하지 않음; B의 댓글과 합산 금지 |
| C. 침착맨 Reaction Phase 1 | 침착맨 | 300 unique comments / 300행 / 10영상 | 댓글 raw·Phase 1 분할 | 있음(제공된 audit) | `OUTPUTS/raw-comment-pilot-seed42/collection/comments.jsonl` | `OUTPUTS/reaction-matrix-phase1/`의 50/250 comments 및 manifest | 300 전체 Reaction Phase 1/vNext 검토 | 전체 실험 사용 확정; 인간의 구체적 열람 범위 확인 필요 | NO | used | raw 유실 아님; reserve 파일 250건은 fresh reserve 아님 |
| D. 침착맨 sentiment/topic 댓글 | 침착맨 | 400 unique comments / 2영상 / 200건씩 | sentiment/topics v2 라벨 | raw 별도 보존 여부 확인 필요 | 확인 필요 | `backend/exports/resumed-analysis-20260910T074639Z/chim-labels.json`, `chim-report.json` | 현재 검색에서 확인된 사용은 sentiment/topic; resumed analysis에 R1–R8 미포함 | human gold validation 없음; 원문 열람 범위 확인 필요 | 댓글 단위 확인 필요; Phase 2 채널 제외 | conditional | C와 댓글·영상 overlap 모두 0; 침착맨 채널 전체 Phase 2 제외 |
| E. 침착맨 영상 DB / Content Feature | 침착맨 | 300영상; comments=0 | 영상·통계·Feature 자산 | 있음(영상 DB; 제공된 audit) | `LEGACY/backend/data/chim.db` | content/discovery/split/90-video packet 및 `docs/prototype/chim-evidence.json` | Content Feature / Feature Discovery; 세부 이력 확인 필요 | 확인 필요 | 확인 필요; 댓글 raw로 사용 불가 | source check needed | 댓글 300/400과 별도 축; 관련 파일과 DB의 세부 대응 확인 필요 |
| F. Carden 댓글 분석 | 카더정원 | 과거 채널 300영상; 댓글 표본 2영상 × 200건=400 | sentiment/topic v2 라벨·report | 있음(2026-09-17 저장소에 추가) | `backend/data/carden.db` (Git 추적; 이 파일만 `backend/data/` ignore 예외로 강제 추가); historical backup `backend/data/backups/carden-<timestamp>.db` | `backend/exports/resumed-analysis-20260910T074639Z/carden-labels.json`, `carden-report.json`; historical batches | sentiment/topic v2; 해당 분석에 R1–R8 미포함 | human gold validation 없음; 원문 열람 범위 확인 필요 | CONDITIONAL / 확인 필요 | source check needed | raw는 복구됨; Reaction 사용 이력 확인은 여전히 별도 조건; DB에 작성자 닉네임(author_name) 포함 |
| G. Feature Discovery 파생 산출물 | source별 확인 필요 | 독립 규모 확인 필요; 추가 댓글로 계산하지 않음 | probe·split·registry·predictions·annotations·report 등 | source별 확인 필요 | source dataset에 연결; 불명확하면 확인 필요 | 아래 G 목록 | 산출물별 이력 확인 필요 | 산출물별 확인 필요 | source 및 사용 이력 확인 필요 | source check needed | source가 확인되면 해당 계보의 파생본으로 연결 |
| H. backup tree | source별 | 독립 규모로 계산하지 않음 | 안전 복사본·과거 상태 | 파일별 확인 필요 | `BASE/backups/feature-discovery-pre-integration-20260914T041808Z` | 같은 backup tree | 보존 | 원본 이력 및 별도 열람 확인 필요 | 원본의 사용/노출 이력 승계; 확인 필요 | source check needed | 복사본은 새 blind 데이터가 아님 |
| I. Reaction Phase 2 표본 | 슈카월드, MBCNEWS | 200 top-level comments / 4영상 / 50건씩 | 댓글 raw·봉인 표본 | 있음 | 수집 PC(`C:/Users/EZ/Desktop/yt-trend`)의 gitignored `backend/data/phase2-reaction/2026-09-17/raw_collection.json`; 판정 담당자에게 파일로 전달한 사본 | `backend/fixtures/phase2-reaction/sealed_sample.jsonl`, `manifest.json`(원문 없음); `docs/reports/phase2-reaction-sampling-2026-09-17.md` | Reaction Phase 2 판정용으로 수집; 수집 시점 판정·분포 계산 없음 | 수집 과정에서 사람·모델 원문 열람 없음; 판정용 원문 전달은 2026-09-17 | YES(수집 시점) | usable | 봉인 표본·raw 수정 금지, 판정 결과는 별도 파일; raw는 GitHub에 올리지 않음 |

## 3. 데이터별 출처와 계보

### A. 14F 댓글 282

`backend/exports/comment-labels.json`의 source metadata는 `backend/data/yt_trend.db (comment_labels + comments + comment_screens)`이다. declared=282, actual=282이며 독립 댓글은 282개, 영상은 2개다. CSV는 같은 export 계열이며 추가 모집단으로 세지 않는다.

| 영상 ID | 댓글 수 |
|---|---:|
| EorZZyZ2d0s | 208 |
| hwZSXe3VaN8 | 74 |

파생 파일:

- `backend/fixtures/labeled/14f_hwZSXe3VaN8.json`: 74 top-level comments, 282에 포함.
- `backend/fixtures/labeled/reaction-recheck_EorZZyZ2d0s_neutral.json`: 117 comments, 117/117 모두 282와 overlap.

제공된 historical Reaction ID audit:

- 전체 historical Reaction population = 동일한 282 comments.
- Gold90=90; Set4=30; Gold90 ∩ Set4=0; Gold120=120.
- Holdout60=60; Holdout60 ⊂ 282; Holdout60 ∩ Gold120=0.
- union(282, Gold120, Holdout60)=282.

Gold/Holdout/PassA/PassB/hybrid 파일은 추가 독립 댓글이 아니다. historical Reaction 출력은 작업공간 섹션의 OneDrive 저장소에 다수 보존되어 있다. 개별 파일별 canonical 경로는 확인 필요다. 전체 282는 과거 Reaction/comment-pilot 등에 노출되었으므로 Reaction fresh blind=NO, 상태=used다.

### B. Woni / 안원잘부

완료/종료된 discovery track이다. 27개 후보와 Pass 2 correction audit(CORRECT 32, KEEP_UNCLEAR 5)의 정본은 [Woni discovery checkpoint](reports/woni-reaction-discovery-checkpoint.md)다.

`backend/fixtures/woni-reaction-open-discovery-400.json`과 `backend/fixtures/labeled/comment-labels_woni_400.json`은 각각 400 IDs를 가지며 shared IDs=400이다. 동일 원본 400댓글의 서로 다른 분석/표현으로 기록한다. 2영상에서 각 200댓글이다.

400댓글은 independent Reaction open discovery, 27 initial Reaction candidates 발견, auditable comment-level assignments에 사용되었고 Reaction taxonomy/vNext 설계에 영향을 주었다. Reaction fresh blind=NO, 상태=used다.

`backend/fixtures/labeled/video-types_woni_107.json`은 별도 content/video 자산 B-V다. 정확한 provenance/use와 실제 규모는 확인 필요이며 댓글 400과 합산하지 않는다.

### C. 침착맨 Reaction Phase 1

raw는 유실되지 않았다. repo 밖 실제 위치:

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/outputs/raw-comment-pilot-seed42/collection/comments.jsonl`

제공된 audit: JSONL rows=300, unique comments=300, videos=10. 필드는 `video_id`, `comment_id`, `text`, `published_at`, `updated_at`, `collected_at`, `is_reply`, `source`다. 필드명만 기록하며 내용은 복사하지 않는다.

| OUTPUTS 기준 파생 경로 | 건수 | 필드 |
|---|---:|---|
| `reaction-matrix-phase1/phase1-comments.json` | 50 | video_id, comment_id, text |
| `reaction-matrix-phase1/phase1-manifest.json` | 50 | video_id, comment_id |
| `reaction-matrix-phase1/reserve-comments.json` | 250 | video_id, comment_id, text |
| `reaction-matrix-phase1/reserve-manifest.json` | 250 | video_id, comment_id |

300 raw = Phase1 50 + reserve 250. comments와 manifest는 같은 분할의 다른 표현이다. 300 전체는 Reaction Phase 1/vNext 검토에 이미 사용되었다. Reaction fresh blind=NO, 상태=used이며 현재 fresh reserve=0이다. `reserve`라는 파일명이 미사용 상태를 보증하지 않는다.

### D. 침착맨 sentiment/topic 400

결과 경로:

- `backend/exports/resumed-analysis-20260910T074639Z/chim-labels.json`
- `backend/exports/resumed-analysis-20260910T074639Z/chim-report.json`

400 unique comments, 2영상, 영상당 200댓글이다. 기존 sentiment/topics v2 분석이며 인간 gold validation은 수행되지 않았다. R1–R8 Reaction 분석은 해당 resumed analysis에 포함되지 않았다.

| 비교 항목 | Reaction Phase 1 (C) | sentiment/topic (D) | 공통 |
|---|---:|---:|---:|
| unique comments | 300 | 400 | 0 |
| videos | 10 | 2 | 0 |

제공된 ID audit에서 total distinct comments=700으로 확인되었다. 두 자산은 완전히 별개의 댓글 표본이다. 현재까지 사용 이력 검색에서 확인된 것은 sentiment/topic 분석뿐이며 Reaction taxonomy/Reaction Matrix 입력으로 사용됐다는 증거는 발견되지 않았다. 이것을 절대로 사용되지 않았다는 의미로 확대하지 않는다.

댓글 단위 Reaction fresh 여부는 확인 필요이며 상태=conditional을 유지한다. sentiment/topic 라벨 존재 자체와 Reaction blind contamination을 구분한다. 댓글 단위로 미사용일 수 있으나 Phase 2는 채널 일반화 검증을 위해 침착맨 채널 전체를 제외한다. 기존 Phase 2 조건부 후보 표기는 현재 [Phase 2 프로토콜](reaction-phase1-checkpoint.md)로 대체한다. 원문 입력 확보, Reaction 설계 노출 및 기존 판정 여부는 여전히 확인 필요다. 데이터 삭제나 오염 확정을 뜻하지 않는다.

### E. 침착맨 영상 300 DB와 Content Feature

DB 위치:

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/yt-trend/backend/data/chim.db`

제공된 read-only audit 결과:

| 테이블 | 행 수 |
|---|---:|
| channels | 1 |
| videos | 300 |
| video_stats_snapshots | 300 |
| comments | 0 |
| comment_labels | 0 |
| comment_screens | 0 |

이 DB는 audit 당시 상태에서 침착맨 댓글 raw DB가 아니다. C/D의 댓글 원본 위치로 연결하지 않는다.

관련 Content Feature / Feature Discovery 자산 예시는 `chim-content.json`, `labels-title-regex-300.json`, `split.csv`, `packet/blind_discovery.csv`, `packet/blind_discovery.jsonl`, `docs/prototype/chim-evidence.json`이다. 파일명만 제공된 항목의 정확한 전체 경로 및 DB와의 세부 계보는 확인 필요다. 90-video discovery packet 등은 영상 자료이며 독립 댓글 수에 더하지 않는다. CSV/JSONL 같은 표현별 파일을 새 표본으로 자동 계산하지 않는다.

### F. Carden / 카더정원

결과 경로:

- `backend/exports/resumed-analysis-20260910T074639Z/carden-labels.json`
- `backend/exports/resumed-analysis-20260910T074639Z/carden-report.json`

확인된 과거 상태는 채널 300영상, sampled videos=2, 200 comments/video, 400 labeled comments다. 채널 영상 수와 댓글 표본 영상 수를 구분한다. sentiment/topic v2이며 해당 분석에 R1–R8 Reaction은 포함되지 않았고 human gold validation도 없었다. channel announcements/performer comments가 포함되었을 가능성이 있어 표본 구성은 확인 필요다.

historical batch 경로는 `backend/data/batches/carden/comments/carden_001.result.json`부터 `carden_020.result.json`까지다. 과거 `resume_channel_analysis.py` 기준 20 result files × 20 = 400 unique comment IDs였다. 당시 DB는 `backend/data/carden.db`, backup 경로는 `backend/data/backups/carden-<timestamp>.db`였다. 실제 backup 파일의 현재 존재 및 복구 가능성은 확인 필요다.

현재 audited workspace에서는 carden.db/backup raw source가 복구되지 않았다. 이 사실을 외부 백업까지 모두 없다는 의미로 확장하지 않는다. Reaction 사용 증거가 현재 확인되지 않은 문제와 raw source 미복구 문제를 별도로 관리한다. raw 미복구만으로 오염됐다고 단정하지 않는다.

2026-09-17 추가: 수집 PC(`C:/Users/EZ/Desktop/yt-trend`)에 남아 있던 `backend/data/carden.db`를 사람 지시에 따라 바이트 그대로 저장소에 올렸다. 1,024,000 bytes, SHA-256 `39b60f9e8a063ad2e99fc3c07d5d247febd86a4983b512488aeff6a41fcfb734`. `comments` 400건의 comment_id 집합이 `carden-labels.json` 400건과 정확히 같다. 같은 DB에 영상 300, 통계 스냅샷 302, 댓글 screen·라벨 각 400, 영상 유형 라벨 369, report 9행이 있다. 댓글 원문, `author_channel_id`, `author_name`이 포함되어 있으며 사람이 원본 그대로 올리기로 결정했다. raw source 복구 조건은 충족됐지만 Reaction 사용 이력 확인 조건은 그대로 남는다.

Reaction fresh blind=CONDITIONAL / 확인 필요, 상태=source check needed다. Reaction 사용 이력 확인 전에는 Phase 2 입력으로 사용하지 않는다.

### G. Feature Discovery / 파생 산출물

다음은 독립 Audience Behavior 댓글 데이터로 자동 계산하지 않는다.

- `comment-content-feasibility-probe/*`
- `chim-development90-labelability-*`
- `blind_discovery.*`
- feature-discovery report
- `split.csv`
- registry
- predictions
- annotations
- human-review HTML
- `stage2_evidence/*`
- backup copies

이는 자산 유형/경로 패턴 목록이며 각 파일의 실제 위치·규모·source 연결은 확인 필요다. source가 확인되면 A–F 또는 별도 확인된 source dataset의 파생 산출물로 연결한다. source가 불명확하면 확인 필요로 남기며 독립 댓글 수에 포함하지 않는다.

### H. backups

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/backups/feature-discovery-pre-integration-20260914T041808Z`

동일 파일의 안전 복사본/과거 상태 보존으로 취급한다. 새로운 독립 데이터가 아니며 복사·복구가 기존 사용/노출 이력을 초기화하지 않는다. 파일별 source 대응과 복구 가능성은 확인 필요다.

### I. Reaction Phase 2 표본 (2026-09-17 수집)

기준 정본 [Phase 1 checkpoint](reaction-phase1-checkpoint.md)의 Phase 2 설계(새 채널 2개 × 100댓글)를 채널 2개 × 영상 2편 × 원댓글 50개로 수집했다. 수집기는 `backend/scripts/phase2_collect.py`다.

| 슬롯 | 채널 | channel_id | video_id | 원댓글 |
|---|---|---|---|---:|
| A1 | 슈카월드 | `UCsJ6RuBiTVWRX156FVbeaGg` | `tmYmdAykjuQ` | 50 |
| A2 | 슈카월드 | `UCsJ6RuBiTVWRX156FVbeaGg` | `q836AS_27GE` | 50 |
| B1 | MBCNEWS | `UCF4Wxdo3inmxP-Y59wXDsFw` | `bM1KNajYwK0` | 50 |
| B2 | MBCNEWS | `UCF4Wxdo3inmxP-Y59wXDsFw` | `J2qqlnRZPFI` | 50 |

- 수집 시각: 2026-09-17T02:43:49Z–02:43:58Z (UTC). 정렬: YouTube Data API v3 `commentThreads.list order=relevance`. 웹 화면의 Top comments와 같은지는 검증하지 않았다.
- 규모: raw 200, analysis_eligible 200, 채널 본인 댓글 0, 교체 없음.
- 제외 채널: 14F, Woni / 안원잘부, 침착맨, Carden / 카더정원 (수집 지시에서 사람이 지정).
- raw: `backend/data/phase2-reaction/2026-09-17/raw_collection.json` (gitignored, 수집 PC `C:/Users/EZ/Desktop/yt-trend`에만 있음). 312,891 bytes, SHA-256 `a3f2d521d4db1ab647bea41b677b78aa7c2733cbe3128ef042c31349fae20202`. 같은 파일을 판정 담당자에게 파일로 전달했다.
- 봉인 표본: `backend/fixtures/phase2-reaction/sealed_sample.jsonl`, SHA-256 `197f9b07028ceb6daf4be7dde66c1642828535483dec4995c30347e1b6737910`. 원문 없이 `text_sha256`만 담는다. `.gitattributes`의 `backend/fixtures/phase2-reaction/** -text` 규칙으로 줄바꿈 변환을 막아 윈도우 체크아웃에서도 해시가 유지된다.
- 판정 결과는 새 파일로 저장하고 raw와 봉인 표본은 수정하지 않는다. 판정을 시작하면 이 항목의 사용 이력과 노출 범위를 갱신한다.

### 알려진 계보 요약

- A: historical DB → 282 export(JSON/CSV) → 74 fixture / 117 recheck / Gold90·Set4·Gold120·Holdout60·PassA·PassB·hybrid. 이 계보의 독립 댓글은 282.
- B: 동일 원본 400댓글 → sentiment/topic labels / Reaction open discovery. B-V 영상 자산은 별도 축.
- C: repo 밖 raw 300 → Phase1 50 + reserve 250 → 각 comments/manifest. 전체 이미 사용.
- D: 별도 댓글 400 → sentiment/topic labels/report. C와 댓글·영상 overlap 0. raw 위치 확인 필요.
- E: 영상 DB 300과 관련 content/discovery 자산. 상세 연결은 확인 필요; C/D 댓글로 연결하지 않음.
- F: historical Carden DB/batches → 400 sentiment/topic labels/report. 현재 raw source 미복구.
- I: Phase 2 raw 200 → 원문 없는 봉인 표본 200 + manifest. 기존 A–F와 채널·댓글 모두 겹치지 않음.
- G/H: source에 연결되는 파생본/보존본. source 미확정 시 확인 필요.

## 4. Blind 사용 규칙

Reaction fresh blind 판정에서는 다음을 각각 확인하고 기록한다.

1. comment_id가 기존 Reaction validation/development와 겹치는가?
2. 같은 영상인가?
3. 댓글 내용이 Reaction taxonomy 설계 과정에서 이미 노출됐는가?
4. Reaction 정답/판정이 이미 존재하는가?
5. sentiment/topic 같은 다른 목적의 라벨만 존재하는가?

다른 목적의 라벨이 있다는 이유만으로 자동 Reaction contamination으로 판정하지 않는다. 반대로 comment_id가 달라도 taxonomy 설계 과정에서 내용이 사용됐다면 fresh라고 단정하지 않는다. ID/영상 비중복과 설계 목적의 내용 노출을 별도로 확인한다. 인간 gold validation 미수행과 인간 원문 미노출도 구분한다. 확인되지 않은 데이터에 fresh=YES를 부여하지 않는다.

## 5. 현재 Phase 2 입력 자격 요약

| 자산 | 현재 판정 | 근거 및 남은 조건 |
|---|---|---|
| 14F 282 | fresh 제외 | 과거 Reaction/comment-pilot 노출 |
| Woni 400 | fresh 제외 | Reaction open discovery 및 taxonomy/vNext 설계 사용 |
| 침착맨 Reaction Phase 1 300 | fresh 제외 | 300 전체 Phase 1/vNext 검토 사용 |
| 침착맨 sentiment/topic 400 | Phase 2 채널 제외 | Phase1과 comment/video overlap=0 및 sentiment/topic 사용 이력은 유지; 댓글 단위 fresh 여부 확인 필요와 별개로 침착맨 전체 제외 |
| Carden 400 | 조건부, source check needed | Reaction 사용 증거 현재 미확인; raw DB는 2026-09-17 저장소에 추가됨; 사용/노출 확인 필요 |

현재 Phase 2는 taxonomy 설계에 사용하지 않은 새로운 채널 2개 × 100댓글 = 200댓글을 기본 설계로 한다. 14F, Woni / 안원잘부, 침착맨은 댓글 ID 비중복 여부와 무관하게 채널 단위로 제외한다. Carden은 raw 복구 및 provenance/사용 이력 확인이 필요한 조건부 자산이며 선정 확정이 아니다. 기존 데이터의 충분성이나 추가 수집 필요성을 이 장부에서 단정하지 않는다. 기준 정본은 [Phase 1 checkpoint의 Phase 2 운영 원칙](reaction-phase1-checkpoint.md)이다.

2026-09-17 실제 수집분은 I항목(슈카월드, MBCNEWS 200댓글)이다. 이 수집에서는 사람 지시에 따라 Carden도 제외했다. 위 표의 Carden 조건부 판정은 과거 자산 400건에 대한 것으로, 이번 수집과 별개로 유지한다.

## 6. 확인 필요 항목과 갱신 규칙

남은 확인 항목:

1. A의 raw DB 현재 보존 위치 및 historical Reaction 개별 산출물의 canonical 경로.
2. A/B/C/D/F의 인간 원문 열람 범위와 목적별 노출 기록 중 확정되지 않은 부분.
3. B의 raw 별도 보존 위치; B-V의 실제 규모, provenance 및 사용 이력.
4. D의 원문 입력/raw 위치, Reaction taxonomy/Matrix 사용·노출 이력 및 Reaction 판정 존재 여부. C/D overlap은 이미 0으로 확정되어 미확정 항목으로 되돌리지 않음.
5. E의 관련 content/discovery 파일 전체 경로, 영상 DB와의 세부 계보 및 사용 이력.
6. F의 batch 파일 보존 여부(DB raw는 2026-09-17 복구); Reaction 설계/판정 사용 이력; 표본 구성.
7. G/H 개별 산출물·복사본의 source 연결, 보존 위치 및 사용/노출 이력.
8. 자산별 수집 방법·표본 추출 방법 등 이번 확정 사실에 포함되지 않은 세부 provenance.

새 수집 시 source dataset 항목을 만들고 규모의 단위, raw 및 backup 위치를 기록한다. 실험에 사용하면 목적, 파생 경로, 인간/모델 노출 및 blind reserve 사용 상태를 갱신한다. 파생본은 source ID에 연결한다. repo 밖 또는 gitignored raw도 실제 보존 위치를 기록한다. 미확정 정보는 확인 필요로 유지하며 새로운 증거와 확정 사실이 충돌하면 임의로 선택하지 않고 확인을 요청한다.

## 7. 작업공간/저장 위치

아래 작업공간은 데이터 장부의 관리 범위이며 자동 정리·삭제 대상이 아니다. 이번 문서 추가 대상은 1번 저장소의 `docs/data-ledger.md` 하나다. 2–6번의 설명은 제공된 기존 audit 사실이며 이번에 branch/파일 내용을 재검증했다고 주장하지 않는다.

### 1. 현재 주 작업/통합 workspace

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/yt-trend-integration`

- remote: `https://github.com/bbamindol-dev/yt-trend.git`
- branch: `integration/feature-discovery-observable`
- 이번 확인 HEAD: `12248c5287e291f094df27bd560a0886836ace38`
- 작성 전 working tree 변경 없음. checkout/reset하지 않음.

### 2. 기존 Feature Discovery workspace

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/yt-trend`

- same remote: `bbamindol-dev/yt-trend`.
- observed branch during audit: `feat/feature-discovery-experiment`.
- observed HEAD during audit: `72637ac0666236ca6f5f707c6704add2402cebf3`.
- local ignored DB인 `14f-recent300.db`, `chim.db` 등이 존재.
- untracked `stage2_evidence` 파일 보유.
- 절대 자동 clean/reset 대상이 아님.

### 3. historical Reaction workspace

`C:/Users/EZ/OneDrive/바탕 화면/project/yt-trend/yt-trend`

- same remote: `bbamindol-dev/yt-trend`.
- historical audit branch: `feat/offline-comment-labeling`.
- historical Reaction experiment outputs 다수 보존.
- 특히 14F Reaction gold/holdout/pass/hybrid lineage 보존.

### 4. 별도/임시 Git workspace

`C:/Users/EZ/OneDrive/Documents/ChatGPT/yt_trend`

- audit-pytest 계열 테스트 산출물이 대부분.
- 실제 YouTube 데이터 자산으로 자동 계산하지 않음.
- untracked 파일을 임의 삭제하지 않음.

### 5. repo 밖 outputs

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/outputs`

- Git repo 밖에 존재하지만 장부의 관리 범위에 포함.
- `raw-comment-pilot-seed42`, `reaction-matrix-phase1`, feature discovery outputs 등이 존재.
- C의 raw와 Phase 1 분할이 있는 위치. repo 안에 없다는 이유로 유실로 판단하지 않음.

### 6. backups

`C:/Users/EZ/Documents/Codex/2026-09-10/github-repository-branch-repository-x20/backups`

- `feature-discovery-pre-integration-20260914T041808Z` 등의 보존 영역.
- 독립 데이터로 중복 계산 금지. 자동 clean/reset/삭제 대상이 아님.
