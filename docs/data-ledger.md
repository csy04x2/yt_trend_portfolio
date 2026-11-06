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
| I. Reaction Phase 2 표본 | 슈카월드, MBCNEWS | 200 top-level comments / 4영상 / 50건씩 | 댓글 raw·봉인 표본 | 있음 | 수집 PC(`C:/Users/EZ/Desktop/yt-trend`)의 gitignored `backend/data/phase2-reaction/2026-09-17/raw_collection.json`; 판정 담당자에게 파일로 전달한 사본 | `backend/fixtures/phase2-reaction/sealed_sample.jsonl`, `manifest.json`(원문 없음); `docs/reports/phase2-reaction-sampling-2026-09-17.md` | Reaction Phase 2 AI coding 및 review audit; R9 행동 유발 → 행동 지향 구조 수정 근거 | 수집 과정에서 사람·모델 원문 열람 없음; 판정용 원문 전달은 2026-09-17; 이후 AI coding·review audit에 노출 | NO | used | 봉인 표본·raw 수정 금지; AI coding 결과 파일은 저장소에 없음(보관 위치 확인 필요); raw는 GitHub에 올리지 않음 |

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

`backend/fixtures/labeled/video-types_woni_107.json`은 별도 content/video 자산 B-V다. labels 107개인 제목 기반 영상 type 자료이며 상세 작성/검증 provenance는 확인 필요하다. 댓글 400과 합산하지 않는다.

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
- Phase 2 AI coding 결과 파일은 저장소에 추가하지 않았다. 보관 위치는 확인 필요다. raw와 봉인 표본은 수정하지 않았다.
- 최종 사용 이력: Reaction Phase 2 AI coding 및 review audit에 사용했고, R9 행동 유발 → 행동 지향 구조 수정의 근거가 되었다. review audit은 APPLICATION_ERROR 5 / DEFINITION_BOUNDARY 6 / STRUCTURE_CANDIDATE 18, 제3자·기관·대중 대상 행동 요구·촉구 중첩 집계는 19건이다.
- 위 200개는 taxonomy 구조 수정에 사용되었으므로 fresh-blind validation eligibility = NO이며, 수정된 vNext의 독립 성능 증거로 재사용하지 않는다. 상태: Phase 2 completed / Reaction track CLOSED.

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

## 8. Human Discovery / validation 보존 감사 — 2026-09-17

감사 시작 HEAD: c76f94f (integration/feature-discovery-observable), working tree 변경 없음. Phase 2 sealed sample은 감사 대상에서 제외했다. 인간 판정/실험 결과의 값은 수정·병합·재계산하지 않았다.

### 재발견 및 보존 상태

침착맨 Human Discovery v3 및 Dev90/guest 검증 원본을 사용자 PC 다운로드 폴더에서 2026-09-17 재발견했다. 사용자 제공 provenance와 파일 구조를 대조했다. 네 저장소의 현재 refs에 도달 가능한 Git blob에서 다운로드 4종과 동일 SHA-256을 찾지 못했다. 삭제된 refs나 외부 저장소까지 확인한 결과는 아니다.

기존 discovery-chim-claude-20260914는 AI/regex 실험이므로 인간 원본을 섞지 않았다. backend/fixtures/labeled/discovery-chim-human-20260917/은 이번 보존일 기준 디렉터리이며 원 실험일을 추정한 이름이 아니다. COPY 후 원본과 크기/SHA-256/바이트 일치를 확인했다. **아직 untracked이며 git add/commit/push 하지 않았다. Git 보존 완료는 아니다.**

| 다운로드 원본 절대 경로 | integration COPY 절대 경로 | bytes | SHA-256 | 구조 | 상태 |
|---|---|---:|---|---|---|
| `C:\Users\EZ\Downloads\chim-discovery-human-review-v3-backup(1).json` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-human-20260917\chim-discovery-human-review-v3.json` | 10576 | `6f868160c093423c8a84146a3aefc30af835e94cfca5abaccc2e52ba19242b0d` | 22 features; checks 86영상/181 entries; notes 4건 | A; COPY 완료 / untracked |
| `C:\Users\EZ\Downloads\chim-dev90-video-verification-pilot.json` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-human-20260917\chim-dev90-video-verification-pilot.json` | 5533 | `bbf51e949d6e8799de867da0df8019b707dd71bccb4157e47a740bc171b91973` | 45영상 labels/notes; nonempty notes 33건 | A; COPY 완료 / untracked |
| `C:\Users\EZ\Downloads\chim-dev90-guest-final-human.json` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-human-20260917\chim-dev90-guest-final-human.json` | 9299 | `b44118d12793be890d9716816ee3588acb6f565486531a2f7486bacc0a210eec` | existing pilot 8 + new_reviews 82; new_reviews의 labels 비어 있지 않은 항목 57; 완료율 추정 안 함 | A; COPY 완료 / untracked |
| `C:\Users\EZ\Downloads\chim-guest-human-blind-audit-v0.1.json` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-human-20260917\chim-guest-human-blind-audit-v0.1.json` | 946 | `b3a07eef8649a33f2da5125dfc421de9d6a7f69d99f32e52a65574a7414946a8` | labels 12영상; note 필드는 있으나 빈 값 | A; COPY 완료 / untracked |

Human v3에는 22 features, checks의 영상 키 86개/저장 entry 181개, human notes 4건이 있다. checks 배열 entry 수를 검토 완료 수나 0/1 총수로 해석하지 않는다. Dev90 pilot은 45영상/비어 있지 않은 notes 33건이다. guest final은 existing_pilot_guest 8 + new_reviews 82 영상 키를 포함하지만 new_reviews 중 labels가 비어 있지 않은 항목은 57개다. 파일명 final을 전체 판정 완료로 확대하지 않으며 빈 항목을 채우지 않는다. blind audit은 12영상이며 note는 빈 값이다.

chim-discovery-human-review-v3-backup.json과 (1) 사본은 동일 SHA다. 요구된 다른 세 파일의 (1)/(2) 접미사 이름은 발견되지 않았으나 접미사 없는 파일이 구조상 대응한다. 원래 다운로드 이력까지 추정하지 않는다.

### split 및 관련 자료 연결

legacy backend/feature_discovery/outputs/chim-recent300-seed42/split.csv에서 Human v3 checks 86개는 모두 Discovery, pilot 45개·guest final 90개·blind audit 12개는 모두 Development에 속한다. 반면 integration의 Claude 실험 split에서는 Human checks 85개가 Discovery/1개가 Development이며 guest final 90개 중 Development 대응은 89개다. 두 실험 split을 동일시하거나 인간 판정을 기존 Claude registry에 자동 결합하지 않는다. Human sheet ID의 hash 표기와 현 legacy split 파일 SHA의 정확한 생성 이력은 UNKNOWN이다.

chim-content.json, chim-evidence.json, Claude registry 및 title-regex labels는 아래 표에 별도 분류했다. guest_present/guest_conversation은 인간 Dev90 JSON의 필드로 존재한다. legacy tools/stage2_evidence/queue_human12.json(12항목), queue_20.json(20항목), human12_evidence/collection_summary.json 및 frames/captions 패키지는 검토 입력·수집 자료이며 인간 최종 판정 자체가 아니다.

### 14F 및 Woni 보류/보존 사실

Downloads/14f-human-review-B-backup(1).json은 version=1, sheet=14f-recent300-seed42-human-review-B-v1-c072848ce945de95, features=36, checks=43개 영상 key, notes={}이다. 사용자가 provenance를 직접 확정했다: 친구가 14F 영상 90편 전체를 직접 검토한 Human Discovery 정본이다. checks 43개는 기록된 영상 key 수이며 실제 검토 범위 90편을 뜻하지 않는다. canonical Git path는 `backend/fixtures/labeled/discovery-14f-human-20260917/14f-human-review-B-v1.json`이다. 다운로드 원본과 바이트가 같은 COPY를 이 preservation commit에 포함한다. 업로드명 (1)(1)은 중복 표기이며 원본은 Downloads의 (1) 파일이다. video-types_14F_300.json은 별도 Claude 주제/재생목록 자료다.

Woni woni-reaction-open-discovery-400.json의 comments 400건에 text가 있고 comment-labels_woni_400.json에도 원문 text가 있다. 두 파일은 **B이지만 감사 시작부터 이미 Git tracked**였다. 이번 작업은 새로 add하거나 삭제·untrack·이력 수정하지 않는다. open discovery는 종료된 independent discovery 입력이며 새 blind 표본이 아니다. 경로/해시/사용 이력만 추가 기록한다. video-types_woni_107.json은 기존 tracked 제목 기반 판정으로 인간 작성·검증 provenance는 UNKNOWN이다. Downloads의 Woni correction audit 37행과 comment-level judgments 400행은 과거 사용자+AI Woni 작업의 별도 산출물로 보존한다. 파일명·구조 및 기존 Woni discovery checkpoint의 사용 이력을 근거로 아래 canonical 경로에 원문 그대로 COPY한다. 개별 행의 작성 주체 및 correction의 judgment 반영 여부는 확인 필요하며 자동 병합하지 않는다.

### 파일별 대조표 (COPY 전 원본 기준)

A=작은 인간 판정/실험 재현 근거, B=raw·민감·대용량 로컬 보존, C=재생성 가능한 파생, UNKNOWN=근거 부족. A는 인간 정답 승인이나 taxonomy freeze를 뜻하지 않는다. raw 열은 raw 댓글 원문 포함 여부이며 UNKNOWN을 없음으로 해석하지 않는다. 같은 SHA는 독립 데이터가 아니다. Git tracked는 현재 index 기준, 원본 SHA는 디스크 바이트 기준이다.

| 채널 | filename / 절대 경로 | bytes | SHA-256 | Git tracked / repo·branch | 동일 SHA 다른 위치 | 생성 유형 | raw 댓글 | human notes | 중요도 | 등급 / 근거 |
|---|---|---:|---|---|---|---|---|---|---|---|
| 침착맨 | `C:\Users\EZ\Downloads\chim-discovery-human-review-v3-backup(1).json` | 10576 | `6f868160c093423c8a84146a3aefc30af835e94cfca5abaccc2e52ba19242b0d` | 아니오 / `repo 밖` | `C:\Users\EZ\Downloads\chim-discovery-human-review-v3-backup.json` | human-created | 없음 | 있음 | 높음 | A — 22 features; checks 86영상/181 entries; notes 4건 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-dev90-video-verification-pilot.json` | 5533 | `bbf51e949d6e8799de867da0df8019b707dd71bccb4157e47a740bc171b91973` | 아니오 / `repo 밖` | 조사 범위에서 없음 | human-created | 없음 | 있음 | 높음 | A — 45영상 labels/notes; nonempty notes 33건 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-dev90-guest-final-human.json` | 9299 | `b44118d12793be890d9716816ee3588acb6f565486531a2f7486bacc0a210eec` | 아니오 / `repo 밖` | 조사 범위에서 없음 | human-created | 없음 | 있음 | 높음 | A — existing pilot 8 + new_reviews 82; new_reviews의 labels 비어 있지 않은 항목 57; 완료율 추정 안 함 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-guest-human-blind-audit-v0.1.json` | 946 | `b3a07eef8649a33f2da5125dfc421de9d6a7f69d99f32e52a65574a7414946a8` | 아니오 / `repo 밖` | 조사 범위에서 없음 | human-created | 없음 | 빈 note 필드 | 높음 | A — labels 12영상; note 필드는 있으나 빈 값 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-discovery-human-review-v3-backup.json` | 10576 | `6f868160c093423c8a84146a3aefc30af835e94cfca5abaccc2e52ba19242b0d` | 아니오 / `repo 밖` | `C:\Users\EZ\Downloads\chim-discovery-human-review-v3-backup(1).json` | human-created | 없음 | 있음 | 높음 | A — (1) 파일과 byte-identical; 중복 복사 안 함 |
| 14F | `C:\Users\EZ\Downloads\14f-human-review-B-backup(1).json` | 13000 | `da2cce486da29c0acd5693be7f65ca4eef6a3ab2b044be88dbbf51d13252bd43` | 아니오 / `repo 밖` | 조사 범위에서 없음 | human-created | 없음 | notes={} (0건) | 높음 | A — 사용자 provenance 확정: 친구가 90편 전체 검토한 Human Discovery 정본; features 36; checks 기록 영상 43; notes 0; canonical COPY 보존(아래 표) |
| Woni | `C:\Users\EZ\Downloads\woni-reaction-pass2-unclear-correction-audit.json` | 10947 | `ca7421eb520b038d62026751dc59e50d31cd4fbebc0f1966ab49555cff9c8385` | 아니오 / `repo 밖` | 조사 범위에서 없음 | UNKNOWN | 전용 raw text 필드 없음; 자유기술 인용 여부 UNKNOWN | human 작성 여부 UNKNOWN | 높음 | 과거 사용자+AI Woni 산출물; 역할별 canonical COPY 보존(아래 표); 개별 작성 주체 확인 필요 |
| Woni | `C:\Users\EZ\Downloads\woni-reaction-stage2-comment-level-judgments.json` | 88507 | `4550d66c0db68e093f6336492352a88c1e821f0c49de429c14f35b3ffbe43b2a` | 아니오 / `repo 밖` | 조사 범위에서 없음 | UNKNOWN | 전용 raw text 필드 없음; 자유기술 인용 여부 UNKNOWN | human 작성 여부 UNKNOWN | 높음 | 과거 사용자+AI Woni 산출물; 역할별 canonical COPY 보존(아래 표); 개별 작성 주체 확인 필요 |
| Woni | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\comment-labels_woni_400.json` | 163757 | `3f56c93eec4d7c8b1bf8316dbefbedb3853d51edf3c649503de9eafaecea4046` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\comment-labels_woni_400.json` | derived + raw | 있음 | UNKNOWN | 높음 | B — 400 comments; text 포함; 기존 tracked 유지, 추가 안 함 |
| Woni | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\video-types_woni_107.json` | 9865 | `86854adcda22e446e5b2a9be224c3602eb30e93c6235be460fcd5a0d6968186e` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\video-types_woni_107.json` | derived; 작성 주체 UNKNOWN | 없음 | UNKNOWN | 중간 | UNKNOWN — 제목 기반 라벨; 인간 validation 정본으로 간주하지 않음 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\video-types_14F_300.json` | 74420 | `d0fb33e4923e8fc93baec8bb291fc39390296ad2cc7cc4516f3693b15e7c8cd9` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\video-types_14F_300.json` | AI-created + derived | 없음 | UNKNOWN | 중간 | C — Claude Code 주제 판정 + 재생목록 코너; Human Discovery 아님 |
| Woni | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\comment-labels_woni_400.json` | 163757 | `3f56c93eec4d7c8b1bf8316dbefbedb3853d51edf3c649503de9eafaecea4046` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\comment-labels_woni_400.json` | derived + raw | 있음 | UNKNOWN | 높음 | B — 400 comments; text 포함; 기존 tracked 유지, 추가 안 함 |
| Woni | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\video-types_woni_107.json` | 9865 | `86854adcda22e446e5b2a9be224c3602eb30e93c6235be460fcd5a0d6968186e` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\video-types_woni_107.json` | derived; 작성 주체 UNKNOWN | 없음 | UNKNOWN | 중간 | UNKNOWN — 제목 기반 라벨; 인간 validation 정본으로 간주하지 않음 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\fixtures\labeled\video-types_14F_300.json` | 74420 | `d0fb33e4923e8fc93baec8bb291fc39390296ad2cc7cc4516f3693b15e7c8cd9` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\video-types_14F_300.json` | AI-created + derived | 없음 | UNKNOWN | 중간 | C — Claude Code 주제 판정 + 재생목록 코너; Human Discovery 아님 |
| Woni | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\woni-reaction-open-discovery-400.json` | 68500 | `ca86fdbeaf42b14ccf224d550395170423f91dfd07576c910bdcadfbfc38d15d` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | raw | 있음 | 없음 | 높음 | B — 400 comments; 종료된 independent discovery 입력; 기존 tracked, 이번 add 금지 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-claude-20260914\chim-content.json` | 77835 | `2ee75efb3e75c445ee0f7c91d3888ec635e3de344dc8bd735fd157bbd6bef332` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | A — 300영상 content source, 인간 판정 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-claude-20260914\split.csv` | 15572 | `e0a9afd0079dee43a6750cb1e675380acd57311bb383f91951b7c009c62c0272` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | A — 실험 split 근거, 인간 판정 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-claude-20260914\registry-claude-v0.1.json` | 11002 | `59d911262906c3ed2deb5e9d851e211b3f52cfc3974a3ebec530037ced785f53` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | AI-created | 없음 | UNKNOWN | 중간 | A — Claude candidate registry; 인간 정본 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\backend\fixtures\labeled\discovery-chim-claude-20260914\labels-title-regex-300.json` | 95365 | `9fdbfcd56b473b399dfd8914d705597b63da2cea7ec15eba406ae2f56372ac80` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | C — title-regex placeholder; Human Discovery 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration\docs\prototype\chim-evidence.json` | 1229544 | `f157f706ff5f176446f26d4e0c081c48e6dc60cf0bf84936c4a72d4942321198` | 예 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend-integration @ integration/feature-discovery-observable` | 조사 범위에서 없음 | derived + raw | 있음 | UNKNOWN | 높음 | B — 집계/evidence와 댓글 text; 인간 정본 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\tools\stage2_evidence\queue_human12.json` | 3306 | `f0672556a3714058602b91820b51d83b00f44ccc013db968e23cc8d920c62a47` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | derived | 전용 댓글 text 없음 | UNKNOWN | 중간 | UNKNOWN — human 검토 입력/수집 근거; 최종 human 판정 아님, 정본 미확정 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\tools\stage2_evidence\queue_20.json` | 10729 | `df7328024327065bca8be67faedea4c1b99d03787d52a8a3689569d2a30e19ee` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | derived | 전용 댓글 text 없음 | UNKNOWN | 중간 | UNKNOWN — human 검토 입력/수집 근거; 최종 human 판정 아님, 정본 미확정 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\tools\stage2_evidence\human12_evidence\collection_summary.json` | 292 | `0f7c2f4ee8f045c7ceeb3f98b3c0585a94cb144a7bdb696adafda62c9f5b6071` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | derived | 전용 댓글 text 없음 | UNKNOWN | 중간 | UNKNOWN — human 검토 입력/수집 근거; 최종 human 판정 아님, 정본 미확정 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\tools\stage2_evidence\human12_evidence.zip` | 3722598 | `ea1efc3f53cdd816087dd37c2d548df275411a1ff108f19e425e99d0272f1155` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | raw + derived | UNKNOWN | UNKNOWN | 높음 | B — 영상 frames/captions/evidence 패키지, 로컬 보존 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\data\14f-recent300.db` | 483328 | `d69698b78ca893a17488f4f29b1d6f2c7ffa1d2b92a78e09f71d09e393ac1a30` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | raw | UNKNOWN (DB 미개방) | UNKNOWN | 높음 | B — DB는 인간 Discovery 결과와 별도; Git 추가 금지 |
| 14F | `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend\backend\exports\reaction-human-gold-validation-90.json` | 46090 | `526079180794eeacae9fba5b00298681c006ad5bdd4aa3d88691d93bf6379f1c` | 예 / `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend @ feat/offline-comment-labeling` | 조사 범위에서 없음 | human-created + raw | 있음 | UNKNOWN; 인간 라벨은 있음 | 높음 | B — 과거 Reaction gold/adjudication; Content Feature Human Discovery와 별도 |
| 14F | `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend\backend\exports\reaction-human-gold-validation-set4-30.json` | 13797 | `3e28aea049058f30c2697af1194b2ca731aaf6b22dc5fece7996970b9d6d6c20` | 예 / `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend @ feat/offline-comment-labeling` | 조사 범위에서 없음 | human-created + raw | 있음 | UNKNOWN; 인간 라벨은 있음 | 높음 | B — 과거 Reaction gold/adjudication; Content Feature Human Discovery와 별도 |
| 14F | `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend\backend\exports\reaction-human-adjudication-holdout60-v02.json` | 41499 | `3d81a612ed9d36dfdd468b08bff319ab7d66f64eb4d412d341221d091458d210` | 예 / `C:\Users\EZ\OneDrive\바탕 화면\project\yt-trend\yt-trend @ feat/offline-comment-labeling` | 조사 범위에서 없음 | human-created + raw | 있음 | 있음/판정 근거 | 높음 | B — 과거 Reaction gold/adjudication; Content Feature Human Discovery와 별도 |
| 14F | `C:\Users\EZ\Downloads\14F_Feature_Discovery_Mac_친구용.zip` | 31194 | `6bb99e6acca871bacf64be2e7f5a12b3297eaea82adc4e44cfc5ca623099f882` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 14F | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용 (1).zip` | 32203 | `6925755a8a3dc4e5e92e45fe98fdb00006abcccb844481ba01f0f667ecad6488` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 14F | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용 (2).zip` | 32582 | `cc7fad25752e61b9ca1554f8a50db2ce56cef3681f29e39ee11d4a00d939f336` | 아니오 / `repo 밖` | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용 (3).zip` | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 14F | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용 (3).zip` | 32582 | `cc7fad25752e61b9ca1554f8a50db2ce56cef3681f29e39ee11d4a00d939f336` | 아니오 / `repo 밖` | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용 (2).zip` | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 14F | `C:\Users\EZ\Downloads\14F_Feature_Discovery_친구용.zip` | 31967 | `e2108cbeb7556846b11a99b29f2206442157f80d2d7f57f115fb1e878661ef9d` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-browse-comment-caption-validation-result-v0.1.zip` | 1478 | `44c97c570acf999df31cfd5e94a0cbb95723be32d97f8d8bbea50ae50a33e0b5` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-browse-comment-caption-validation-v0.1.zip` | 3312 | `6752255825f0a718a1475854ebe9665f049c4be0a8056cf03ab960454b150069` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-dev90-12feature-provisional-screen-v0.1.zip` | 12624 | `54c97f4bd6881d25f5e8308b920e9d98bfd8dc28d93d993fa614d0dee645a889` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-dev90-feature-performance-screen-v0.1.zip` | 1489 | `622ec063909345101119df6b7fdbb162823272d682c141f08f59a7809b946bcf` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-stage2-runner-v0.1.zip` | 8572 | `b61ac1a63d393a7070cd56072c2b11eea3eff3d08d21d35fcc4f914ff5b28ea5` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\chim-stage2-runner-v0.2.zip` | 8770 | `2b78fd76562449654e57bfd1aac57db9d4b51b0fa261c56e0d0381d66656b575` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\Chim_Development_Verification_Windows.zip` | 9619 | `4fcbbf43c8fd2401d270cbf219753cef0f31d9676a8c422ace1515d41f36de8c` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\Chim_Development_Verification_Windows_v2.zip` | 10136 | `34f84d3cf3672c694c41f21eacee5ecad20f2d6c959b094b480cc49f7debd37e` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\Chim_Guest_Final_Human.zip` | 15632 | `d3ce03658f10d24c0f9b8efa1c089cf7d6d35f7193ef5e57e7bddfff0a4a40bb` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 침착맨 | `C:\Users\EZ\Downloads\gemini_guest_present_blind_validation_v0.1.zip` | 7227280 | `6e0aad0dc748a06ac5d04561dcdcfc0303bfbf6600e75d3bf0eb0ba036372594` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived/package | UNKNOWN | UNKNOWN | 중간 | UNKNOWN — 배포/검증 도구 또는 evidence 패키지; 인간 최종 JSON으로 간주하지 않음, COPY 보류 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\outputs\14f-recent300-seed42\manifest.json` | 1998 | `fb347f27282b577fc3a73459857e7ceb21a66eb614090bfc53380f1e16cde3f1` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | UNKNOWN — 관련 실험 근거; final human 판정 아님 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\outputs\14f-recent300-seed42\split.csv` | 15572 | `c072848ce945de95d6c7398faff458a40ce7844c2c8d5d35d610e5c71f705dd0` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | UNKNOWN — 관련 실험 근거; final human 판정 아님 |
| 14F | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\outputs\14f-recent300-seed42\human-review-B\validation.json` | 1185 | `f068692483304125606ac632b108d6a3d81d1e983f9a8b966398522b8ba834bd` | 아니오 / `repo 밖` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | UNKNOWN — 관련 실험 근거; final human 판정 아님 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\feature_discovery\outputs\chim-recent300-seed42\split.csv` | 15572 | `d24841188d6674040e3f6280c1e8df1cbd4b10d9cc1c4a6c47dabd0c7a750c5b` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | derived | 없음 | 없음 | 높음 | UNKNOWN — 인간 판정 ID와 연결; sheet hash와 현재 파일 hash의 생성 이력 확인 필요 |
| 침착맨 | `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend\backend\feature_discovery\outputs\guest-extractor-v0.1\run-001\manifest.json` | 2173 | `4655813bb8e7504c15ed23ae7491ad58019d75ac0b43f3b8373ae13667d6dfdc` | 아니오 / `C:\Users\EZ\Documents\Codex\2026-09-10\github-repository-branch-repository-x20\yt-trend @ feat/feature-discovery-experiment` | 조사 범위에서 없음 | derived | 없음 | UNKNOWN | 중간 | UNKNOWN — AI extractor run 근거, 인간 판정 아님 |

조사 범위: integration/legacy/ChatGPT 임시/OneDrive historical 네 저장소, 사용자 Downloads와 OneDrive 바탕 화면 최상위 동일 이름 후보, 직접 참조된 14F outputs. OneDrive Downloads/다운로드 및 사용자 다운로드라는 별도 경로는 발견되지 않았다. 임시 workspace의 freeze-focused-tests-20260915, freeze-regression-tests-20260915, outcome-audit-tests-20260915는 접근 거부로 미조사이며 실제 인간 자산 부재를 단정하지 않는다. 테스트 registry/cache는 C로 분리하고 실제 Human Discovery로 계산하지 않는다. SHA 중복 검색은 해당 범위의 읽기 가능한 파일 기준이며 ZIP 내부 동일 member와 외부 저장소까지 완전 대조했다는 뜻은 아니다.


### 14F / Woni canonical preservation 확정 — 2026-09-17

이 절은 위 COPY 전 대조표의 후속 보존 상태다. Downloads 원본은 유지하고 JSON 내용은 변경하지 않는다. 새 JSON 3개와 이 ledger를 동일 preservation commit으로 Git에 보존한다. 기존 tracked Woni 3개는 복사·재추가·내용 변경하지 않는다.

| 자산 | 역할 / 규모 | canonical Git path | Git 보존 | 기존 사용 이력 / 다른 자산과의 관계 |
|---|---|---|---|---|
| 14F Human Discovery | 친구의 90편 전체 인간 검토 정본; features 36 / checks 기록 영상 43 / notes 0 | `backend/fixtures/labeled/discovery-14f-human-20260917/14f-human-review-B-v1.json` | 이번 commit에 신규 보존 | 사용자 직접 provenance 확정; checks key 수를 검토 범위로 해석하지 않음 |
| Woni open discovery | Reaction open discovery 입력; 2영상 / comments 400 | `backend/fixtures/woni-reaction-open-discovery-400.json` | 기존 tracked 유지 | 종료된 독립 discovery 및 vNext 설계 사용; 기존 comment labels와 같은 400댓글의 별도 표현; fresh blind 아님 |
| Woni comment labels | 기존 comment-level label 자료; comments 400; model=claude-code-offline | `backend/fixtures/labeled/comment-labels_woni_400.json` | 기존 tracked 유지 | sentiment/topics 등 기존 라벨; Reaction stage2 judgments와 역할이 달라 합치지 않음 |
| Woni video types | 영상 Feature/type 자료; labels 107 / types 8 | `backend/fixtures/labeled/video-types_woni_107.json` | 기존 tracked 유지 | 파일 기록상 제목 기반 판정; 상세 작성/인간 검증 이력 확인 필요; 댓글 자산과 별도 |
| Woni correction audit | Pass 2 unclear correction/audit; 37행; comment_id/original_status/decision/corrected_reactions/reason | `backend/fixtures/labeled/discovery-woni-20260917/woni-reaction-pass2-unclear-correction-audit.json` | 이번 commit에 신규 보존 | Downloads 동명 원본의 byte-identical COPY; 종료된 discovery checkpoint의 Pass 2 audit에 대응; judgment와 별도 보존 |
| Woni stage2 judgments | comment-level Reaction judgments; 400행; comment_id/video/reactions/unclear/new_candidate_note | `backend/fixtures/labeled/discovery-woni-20260917/woni-reaction-stage2-comment-level-judgments.json` | 이번 commit에 신규 보존 | Downloads 동명 원본의 byte-identical COPY; 과거 사용자+AI discovery/judgment 산출물; correction 반영 여부는 확인 필요; 기존 comment labels를 대체하지 않음 |

Woni의 종료 및 27개 후보 / Pass 2 audit 사용 이력은 `docs/reports/woni-reaction-discovery-checkpoint.md`를 따른다. 이번 보존은 taxonomy 재해석·새 분석·판정 병합이 아니다. 서로 다른 역할의 파일은 별도 자산이며 행 수를 합쳐 독립 데이터 규모로 계산하지 않는다.
