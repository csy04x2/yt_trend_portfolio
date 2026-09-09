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
    fetched_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id, published_at);

-- 4단계 결과. PK가 (대상, 프롬프트 버전, 모델)인 것은 아키텍처 4.2와 같다.
-- 규칙만으로 정한 행은 model='rule'.
CREATE TABLE IF NOT EXISTS comment_screens (
    comment_id      TEXT NOT NULL REFERENCES comments(comment_id),
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    rule_flags_json TEXT,
    verdict         TEXT NOT NULL,
    screened_at     TEXT NOT NULL,
    PRIMARY KEY (comment_id, prompt_version, model)
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

CREATE TABLE IF NOT EXISTS quota_ledger (
    day_pt     TEXT PRIMARY KEY,
    units_used INTEGER NOT NULL DEFAULT 0
);
