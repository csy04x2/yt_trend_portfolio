"""댓글 분석 포함 여부(analysis_eligible)와 명시적 timestamp 테스트.

근거: docs/reaction-phase1-checkpoint.md H2·H3, 정리: docs/design/comment-eligibility.md

지키려는 것:

1. 제외는 삭제가 아니다. 채널 자신의 댓글·잘못 들어온 데이터도 raw 행으로 남는다.
2. 채널 댓글에 달린 시청자 답글은 부모를 따라 빠지지 않는다.
3. 의심만으로는 빼지 않는다. 규칙이 확정한 promo 만 spam_confirmed 다.
4. timestamp 는 원문에 적힌 것만. 없는 것을 만들지 않는다.
5. 옛 DB 를 열면 알 수 있는 것(own_channel)만 채우고 나머지는 eligible 로 둔다.

댓글 원문은 전부 지어낸 문자열이다.
"""

import pathlib
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import connect  # noqa: E402
from app.pipeline import engagement, label_comments, rules  # noqa: E402
from app.pipeline import eligibility as el  # noqa: E402
from app.pipeline.collect import collect_comments  # noqa: E402
from app.pipeline.observable_collect import collect_sample, ensure_schema  # noqa: E402

CH = "UC_owner"
VIEWER = "UC_viewer"


def _db(path=None):
    path = path or pathlib.Path(tempfile.mkdtemp()) / "t.db"
    conn = connect(path)
    conn.execute("""INSERT INTO channels (channel_id, input_url, title,
                        uploads_playlist, first_analyzed_at)
                    VALUES (?,'u','채널','UU','2026-01-01')""", (CH,))
    for vid in ("v1", "v2"):
        conn.execute("""INSERT INTO videos (video_id, channel_id, title,
                            duration_sec, published_at, length_axis, first_seen_at)
                        VALUES (?,?,'제목',600,'2026-01-01','standard','2026-01-01')""",
                     (vid, CH))
    return conn


def _api_comment(cid, author, text="지어낸 댓글", api_video_id="v1",
                 published="2026-01-02T00:00:00Z"):
    return {"comment_id": cid, "video_id": "v1", "author_channel_id": author,
            "author_name": "이름", "text": text, "published_at": published,
            "like_count": 0, "api_video_id": api_video_id, "parent_id": None}


class FakeYT:
    def __init__(self, pages):
        self.pages = pages

    def iter_comment_pages(self, video_id):
        yield from self.pages


# --------------------------------------------------------------------------
# decide — 순수 함수
# --------------------------------------------------------------------------

def test_decide_own_channel():
    assert el.decide("v1", "v1", CH, CH) == (0, "own_channel", 1)


def test_decide_viewer_is_eligible():
    assert el.decide("v1", "v1", VIEWER, CH) == (1, None, 0)


def test_decide_misplaced_data_wins_over_own_channel():
    assert el.decide("v1", "v9", CH, CH) == (0, "misplaced_data", 1)
    assert el.decide("v1", "v9", VIEWER, CH)[:2] == (0, "misplaced_data")


def test_decide_unknown_is_not_excluded():
    """작성자·채널·보고된 영상을 모르면 추정하지 않는다. owner 도 0 이 아니라 None."""
    assert el.decide("v1", None, None, CH) == (1, None, None)
    assert el.decide("v1", None, VIEWER, None) == (1, None, None)


def test_spam_constants_match_rules():
    assert el.SPAM_CONFIRMED_VERDICTS == (rules.VERDICT_PROMO,)
    assert el.SPAM_CONFIRMED_MODEL == rules.MODEL_RULE


# --------------------------------------------------------------------------
# timestamp — 적힌 것만
# --------------------------------------------------------------------------

def test_timestamps_literal_only():
    got = el.extract_timestamps("처음 0:45 그리고 32:19, 마지막 1:02:03 다시 32:19")
    assert got == [{"text": "0:45", "seconds": 45},
                   {"text": "32:19", "seconds": 1939},
                   {"text": "1:02:03", "seconds": 3723}]


def test_timestamps_none_invented():
    for text in ("타임스탬프 없는 댓글", "3분 20초쯤 장면", "", None,
                 "비율 1:2", "12345", "1:99", "1:75:00", "2026-01-01"):
        assert el.extract_timestamps(text) == [], text


def test_timestamps_not_filtered_by_duration():
    """영상 길이를 모르는 채 원문을 기록한다. 거를지는 읽는 쪽이 정한다."""
    assert el.extract_timestamps("999:59")[0]["seconds"] == 999 * 60 + 59


# --------------------------------------------------------------------------
# 수집 — 1단계 collect_comments
# --------------------------------------------------------------------------

def test_collect_marks_own_channel_and_keeps_raw():
    conn = _db()
    page = [_api_comment("c_own", CH, "채널 공지 12:34"),
            _api_comment("c_view", VIEWER, "시청자 댓글 1:02"),
            _api_comment("c_misp", VIEWER, api_video_id="v2")]
    got = collect_comments(conn, FakeYT([page]), "v1", 100)
    assert got == 3
    rows = {r["comment_id"]: dict(r) for r in conn.execute("SELECT * FROM comments")}
    assert set(rows) == {"c_own", "c_view", "c_misp"}, "제외된 행이 raw 에서 사라졌다"

    own = rows["c_own"]
    assert (own["analysis_eligible"], own["exclusion_reason"],
            own["author_is_channel_owner"], own["exclusion_source"]) == \
        (0, "own_channel", 1, "collect")
    assert own["text"] == "채널 공지 12:34"
    assert own["timestamps_json"] == '[{"text": "12:34", "seconds": 754}]'

    view = rows["c_view"]
    assert (view["analysis_eligible"], view["exclusion_reason"],
            view["author_is_channel_owner"], view["exclusion_source"]) == (1, None, 0, None)

    misp = rows["c_misp"]
    assert (misp["analysis_eligible"], misp["exclusion_reason"]) == (0, "misplaced_data")
    assert misp["video_id"] == "v1" and misp["timestamps_json"] == "[]"


# --------------------------------------------------------------------------
# 수집 — observation 경로 (답글 포함)
# --------------------------------------------------------------------------

def test_reply_to_own_channel_parent_stays_eligible():
    conn = _db()

    class Fake:
        def _get(self, endpoint, **kw):
            if endpoint == "commentThreads":
                return {"items": [{"id": "th", "snippet": {
                    "totalReplyCount": 2,
                    "topLevelComment": {"id": "top", "snippet": {
                        "videoId": "v1", "authorChannelId": {"value": CH},
                        "textOriginal": "고정 댓글"}}}}]}
            return {"items": [
                {"id": "r_view", "snippet": {"videoId": "v1", "parentId": "top",
                                             "authorChannelId": {"value": VIEWER},
                                             "textOriginal": "답글 5:00"}},
                {"id": "r_own", "snippet": {"videoId": "v1", "parentId": "top",
                                            "authorChannelId": {"value": CH},
                                            "textOriginal": "채널 답글"}},
            ]}

    ensure_schema(conn)
    collect_sample(conn, Fake(), "run1", "v1")
    rows = {r["comment_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM observation_comments WHERE run_id='run1'")}
    assert (rows["top"]["analysis_eligible"], rows["top"]["exclusion_reason"]) == \
        (0, "own_channel")
    assert rows["r_view"]["parent_id"] == "top", "부모 맥락 연결이 끊겼다"
    assert (rows["r_view"]["analysis_eligible"], rows["r_view"]["exclusion_reason"]) == \
        (1, None), "시청자 답글이 부모를 따라 빠졌다"
    assert rows["r_view"]["timestamps_json"] == '[{"text": "5:00", "seconds": 300}]'
    assert rows["r_own"]["exclusion_reason"] == "own_channel"


# --------------------------------------------------------------------------
# 스팸 — 확정만
# --------------------------------------------------------------------------

def _seed_screened(conn):
    for cid, author in (("c_promo", VIEWER), ("c_rep", VIEWER), ("c_drop", VIEWER),
                        ("c_own", CH), ("c_flip", VIEWER)):
        conn.execute("""INSERT INTO comments (comment_id, video_id, author_channel_id,
                            text, published_at, fetched_at, analysis_eligible,
                            exclusion_reason, author_is_channel_owner)
                        VALUES (?, 'v1', ?, '지어낸', '2026-01-01', '2026-01-01', ?, ?, ?)""",
                     (cid, author, 0 if author == CH else 1,
                      "own_channel" if author == CH else None, int(author == CH)))

    def screen(cid, pv, model, verdict, at="2026-01-01"):
        conn.execute("""INSERT INTO comment_screens (comment_id, prompt_version, model,
                            verdict, screened_at) VALUES (?,?,?,?,?)""",
                     (cid, pv, model, verdict, at))

    screen("c_promo", "rules-v1", "rule", "promo")
    screen("c_rep", "rules-v1", "rule", "suspect_repeat")
    screen("c_drop", "rules-v1", "rule", "keep")
    screen("c_drop", "screen-v1", "claude-x", "drop")
    screen("c_own", "rules-v1", "rule", "promo")
    screen("c_flip", "rules-v1", "rule", "promo", "2026-01-01")
    screen("c_flip", "rules-v2", "rule", "keep", "2026-02-01")


def test_only_confirmed_rule_promo_is_spam():
    conn = _db()
    _seed_screened(conn)
    n = el.apply_screen_exclusions(conn)
    rows = {r["comment_id"]: dict(r) for r in conn.execute("SELECT * FROM comments")}
    assert n == 1
    assert (rows["c_promo"]["analysis_eligible"], rows["c_promo"]["exclusion_reason"],
            rows["c_promo"]["exclusion_source"]) == \
        (0, "spam_confirmed", "comment_screens:rules-v1/rule")
    assert rows["c_rep"]["analysis_eligible"] == 1, "반복 의심만으로 뺐다"
    assert rows["c_drop"]["analysis_eligible"] == 1, "모델 drop 을 확정 스팸으로 봤다"
    assert rows["c_flip"]["analysis_eligible"] == 1, "새 규칙 판정(keep)을 무시했다"
    assert rows["c_own"]["exclusion_reason"] == "own_channel", "앞선 사유를 덮어썼다"

    # 다시 돌려도 같다
    assert el.apply_screen_exclusions(conn) == 1


# --------------------------------------------------------------------------
# 집계가 표시를 본다
# --------------------------------------------------------------------------

def test_label_pending_and_engagement_skip_excluded():
    conn = _db()
    for cid, author, sentiment in (("a", VIEWER, "positive"), ("b", CH, "positive"),
                                   ("c", VIEWER, "negative")):
        own = int(author == CH)
        conn.execute("""INSERT INTO comments (comment_id, video_id, author_channel_id, text,
                            published_at, fetched_at, analysis_eligible, exclusion_reason)
                        VALUES (?, 'v1', ?, '지어낸', '2026-01-01', '2026-01-01', ?, ?)""",
                     (cid, author, 1 - own, "own_channel" if own else None))
        conn.execute("""INSERT INTO comment_screens (comment_id, prompt_version, model,
                            verdict, screened_at) VALUES (?, 'rules-v1', 'rule', 'keep', 'x')""",
                     (cid,))
    pend = {r["comment_id"] for r in label_comments.pending(conn, "p1", "m1")}
    assert pend == {"a", "c"}, "채널 자신의 댓글이 라벨 대상에 올랐다"

    for cid, s in (("a", "positive"), ("b", "positive"), ("c", "negative")):
        conn.execute("""INSERT INTO comment_labels (comment_id, prompt_version, model,
                            sentiment, topics_json, labeled_at)
                        VALUES (?, 'p1', 'm1', ?, '[]', 'x')""", (cid, s))
    assert engagement.read_label_counts(conn, "p1", "m1") == \
        {"v1": {"positive": 1, "negative": 1}}
    out = {e["video_id"]: e for e in engagement.run(conn, "r1", "p1", "m1")}
    assert out["v1"]["comment_count_collected"] == 2, "분모에 제외 댓글이 들어갔다"
    assert out["v1"]["labeled_ratio"] == 1.0


# --------------------------------------------------------------------------
# 옛 DB
# --------------------------------------------------------------------------

OLD_DDL = """
CREATE TABLE channels (channel_id TEXT PRIMARY KEY, input_url TEXT NOT NULL, handle TEXT,
    title TEXT NOT NULL, uploads_playlist TEXT NOT NULL, subscriber_count INTEGER,
    first_analyzed_at TEXT NOT NULL, last_analyzed_at TEXT);
CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL,
    description TEXT, tags_json TEXT, duration_sec INTEGER NOT NULL, published_at TEXT NOT NULL,
    thumbnail_url TEXT, is_live INTEGER NOT NULL DEFAULT 0, live_evidence TEXT,
    comments_disabled INTEGER NOT NULL DEFAULT 0, length_axis TEXT, first_seen_at TEXT NOT NULL,
    comments_newest_at TEXT, comments_oldest_at TEXT, comments_complete INTEGER NOT NULL DEFAULT 0);
CREATE TABLE comments (comment_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
    author_channel_id TEXT, author_name TEXT, text TEXT NOT NULL, published_at TEXT NOT NULL,
    like_count INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL);
CREATE TABLE comment_screens (comment_id TEXT NOT NULL, prompt_version TEXT NOT NULL,
    model TEXT NOT NULL, rule_flags_json TEXT, verdict TEXT NOT NULL, screened_at TEXT NOT NULL,
    PRIMARY KEY (comment_id, prompt_version, model));
"""


def test_old_schema_db_is_migrated():
    path = pathlib.Path(tempfile.mkdtemp()) / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_DDL)
    raw.execute("INSERT INTO channels VALUES (?,'u',NULL,'채널','UU',NULL,'x',NULL)", (CH,))
    raw.execute("""INSERT INTO videos (video_id, channel_id, title, duration_sec,
                       published_at, first_seen_at) VALUES ('v1', ?, '제목', 60, 'x', 'x')""",
                (CH,))
    for cid, author, text in (("o1", CH, "채널 댓글"), ("o2", VIEWER, "시청자 3:15"),
                              ("o3", None, "작성자 모름"), ("o4", VIEWER, "홍보 문구")):
        raw.execute("INSERT INTO comments VALUES (?, 'v1', ?, '이름', ?, 'x', 0, 'x')",
                    (cid, author, text))
    raw.execute("INSERT INTO comment_screens VALUES ('o4','rules-v1','rule','[]','promo','x')")
    raw.commit()
    raw.close()

    conn = connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comments)")}
    assert {"parent_id", "author_is_channel_owner", "analysis_eligible", "exclusion_reason",
            "exclusion_source", "timestamps_json"} <= cols
    rows = {r["comment_id"]: dict(r) for r in conn.execute("SELECT * FROM comments")}
    assert len(rows) == 4, "마이그레이션이 행을 지웠다"
    assert (rows["o1"]["analysis_eligible"], rows["o1"]["exclusion_reason"],
            rows["o1"]["exclusion_source"], rows["o1"]["author_is_channel_owner"]) == \
        (0, "own_channel", "migration", 1)
    assert (rows["o2"]["analysis_eligible"], rows["o2"]["exclusion_reason"],
            rows["o2"]["author_is_channel_owner"]) == (1, None, 0)
    assert rows["o2"]["timestamps_json"] == '[{"text": "3:15", "seconds": 195}]'
    assert (rows["o3"]["analysis_eligible"], rows["o3"]["exclusion_reason"],
            rows["o3"]["author_is_channel_owner"]) == (1, None, None)
    assert rows["o4"]["exclusion_reason"] == "spam_confirmed"
    assert all(r["parent_id"] is None for r in rows.values())
    conn.close()

    # 두 번째 연결은 아무것도 바꾸지 않는다
    again = connect(path)
    assert {r["comment_id"]: dict(r) for r in again.execute("SELECT * FROM comments")} == rows
    again.close()


def test_old_observation_table_is_migrated():
    path = pathlib.Path(tempfile.mkdtemp()) / "obs.db"
    conn = _db(path)
    conn.execute("""CREATE TABLE observation_comments(run_id TEXT,comment_id TEXT,video_id TEXT,
                        parent_id TEXT,author_id TEXT,text TEXT,published_at TEXT,fetched_at TEXT,
                        PRIMARY KEY(run_id,comment_id))""")
    conn.execute("INSERT INTO observation_comments VALUES ('r','t','v1',NULL,?,'고정','x','x')", (CH,))
    conn.execute("INSERT INTO observation_comments VALUES ('r','rep','v1','t',?,'답 7:07','x','x')",
                 (VIEWER,))
    ensure_schema(conn)
    rows = {r["comment_id"]: dict(r) for r in conn.execute("SELECT * FROM observation_comments")}
    assert (rows["t"]["analysis_eligible"], rows["t"]["exclusion_reason"]) == (0, "own_channel")
    assert (rows["rep"]["analysis_eligible"], rows["rep"]["exclusion_reason"]) == (1, None)
    assert rows["rep"]["timestamps_json"] == '[{"text": "7:07", "seconds": 427}]'
