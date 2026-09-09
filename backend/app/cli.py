"""프로토타입 CLI.

세 명령이 있고, 앞의 둘은 Claude를 부르지 않아 비용이 0이다.

    collect  채널 URL → SQLite (YouTube 키 필요, 금전 비용 0)
    rules    쌓인 댓글에 규칙을 적용하고 무엇이 걸렸는지 보여준다 (비용 0)
    stats    수집 현황

지금 답이 필요한 질문 — 규칙이 무엇을 잘못 버리는가 — 은 `rules`만으로
답할 수 있다. Claude 호출은 아직 붙지 않았다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.clients.youtube import (  # noqa: E402
    ChannelNotFound,
    QuotaExhausted,
    YouTubeClient,
    classify_live,
)
from app.db.connection import connect  # noqa: E402
from app.pipeline.rules import (  # noqa: E402
    DEFAULT_CONFIG,
    MODEL_RULE,
    screen_comments,
    summarize,
)

RULES_VERSION = "rules-v1"
DEFAULT_DB = "./data/yt_trend.db"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_duration(iso: str) -> int:
    """PT1H2M3S → 초."""
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

def cmd_collect(args) -> int:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("YOUTUBE_API_KEY 가 없다. .env 를 읽거나 환경변수로 넣어라.", file=sys.stderr)
        return 2

    conn = connect(args.db)
    yt = YouTubeClient(api_key=key)
    run_id = uuid.uuid4().hex[:12]

    try:
        ch = yt.resolve_channel(args.url)
    except ChannelNotFound as e:
        print(f"채널을 찾을 수 없다: {e}", file=sys.stderr)
        return 1
    print(f"[채널] {ch['title']}  ({ch['channel_id']})")

    conn.execute(
        """INSERT INTO channels (channel_id, input_url, handle, title,
               uploads_playlist, subscriber_count, first_analyzed_at, last_analyzed_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(channel_id) DO UPDATE SET last_analyzed_at=excluded.last_analyzed_at""",
        (ch["channel_id"], args.url, ch["handle"], ch["title"],
         ch["uploads_playlist"], ch["subscriber_count"], now(), now()),
    )

    ids = yt.list_upload_ids(ch["uploads_playlist"], args.max_videos)
    print(f"[영상] {len(ids)}개")

    for item in yt.fetch_videos(ids):
        sn, cd, st = item["snippet"], item["contentDetails"], item.get("statistics", {})
        is_live, evidence = classify_live(item)
        conn.execute(
            """INSERT INTO videos (video_id, channel_id, title, description, tags_json,
                   duration_sec, published_at, thumbnail_url, is_live, live_evidence,
                   first_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id) DO NOTHING""",
            (item["id"], ch["channel_id"], sn["title"], sn.get("description"),
             json.dumps(sn.get("tags") or [], ensure_ascii=False),
             parse_duration(cd.get("duration")), sn["publishedAt"],
             (sn.get("thumbnails", {}).get("high") or {}).get("url"),
             is_live, evidence, now()),
        )
        conn.execute(
            """INSERT INTO video_stats_snapshots
                   (video_id, run_id, captured_at, view_count, like_count, comment_count)
               VALUES (?,?,?,?,?,?) ON CONFLICT(video_id, run_id) DO NOTHING""",
            (item["id"], run_id, now(),
             int(st.get("viewCount") or 0),
             int(st["likeCount"]) if "likeCount" in st else None,
             int(st.get("commentCount") or 0)),
        )

    # ---- 댓글: 페이지마다 커서를 커밋한다 ----
    total = 0
    rows = conn.execute(
        "SELECT video_id, title, comments_newest_at FROM videos WHERE channel_id=?"
        " ORDER BY published_at DESC", (ch["channel_id"],)
    ).fetchall()

    try:
        for v in rows:
            newest_seen = v["comments_newest_at"]
            got, page_newest, stop = 0, None, False
            for page in yt.iter_comment_pages(v["video_id"]):
                if not page:
                    break
                for c in page:
                    if newest_seen and c["published_at"] <= newest_seen:
                        stop = True
                        break
                    conn.execute(
                        """INSERT INTO comments (comment_id, video_id, author_channel_id,
                               author_name, text, published_at, like_count, fetched_at)
                           VALUES (?,?,?,?,?,?,?,?)
                           ON CONFLICT(comment_id) DO NOTHING""",
                        (c["comment_id"], c["video_id"], c["author_channel_id"],
                         c["author_name"], c["text"], c["published_at"],
                         c["like_count"], now()),
                    )
                    page_newest = page_newest or c["published_at"]
                    got += 1
                    total += 1
                # 페이지를 저장한 직후에 커서를 옮긴다
                if page_newest:
                    conn.execute(
                        "UPDATE videos SET comments_newest_at=? WHERE video_id=?",
                        (page_newest, v["video_id"]),
                    )
                if stop or got >= args.max_comments:
                    break
            if got:
                print(f"  {v['title'][:38]:<40} 댓글 {got}")
    except QuotaExhausted as e:
        print(f"\n[중단] 할당량 소진 — {e}", file=sys.stderr)
        print("여기까지 저장한 것은 그대로 남는다. 내일 다시 실행하면 이어받는다.")

    print(f"\n댓글 {total}개 · 할당량 {yt.units_used}유닛 사용 (한도 {yt.daily_quota})")
    print(f"DB: {args.db}")
    return 0


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _load_comments(args) -> tuple[list[dict], str]:
    if args.fixture:
        data = json.loads(pathlib.Path(args.fixture).read_text(encoding="utf-8"))
        return data["comments"], f"표본 {args.fixture}"
    conn = connect(args.db)
    q = "SELECT comment_id, video_id, author_channel_id, text, like_count FROM comments"
    params: tuple = ()
    if args.video_id:
        q += " WHERE video_id=?"
        params = (args.video_id,)
    q += " ORDER BY published_at DESC"
    if args.limit:
        q += f" LIMIT {int(args.limit)}"
    return [dict(r) for r in conn.execute(q, params)], f"DB {args.db}"


def cmd_rules(args) -> int:
    comments, source = _load_comments(args)
    if not comments:
        print("댓글이 없다. 먼저 collect 를 돌리거나 --fixture 를 써라.", file=sys.stderr)
        return 1

    screens = screen_comments(comments, DEFAULT_CONFIG)
    by_id = {c["comment_id"]: c for c in comments}
    counts = summarize(screens)

    print(f"출처: {source}   댓글 {len(comments)}개\n")
    print("verdict 분포")
    for k in ("keep", "suspect_repeat", "irrelevant", "promo"):
        n = counts.get(k, 0)
        pct = n / len(comments) * 100
        print(f"  {k:<16} {n:>5}  {pct:5.1f}%  {'█' * int(pct / 2)}")

    dropped = [s for s in screens if s.verdict in ("promo", "irrelevant")]
    print(f"\n규칙이 확정 제외한 것 {len(dropped)}건 — 오탐이 있는지 눈으로 본다")
    for s in dropped[: args.show]:
        t = by_id[s.comment_id]["text"].replace("\n", " ")[:64]
        print(f"  [{s.verdict:<10}] {','.join(s.rule_flags):<24} {t}")

    flagged = [s for s in screens if s.verdict == "keep" and s.rule_flags]
    print(f"\n통과했지만 표시가 붙은 것 {len(flagged)}건 — 버리지 않고 LLM으로 간다")
    for s in flagged[: args.show]:
        t = by_id[s.comment_id]["text"].replace("\n", " ")[:64]
        print(f"  [{','.join(s.rule_flags):<12}] {t}")

    to_llm = sum(1 for s in screens if s.needs_llm)
    print(f"\nLLM으로 보낼 댓글 {to_llm}건 = 묶음 {-(-to_llm // 20)}회 호출")
    print("(규칙은 감성을 판단하지 않는다. 이모지만 있는 댓글도 여기 포함된다)")

    if args.save:
        conn = connect(args.db)
        for s in screens:
            conn.execute(
                """INSERT INTO comment_screens
                       (comment_id, prompt_version, model, rule_flags_json, verdict, screened_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       verdict=excluded.verdict, rule_flags_json=excluded.rule_flags_json""",
                (s.comment_id, RULES_VERSION, MODEL_RULE,
                 json.dumps(s.rule_flags, ensure_ascii=False), s.verdict, now()),
            )
        print(f"\ncomment_screens 에 저장했다 (prompt_version={RULES_VERSION}, model={MODEL_RULE})")
    return 0


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------

def cmd_stats(args) -> int:
    conn = connect(args.db)
    for label, sql in (
        ("채널", "SELECT COUNT(*) FROM channels"),
        ("영상", "SELECT COUNT(*) FROM videos"),
        ("댓글", "SELECT COUNT(*) FROM comments"),
        ("규칙 판정", "SELECT COUNT(*) FROM comment_screens"),
    ):
        print(f"  {label:<10} {conn.execute(sql).fetchone()[0]:>7}")
    rows = conn.execute(
        "SELECT title, comments_newest_at, comments_complete FROM videos LIMIT 5"
    ).fetchall()
    if rows:
        print("\n영상별 댓글 커서 (앞 5개)")
        for r in rows:
            print(f"  {r['title'][:38]:<40} newest={r['comments_newest_at']} "
                  f"complete={r['comments_complete']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="yt-trend", description=__doc__)
    p.add_argument("--db", default=os.environ.get("DB_PATH", DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="채널 URL → SQLite (비용 0, YouTube 키 필요)")
    c.add_argument("url")
    c.add_argument("--max-videos", type=int, default=50)
    c.add_argument("--max-comments", type=int, default=2000)
    c.set_defaults(fn=cmd_collect)

    r = sub.add_parser("rules", help="규칙 필터를 돌려보고 무엇이 걸렸는지 본다 (비용 0)")
    r.add_argument("--fixture", help="DB 대신 표본 JSON 을 쓴다")
    r.add_argument("--video-id")
    r.add_argument("--limit", type=int)
    r.add_argument("--show", type=int, default=20, help="예시로 보여줄 건수")
    r.add_argument("--save", action="store_true", help="comment_screens 에 저장")
    r.set_defaults(fn=cmd_rules)

    s = sub.add_parser("stats", help="수집 현황")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
