-- 프로토타입 스키마.
-- 아키텍처 4장의 부분집합이다. 수집과 규칙 필터를 돌리는 데 필요한 것만
-- 넣었고, 열 이름과 키는 4장과 같게 두어 나중에 확장만 하면 되게 했다.
--
-- 아직 없는 것: video_taxonomies, video_type_labels, comment_labels,
-- video_metrics, type_metrics, reports. Claude 단계가 붙을 때 추가한다.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS channels (
    channel_id        TEXT PRIMARY KEY,
    input_url         TEXT NOT NULL,
    handle            TEXT,
    title             TEXT NOT NULL,
    uploads_playlist  TEXT NOT NULL,
    subscriber_count  INTEGER,
    first_analyzed_at TEXT NOT NULL,
    last_analyzed_at  TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id           TEXT PRIMARY KEY,
    channel_id         TEXT NOT NULL REFERENCES channels(channel_id),
    title              TEXT NOT NULL,
    description        TEXT,
    tags_json          TEXT,
    duration_sec       INTEGER NOT NULL,
    published_at       TEXT NOT NULL,
    thumbnail_url      TEXT,
    is_live            INTEGER NOT NULL DEFAULT 0,
    live_evidence      TEXT,          -- 라이브 판정 근거. 0단계 확인용으로 남긴다
    comments_disabled  INTEGER NOT NULL DEFAULT 0,
    length_axis        TEXT,
    first_seen_at      TEXT NOT NULL,
    -- 커서 두 개. 하나만 두면 상한에 잘린 구간을 영원히 못 받는다
    comments_newest_at TEXT,
    comments_oldest_at TEXT,
    comments_complete  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id, published_at);

CREATE TABLE IF NOT EXISTS video_stats_snapshots (
    snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL REFERENCES videos(video_id),
    run_id        TEXT NOT NULL,          -- 프로토타입에서는 job_id 대신 실행 id
    captured_at   TEXT NOT NULL,
    view_count    INTEGER,
    like_count    INTEGER,
    comment_count INTEGER,
    UNIQUE (video_id, run_id)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id        TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos(video_id),
    author_channel_id TEXT,
    author_name       TEXT,
    text              TEXT NOT NULL,      -- 원문. 절대 수정하지 않는다
    published_at      TEXT NOT NULL,
    like_count        INTEGER NOT NULL DEFAULT 0,
    fetched_at        TEXT NOT NULL,
    -- 아래는 분석 포함 여부. 원문 보존(H3)과 분리한다 — 제외는 삭제가 아니라 표시다.
    -- 필드·규칙: docs/design/comment-eligibility.md, 로직: pipeline/eligibility.py
    parent_id              TEXT,       -- 답글이면 부모 댓글 id. 최상위 댓글은 NULL
    author_is_channel_owner INTEGER,   -- 작성자 = 영상 채널이면 1. 모르면 NULL
    analysis_eligible      INTEGER NOT NULL DEFAULT 1,
    exclusion_reason       TEXT,       -- NULL | own_channel | misplaced_data | spam_confirmed
    exclusion_source       TEXT,       -- collect | migration | comment_screens:<버전>/<모델>
    timestamps_json        TEXT NOT NULL DEFAULT '[]'  -- 원문에 적힌 것만 [{"text":"32:19","seconds":1939}]
);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id, published_at);

-- 4단계 결과. PK가 (대상, 프롬프트 버전, 모델)인 것은 아키텍처 4.2와 같다.
-- 규칙만으로 정한 행은 model='rule'.
--
-- 같은 댓글에 규칙 행과 모델 행(model='claude-…', prompt_version='screen-v1')이
-- 나란히 앉는다. 모델 행이 규칙 행을 덮어쓰지 않는 것이 설계다 — 덮어쓰면
-- "규칙은 통과시켰는데 모델이 버렸다"는 사실이 사라진다. 그 차이를 세는 것이
-- 4단계에 Claude 를 붙인 이유다.
CREATE TABLE IF NOT EXISTS comment_screens (
    comment_id      TEXT NOT NULL REFERENCES comments(comment_id),
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    rule_flags_json TEXT,          -- 규칙이 붙인 표시 ['url','repeat']. 모델 행은 NULL
    verdict         TEXT NOT NULL,
    -- 모델이 왜 버렸는지 한 줄. 규칙 행은 NULL 이다 — 규칙은 이유를 문장이
    -- 아니라 표시(rule_flags_json)로 남긴다. 문장을 그 열에 넣으면 리스트를
    -- 기대하는 쪽이 조용히 틀린다
    reason          TEXT,
    screened_at     TEXT NOT NULL,
    PRIMARY KEY (comment_id, prompt_version, model)
);

-- 2단계 결과. 항상 전체 재계산하므로 실행(run_id)마다 새로 쌓는다.
-- view_multiple_basis 는 분모를 어떻게 잡았는지, 못 잡았으면 왜인지를 적는다.
-- 분모 정의가 아직 미결이라(결정 문서 3장) 근거를 값과 함께 남겨야
-- 리포트가 "왜 비었는지"를 말할 수 있다.
CREATE TABLE IF NOT EXISTS video_metrics (
    video_id            TEXT NOT NULL REFERENCES videos(video_id),
    run_id              TEXT NOT NULL,
    length_axis         TEXT,
    view_count          INTEGER,
    like_rate           REAL,          -- 좋아요 비공개면 NULL. 0 이 아니다
    comment_rate        REAL,
    views_per_day       REAL,
    view_multiple       REAL,          -- 비교군이 모자라면 NULL
    view_multiple_basis TEXT,
    -- 댓글율 배수. 비교군 잡는 법은 view_multiple 과 똑같다.
    -- "댓글이 많다"까지만 말한다 — 그 댓글이 호응이냐 논쟁이냐는
    -- comment_engagement 가 5단계 라벨을 보고 가른다
    comment_rate_multiple       REAL,
    comment_rate_multiple_basis TEXT,
    computed_at         TEXT NOT NULL,
    PRIMARY KEY (video_id, run_id)
);

-- 3단계 결과 — 영상 유형 체계와 라벨.
-- 체계는 채널마다 다르다. 종합 채널은 주제로 갈리고 단일 주제 채널은
-- 다른 축이 필요하다. 그래서 채널별로 제안받고 버전을 붙인다.
CREATE TABLE IF NOT EXISTS video_taxonomies (
    taxonomy_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id     TEXT NOT NULL REFERENCES channels(channel_id),
    -- 축이 둘이다. topic 은 판단(LLM)이고 segment 는 사실(채널 재생목록)이다.
    -- 채널마다 축별로 하나씩 활성 체계를 둔다.
    axis           TEXT NOT NULL DEFAULT 'topic',   -- topic | segment
    version        INTEGER NOT NULL,
    source         TEXT NOT NULL,          -- claude | claude-code-offline | user
    prompt_version TEXT,
    types_json     TEXT NOT NULL,          -- {code: name}
    created_at     TEXT NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1,
    -- 체계의 사람이 부르는 이름. prompt_version 과 다르다 — 저건 이 체계를
    -- 만든 프롬프트의 버전이다. 둘을 한 칸에 섞었더니 원이 채널 라벨 107건이
    -- prompt_version='woni-topics-v1' 로 쌓여 대조기가 재현 불가로 잡았다.
    label          TEXT NOT NULL DEFAULT '',
    UNIQUE (channel_id, version)
);

CREATE TABLE IF NOT EXISTS video_type_labels (
    video_id       TEXT NOT NULL REFERENCES videos(video_id),
    taxonomy_id    INTEGER NOT NULL REFERENCES video_taxonomies(taxonomy_id),
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    type_code      TEXT NOT NULL,
    confidence     REAL,
    rationale      TEXT,
    labeled_at     TEXT NOT NULL,
    PRIMARY KEY (video_id, taxonomy_id, prompt_version, model)
);

-- 유형별 성과. length_axis 로 세 판을 만든다 — 'shorts' / 'longform' / 'all'.
--
-- 세 판이 필요한 이유가 데이터로 확인됐다. 14F 에서 역사·인문은 쇼츠 조회
-- 배수 0.59(최하위)인데 롱폼은 1.61(1위)다. 합쳐서 나온 0.88 은 양쪽 어느
-- 쪽도 설명하지 못하는 숫자였다. 그래도 합침을 남기는 것은 채널 전체를
-- 한눈에 볼 자리가 필요해서다 — 대신 리포트가 가려진다는 사실을 함께 적는다.
--
-- 합침을 NULL 이 아니라 'all' 로 두는 이유: SQLite 는 PK 열의 NULL 을 서로
-- 다른 값으로 취급해 중복을 막지 못한다. 아키텍처 4.3 은 NULL 로 적었지만
-- 그대로 두면 합침 행이 ON CONFLICT 로 갱신되지 않고 실행마다 쌓인다.
CREATE TABLE IF NOT EXISTS type_metrics (
    channel_id            TEXT NOT NULL REFERENCES channels(channel_id),
    run_id                TEXT NOT NULL,
    taxonomy_id           INTEGER NOT NULL,
    type_code             TEXT NOT NULL,
    length_axis           TEXT NOT NULL,  -- shorts | longform | all
    video_count           INTEGER NOT NULL,
    med_view_count        REAL,
    med_like_rate         REAL,
    med_comment_rate      REAL,
    med_view_multiple     REAL,
    med_comment_rate_multiple REAL,
    computed_at           TEXT NOT NULL,
    PRIMARY KEY (channel_id, run_id, taxonomy_id, type_code, length_axis)
);

-- 5단계 결과. model='claude-code-offline' 이면 API가 아니라 Claude Code가 판정한 것.
CREATE TABLE IF NOT EXISTS comment_labels (
    comment_id           TEXT NOT NULL REFERENCES comments(comment_id),
    prompt_version       TEXT NOT NULL,
    model                TEXT NOT NULL,
    sentiment            TEXT NOT NULL,
    sentiment_confidence REAL,
    is_sarcasm_suspect   INTEGER NOT NULL DEFAULT 0,
    topics_json          TEXT NOT NULL,
    labeled_at           TEXT NOT NULL,
    PRIMARY KEY (comment_id, prompt_version, model)
);
CREATE INDEX IF NOT EXISTS idx_comment_labels_version
    ON comment_labels(prompt_version, model);

-- 6단계 결과. 5단계 라벨(comment_labels)을 영상 단위로 접은 것.
-- 댓글이 많다는 사실만으로는 호응인지 논쟁인지 알 수 없다. approval 이
-- 어느 쪽으로 기울었는지, contention 이 갈렸는지를 나눠서 말한다.
-- PK 에 프롬프트 버전과 모델이 들어가는 것은 comment_labels 와 같다 —
-- 라벨이 바뀌면 여기서 나온 값도 다른 값이다.
-- 표본이 모자라면 값 대신 basis 에 이유를 남긴다 (view_multiple 과 같은 규칙).
CREATE TABLE IF NOT EXISTS comment_engagement (
    video_id       TEXT NOT NULL REFERENCES videos(video_id),
    run_id         TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    positive       INTEGER NOT NULL DEFAULT 0,
    negative       INTEGER NOT NULL DEFAULT 0,
    neutral        INTEGER NOT NULL DEFAULT 0,
    approval       REAL,          -- 긍정 ÷ (긍정+부정). neutral 은 분모에서 뺀다
    contention     REAL,          -- 2·min(긍정,부정) ÷ (긍정+부정). 0 쏠림 ~ 1 반반
    labeled_ratio  REAL,          -- 라벨된 댓글 ÷ 그 영상의 분석 대상 댓글 (analysis_eligible=1)
    basis          TEXT NOT NULL,
    computed_at    TEXT NOT NULL,
    PRIMARY KEY (video_id, run_id, prompt_version, model)
);

CREATE TABLE IF NOT EXISTS quota_ledger (
    day_pt     TEXT PRIMARY KEY,
    units_used INTEGER NOT NULL DEFAULT 0
);

-- 6단계 결과 ①. 5단계 라벨을 영상 단위로 접은 것.
-- comment_engagement 와 나란히 서지만 묻는 질문이 다르다:
--   comment_engagement.approval  긍정 ÷ (긍정+부정)   — 편을 든 사람 중 몇이 찬성인가
--   video_comment_metrics.positive_ratio  긍정 ÷ 라벨 전체 — 댓글 중 칭찬이 얼마나 되나
-- 같은 영상에서 0.59 와 0.26 이 나온다. 둘 다 맞고, 리포트는 이름을 붙여 구분해야 한다.
CREATE TABLE IF NOT EXISTS video_comment_metrics (
    video_id            TEXT NOT NULL REFERENCES videos(video_id),
    run_id              TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    model               TEXT NOT NULL,
    valid_comment_count INTEGER NOT NULL DEFAULT 0,
    positive            INTEGER NOT NULL DEFAULT 0,
    negative            INTEGER NOT NULL DEFAULT 0,
    neutral             INTEGER NOT NULL DEFAULT 0,
    positive_ratio      REAL,          -- 표본이 모자라면 NULL, 이유는 basis 에
    negative_ratio      REAL,
    neutral_ratio       REAL,
    topic_counts_json   TEXT NOT NULL, -- {"T1": 121, ...}
    top_positive_json   TEXT NOT NULL, -- 대표 댓글 3건. 반어 의심은 뺀다
    top_negative_json   TEXT NOT NULL,
    basis               TEXT NOT NULL,
    computed_at         TEXT NOT NULL,
    PRIMARY KEY (video_id, run_id, prompt_version, model)
);

-- 6단계 결과 ②. 유형 × 길이 축(shorts|longform|all)별 댓글 집계.
-- 성과 쪽 type_metrics 와 같은 키 모양이라 리포트가 둘을 나란히 붙일 수 있다.
CREATE TABLE IF NOT EXISTS type_comment_metrics (
    channel_id          TEXT NOT NULL REFERENCES channels(channel_id),
    run_id              TEXT NOT NULL,
    taxonomy_id         INTEGER NOT NULL REFERENCES video_taxonomies(taxonomy_id),
    type_code           TEXT NOT NULL,
    length_axis         TEXT NOT NULL,
    labeled_video_count INTEGER NOT NULL DEFAULT 0,
    valid_comment_count INTEGER NOT NULL DEFAULT 0,
    positive_ratio      REAL,
    negative_ratio      REAL,
    top_positive_topics_json TEXT NOT NULL,
    top_negative_topics_json TEXT NOT NULL,
    basis               TEXT NOT NULL,
    computed_at         TEXT NOT NULL,
    PRIMARY KEY (channel_id, run_id, taxonomy_id, type_code, length_axis)
);

-- 6단계 결과 ③. 한 판(길이 축 하나)의 리포트.
-- conclusion_source 가 'draft' 면 Claude 가 다듬은 문장이 수치를 바꿔서 버려진
-- 것이거나 애초에 호출하지 않은 것이다. 어느 쪽이든 초안이 나갔다는 뜻이고,
-- 그 사실이 기록되지 않으면 나중에 "이 문장은 누가 썼나"를 알 수 없다.
CREATE TABLE IF NOT EXISTS reports (
    channel_id        TEXT NOT NULL REFERENCES channels(channel_id),
    run_id            TEXT NOT NULL,
    length_axis       TEXT NOT NULL,
    taxonomy_id       INTEGER NOT NULL,
    axis              TEXT NOT NULL,   -- topic | segment. 커버리지가 정한다
    axis_reason       TEXT NOT NULL,   -- 왜 그 축으로 읽는지
    prompt_version_set_json TEXT NOT NULL,
    masked_types_json TEXT NOT NULL,   -- 합침이 가리고 있는 유형들
    conclusion_draft  TEXT NOT NULL,
    conclusion_text   TEXT,
    conclusion_source TEXT NOT NULL,   -- draft | claude
    recent_vs_prior_json TEXT NOT NULL,
    completeness      TEXT NOT NULL,   -- full | performance_only | empty
    built_at          TEXT NOT NULL,
    PRIMARY KEY (channel_id, run_id, length_axis)
);

-- 규칙이 원문에서 **뽑아낸 사실**. 해석이 아니라 추출이다.
--
-- comment_screens·comment_labels 와 나란히 서지만 키가 다르다. 저 둘은
-- (프롬프트 버전, 모델) 로 키를 잡는 해석 표라, 규칙을 v2 로 올리면 같은
-- 댓글이 새 행으로 다시 쌓인다. 그게 판정에는 맞다 — 판정은 버전마다 달라질
-- 수 있으니까. 하지만 "이 댓글에 11:52 가 있다"는 규칙 버전이 바뀌어도 같은
-- 사실이다. 저 표에 넣으면 같은 값이 버전마다 복제된다.
--
-- 무엇을 여기 넣는가: **원문만 보고 세거나 뽑을 수 있는 것.** 모델이 없으므로
-- 재현이 100% 다.
--
-- 무엇을 넣지 않는가: 임계값이 들어간 판정. 「저정보 댓글」 같은 플래그는
-- 여기 두지 않고 char_count·emoji_ratio 라는 **측정값**만 둔다. 몇 글자
-- 아래가 저정보인지는 바뀌지만 글자 수는 안 바뀐다. 플래그로 박아두면
-- 임계값을 고칠 때마다 전부 다시 돌려야 한다 — 이 저장소가 view_multiple 에
-- 값 대신 basis 를 남기는 것과 같은 이유다.
--
-- 「정정·반박 후보」처럼 맥락을 읽어야 아는 것도 여기가 아니다. 그건
-- comment_labels 쪽이고, ideas.md 의 A-002(Reaction taxonomy)가 이미 묻고
-- 있는 질문이라 답이 정해지기 전에 세 번째 집을 짓지 않는다.
CREATE TABLE IF NOT EXISTS comment_features (
    comment_id        TEXT NOT NULL REFERENCES comments(comment_id),
    extractor_version TEXT NOT NULL,   -- 모델 칸이 없다. 규칙이라 재현 100%
    char_count        INTEGER,         -- 자수. 저정보 판정의 재료지 판정이 아니다
    emoji_ratio       REAL,            -- 이모지 문자 ÷ 전체 문자 (0~1)
    url_count         INTEGER,
    timestamps_json   TEXT NOT NULL DEFAULT '[]',  -- 초 단위 [705, 1520]
    mentions_json     TEXT NOT NULL DEFAULT '[]',  -- @언급 대상
    extracted_at      TEXT NOT NULL,
    PRIMARY KEY (comment_id, extractor_version)
);
CREATE INDEX IF NOT EXISTS idx_comment_features_ver
    ON comment_features(extractor_version);
