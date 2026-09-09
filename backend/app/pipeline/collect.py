"""1단계 수집.

채널 전체(`collect_channel`)와 영상 하나(`collect_video`)가 같은 함수를 쓴다.
영상 하나만 받는 경로가 필요한 이유는 실험 때문이다 — 채널 전체를 받지 않고
영상 하나의 댓글로 규칙·프롬프트를 시험하는 일이 반복해서 생긴다.

할당량은 유닛이지 돈이 아니다. 영상 하나면 videos.list 1 + channels.list 1 +
댓글 페이지당 1 이라, 댓글 263개짜리 영상도 5유닛이면 끝난다 (하루 한도 10,000).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import urllib.parse
from typing import Callable

from app.clients.youtube import QuotaExhausted, YouTubeClient, classify_live

Progress = Callable[[str], None]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_duration(iso: str) -> int:
    """PT1H2M3S → 초."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url: str) -> str:
    """영상 URL에서 ID를 뽑는다. 지원 형식은 아래 넷과 맨 ID."""
    u = url.strip()
    if VIDEO_ID.match(u):
        return u
    p = urllib.parse.urlparse(u)
    if p.netloc.endswith("youtu.be"):
        cand = p.path.lstrip("/").split("/")[0]
        if VIDEO_ID.match(cand):
            return cand
    if "youtube.com" in p.netloc:
        qs = urllib.parse.parse_qs(p.query)
        if "v" in qs and VIDEO_ID.match(qs["v"][0]):
            return qs["v"][0]
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
            if VIDEO_ID.match(parts[1]):
                return parts[1]
    raise ValueError(f"영상 ID를 찾을 수 없다: {url}")


# --------------------------------------------------------------------------
# 저장
# --------------------------------------------------------------------------

def upsert_channel(conn: sqlite3.Connection, ch: dict, input_url: str) -> None:
    conn.execute(
        """INSERT INTO channels (channel_id, input_url, handle, title,
               uploads_playlist, subscriber_count, first_analyzed_at, last_analyzed_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(channel_id) DO UPDATE SET
               last_analyzed_at=excluded.last_analyzed_at,
               title=excluded.title""",
        (ch["channel_id"], input_url, ch["handle"], ch["title"],
         ch["uploads_playlist"], ch["subscriber_count"], _now(), _now()),
    )


def upsert_video(conn: sqlite3.Connection, item: dict, channel_id: str,
                 run_id: str) -> None:
    """영상 메타는 처음 볼 때만, 통계 스냅샷은 실행마다 새로 쌓는다."""
    sn = item["snippet"]
    cd = item.get("contentDetails", {})
    st = item.get("statistics", {})
    is_live, evidence = classify_live(item)

    conn.execute(
        """INSERT INTO videos (video_id, channel_id, title, description, tags_json,
               duration_sec, published_at, thumbnail_url, is_live, live_evidence,
               first_seen_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(video_id) DO NOTHING""",
        (item["id"], channel_id, sn["title"], sn.get("description"),
         json.dumps(sn.get("tags") or [], ensure_ascii=False),
         parse_duration(cd.get("duration")), sn["publishedAt"],
         (sn.get("thumbnails", {}).get("high") or {}).get("url"),
         is_live, evidence, _now()),
    )
    conn.execute(
        """INSERT INTO video_stats_snapshots
               (video_id, run_id, captured_at, view_count, like_count, comment_count)
           VALUES (?,?,?,?,?,?) ON CONFLICT(video_id, run_id) DO NOTHING""",
        (item["id"], run_id, _now(),
         int(st.get("viewCount") or 0),
         int(st["likeCount"]) if "likeCount" in st else None,
         int(st.get("commentCount") or 0)),
    )


# --------------------------------------------------------------------------
# 댓글 — 커서 두 개
# --------------------------------------------------------------------------

def collect_comments(
    conn: sqlite3.Connection,
    yt: YouTubeClient,
    video_id: str,
    max_comments: int,
) -> int:
    """영상 하나의 댓글을 증분 수집한다. 받은 건수를 돌려준다.

    커서를 **페이지 단위로 커밋**한다. 단계 끝에 한꺼번에 쓰면, 할당량 소진으로
    영상 중간에 멈췄을 때 못 받은 구간을 다음 실행이 영원히 건너뛴다.
    """
    row = conn.execute(
        "SELECT comments_newest_at, comments_oldest_at, comments_complete"
        " FROM videos WHERE video_id=?", (video_id,)
    ).fetchone()
    newest_seen = row["comments_newest_at"] if row else None

    got, page_newest, oldest, stop = 0, None, None, False
    for page in yt.iter_comment_pages(video_id):
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
                 c["like_count"], _now()),
            )
            if page_newest is None:
                page_newest = c["published_at"]
            oldest = c["published_at"]
            got += 1

        # 페이지를 저장한 직후에만 커서를 옮긴다
        conn.execute(
            "UPDATE videos SET comments_newest_at=COALESCE(?, comments_newest_at),"
            " comments_oldest_at=? WHERE video_id=?",
            (page_newest, oldest, video_id),
        )
        if stop or got >= max_comments:
            break
    else:
        # 페이지가 다 떨어졌다 = 끝까지 받았다
        conn.execute(
            "UPDATE videos SET comments_complete=1 WHERE video_id=?", (video_id,)
        )
    return got


# --------------------------------------------------------------------------
# 오케스트레이션
# --------------------------------------------------------------------------

def collect_video(conn, yt: YouTubeClient, url: str, run_id: str,
                  max_comments: int, log: Progress = print) -> dict:
    """영상 하나만 받는다. 채널 행은 FK 때문에 함께 채운다."""
    vid = parse_video_id(url)
    items = yt.fetch_videos([vid])
    if not items:
        raise ValueError(f"영상을 찾을 수 없다 (비공개이거나 삭제됨): {vid}")
    item = items[0]
    channel_id = item["snippet"]["channelId"]

    ch = yt.resolve_channel(f"https://www.youtube.com/channel/{channel_id}")
    upsert_channel(conn, ch, url)
    upsert_video(conn, item, channel_id, run_id)

    st = item.get("statistics", {})
    log(f"[채널] {ch['title']}")
    log(f"[영상] {item['snippet']['title'][:60]}")
    log(f"       조회 {int(st.get('viewCount') or 0):,} · "
        f"좋아요 {st.get('likeCount', '비공개')} · 댓글 {st.get('commentCount', '?')}")

    got = collect_comments(conn, yt, vid, max_comments)
    log(f"[댓글] {got}건 수집")
    return {"video_id": vid, "channel_id": channel_id, "comments": got}


def collect_channel(conn, yt: YouTubeClient, url: str, run_id: str,
                    max_videos: int, max_comments: int,
                    log: Progress = print) -> dict:
    ch = yt.resolve_channel(url)
    log(f"[채널] {ch['title']}  ({ch['channel_id']})")
    upsert_channel(conn, ch, url)

    ids = yt.list_upload_ids(ch["uploads_playlist"], max_videos)
    log(f"[영상] {len(ids)}개")
    for item in yt.fetch_videos(ids):
        upsert_video(conn, item, ch["channel_id"], run_id)

    total = 0
    rows = conn.execute(
        "SELECT video_id, title FROM videos WHERE channel_id=? AND comments_disabled=0"
        " ORDER BY published_at DESC", (ch["channel_id"],)
    ).fetchall()
    try:
        for v in rows:
            got = collect_comments(conn, yt, v["video_id"], max_comments)
            total += got
            if got:
                log(f"  {v['title'][:38]:<40} 댓글 {got}")
    except QuotaExhausted as e:
        log(f"[중단] 할당량 소진 — {e}")
        log("여기까지 저장한 것은 그대로 남는다. 내일 다시 실행하면 이어받는다.")
    return {"channel_id": ch["channel_id"], "videos": len(ids), "comments": total}
