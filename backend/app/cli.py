"""프로토타입 CLI.

Anthropic API 를 부르는 명령은 아직 없다. 전부 금전 비용 0이다.

    collect        채널 URL → SQLite (YouTube 키 필요)
    collect-video  영상 URL 하나만 → SQLite (약 5유닛)
    rules          쌓인 댓글에 규칙을 적용하고 무엇이 걸렸는지 본다
    export-batch   댓글 묶음을 판정용 파일로 (Claude Code 가 판정)
    import-batch   판정 결과를 검증하고 저장
    stats          수집 현황과 설정 상태

지금 답이 필요한 질문 — 규칙이 무엇을 잘못 버리는가 — 은 `rules`만으로
답할 수 있다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.clients.youtube import (  # noqa: E402
    ChannelNotFound,
    QuotaExhausted,
    YouTubeClient,
)
from app.db.connection import connect  # noqa: E402
from app.pipeline.collect import collect_channel, collect_video  # noqa: E402
from app.pipeline.offline_llm import (  # noqa: E402
    ValidationError,
    export_batch,
    validate_result,
)
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


# --------------------------------------------------------------------------
# collect / collect-video
# --------------------------------------------------------------------------

def _client(args) -> tuple:
    key = config.require(
        "YOUTUBE_API_KEY",
        "Google Cloud Console에서 YouTube Data API v3를 켜고 API 키를 발급받는다.",
    )
    conn = connect(args.db)
    yt = YouTubeClient(api_key=key, daily_quota=int(config.get("YOUTUBE_DAILY_QUOTA")))
    return conn, yt, uuid.uuid4().hex[:12]


def _report(yt, db) -> None:
    print(f"\n할당량 {yt.units_used}유닛 사용 (한도 {yt.daily_quota}) · 금전 비용 0")
    print(f"DB: {db}")


def cmd_collect(args) -> int:
    conn, yt, run_id = _client(args)
    try:
        collect_channel(conn, yt, args.url, run_id, args.max_videos, args.max_comments)
    except ChannelNotFound as e:
        print(f"채널을 찾을 수 없다: {e}", file=sys.stderr)
        return 1
    _report(yt, args.db)
    return 0


def cmd_collect_video(args) -> int:
    """영상 하나만 받는다. 실험할 때 채널 전체를 받을 이유가 없다."""
    conn, yt, run_id = _client(args)
    try:
        collect_video(conn, yt, args.url, run_id, args.max_comments)
    except ValueError as e:
        print(f"{e}", file=sys.stderr)
        return 1
    except ChannelNotFound as e:
        print(f"채널을 찾을 수 없다: {e}", file=sys.stderr)
        return 1
    except QuotaExhausted as e:
        print(f"[중단] 할당량 소진 — {e}", file=sys.stderr)
        print("여기까지 저장한 것은 그대로 남는다. 다시 실행하면 이어받는다.")
        _report(yt, args.db)
        return 1
    _report(yt, args.db)
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
# export-batch / import-batch  (API 없이 Claude Code가 판정하는 경로)
# --------------------------------------------------------------------------

def cmd_export_batch(args) -> int:
    comments, source = _load_comments(args)
    screens = {s.comment_id: s for s in screen_comments(comments, DEFAULT_CONFIG)}
    # 규칙을 통과한 것만 LLM으로 간다 (keep, suspect_repeat)
    target = [c for c in comments
              if screens[c["comment_id"]].verdict in ("keep", "suspect_repeat")]
    if not target:
        print("판정할 댓글이 없다.", file=sys.stderr)
        return 1
    target = target[: args.size]

    title = args.video_title
    if not title and not args.fixture:
        row = connect(args.db).execute(
            "SELECT title FROM videos WHERE video_id=?", (target[0].get("video_id"),)
        ).fetchone()
        title = row["title"] if row else "(제목 없음)"
    if not title:
        data = json.loads(pathlib.Path(args.fixture).read_text(encoding="utf-8"))
        title = data.get("_video_title", "(제목 없음)")

    out_dir = pathlib.Path(args.out)
    path = export_batch(target, title, args.batch_id, out_dir)
    print(f"출처: {source}")
    print(f"내보냈다: {path}   (댓글 {len(target)}건)")
    print(f"\n다음: 이 파일을 Claude Code에 읽히고, 판정 결과를")
    print(f"      {out_dir / (args.batch_id + '.result.json')} 로 저장한 뒤")
    print(f"      python -m app.cli import-batch {args.batch_id} --out {args.out}")
    return 0


def cmd_import_batch(args) -> int:
    out_dir = pathlib.Path(args.out)
    map_path = out_dir / f"{args.batch_id}.map.json"
    res_path = out_dir / f"{args.batch_id}.result.json"
    for p in (map_path, res_path):
        if not p.exists():
            print(f"없다: {p}", file=sys.stderr)
            return 1

    mapping = json.loads(map_path.read_text(encoding="utf-8"))["map"]
    result = json.loads(res_path.read_text(encoding="utf-8"))
    try:
        rows = validate_result(result, mapping)
    except ValidationError as e:
        print(f"검증 실패 — 저장하지 않았다.\n  {e}", file=sys.stderr)
        return 1

    version = result.get("prompt_version", "v1")
    model = result.get("model", "claude-code-offline")
    print(f"검증 통과: {len(rows)}건  (prompt_version={version}, model={model})")

    if args.dry_run:
        for r in rows[: args.show]:
            print(f"  {r['idx']:>3}. {r['sentiment']:<9} conf={r['confidence']} "
                  f"{'[반어의심]' if r['sarcasm_suspect'] else '':<10} {','.join(r['topics'])}")
        print("\n--dry-run 이라 DB에 쓰지 않았다.")
        return 0

    conn = connect(args.db)
    written = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO comment_labels (comment_id, prompt_version, model,
                       sentiment, sentiment_confidence, is_sarcasm_suspect,
                       topics_json, labeled_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       sentiment=excluded.sentiment,
                       sentiment_confidence=excluded.sentiment_confidence,
                       is_sarcasm_suspect=excluded.is_sarcasm_suspect,
                       topics_json=excluded.topics_json,
                       labeled_at=excluded.labeled_at""",
                (r["comment_id"], version, model, r["sentiment"], r["confidence"],
                 int(r["sarcasm_suspect"]),
                 json.dumps(r["topics"], ensure_ascii=False), now()),
            )
            written += 1
        except Exception as e:      # 표본에서 온 comment_id는 DB에 없을 수 있다
            print(f"  건너뜀 {r['comment_id']}: {e}", file=sys.stderr)
    print(f"comment_labels 에 {written}건 저장했다.")
    return 0


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------

def cmd_stats(args) -> int:
    print(f"설정: {config.describe()}")
    print()
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
    config.setup_console()
    p = argparse.ArgumentParser(prog="yt-trend", description=__doc__)
    config.load_env()
    p.add_argument("--db", default=config.get("DB_PATH", DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="채널 URL → SQLite (비용 0, YouTube 키 필요)")
    c.add_argument("url")
    c.add_argument("--max-videos", type=int, default=50)
    c.add_argument("--max-comments", type=int, default=2000)
    c.set_defaults(fn=cmd_collect)

    v = sub.add_parser("collect-video", help="영상 URL 하나만 → SQLite (약 5유닛)")
    v.add_argument("url", help="watch?v=… / youtu.be/… / shorts/… / 맨 영상 ID")
    v.add_argument("--max-comments", type=int, default=2000)
    v.set_defaults(fn=cmd_collect_video)

    r = sub.add_parser("rules", help="규칙 필터를 돌려보고 무엇이 걸렸는지 본다 (비용 0)")
    r.add_argument("--fixture", help="DB 대신 표본 JSON 을 쓴다")
    r.add_argument("--video-id")
    r.add_argument("--limit", type=int)
    r.add_argument("--show", type=int, default=20, help="예시로 보여줄 건수")
    r.add_argument("--save", action="store_true", help="comment_screens 에 저장")
    r.set_defaults(fn=cmd_rules)

    e = sub.add_parser("export-batch", help="댓글 묶음을 판정용 파일로 (API 불필요)")
    e.add_argument("batch_id")
    e.add_argument("--fixture", help="DB 대신 표본 JSON 을 쓴다")
    e.add_argument("--video-id")
    e.add_argument("--video-title")
    e.add_argument("--limit", type=int)
    e.add_argument("--size", type=int, default=20, help="묶음 크기")
    e.add_argument("--out", default="./data/batches")
    e.set_defaults(fn=cmd_export_batch)

    i = sub.add_parser("import-batch", help="판정 결과를 검증하고 저장")
    i.add_argument("batch_id")
    i.add_argument("--out", default="./data/batches")
    i.add_argument("--dry-run", action="store_true", help="검증만 하고 DB에 안 씀")
    i.add_argument("--show", type=int, default=20)
    i.set_defaults(fn=cmd_import_batch)

    s = sub.add_parser("stats", help="수집 현황과 설정 상태")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
