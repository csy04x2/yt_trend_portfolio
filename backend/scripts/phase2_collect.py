"""Reaction Phase 2 표본 수집 — 채널 2 × 영상 2 × 원댓글 50 = 200, 봉인.

사람이 확정한 설계를 그대로 실행한다. 해석하지 않는다.

    python scripts/phase2_collect.py collect    수집 → 봉인 표본·manifest·보고서 생성
    python scripts/phase2_collect.py validate   산출물을 기계적으로 검증

## 기존 수집기를 건드리지 않는 이유

`YouTubeClient.iter_comment_pages`와 `observable_collect`는 `order="time"`(최신순)으로
받는다. Phase 2의 표본 규칙은 인기순에 해당하는 정렬이라 이 경로에서만
`commentThreads.list`를 `order=relevance`로 **명시해** 부른다. 기존 작업의 기본 동작은
그대로다.

`order=relevance`가 YouTube 웹 화면의 「인기 댓글순」과 같은 결과인지는 검증하지 않았다.
그래서 기록에는 "YouTube Data API `order=relevance` 기준"이라고만 적는다.

## 블라인드

이 스크립트는 댓글 본문과 영상 제목을 **파일에만** 쓰고 화면에는 내지 않는다.
화면에는 ID·개수·형식 메타데이터·해시만 나온다. 댓글 내용으로 영상이나 댓글을
고르거나 바꾸는 코드는 없다. 판정(Reaction·Target·감성·주제)도 하지 않는다.

## 멈추는 경우

형식 판단이 필요한 영상이 선정 순번에 걸리면 즉시 멈춘다 — 진행 중·예정 라이브,
라이브 다시보기·프리미어, 180초 이하(쇼츠일 수 있음). 이런 영상도 수집 시점 댓글이
50개 미만이면 형식과 무관하게 "다음 최근 영상" 규칙으로 넘어가므로 판단이 필요 없다.
산출물은 네 영상이 모두 확정된 뒤에 한 번에 쓴다. 멈추면 아무 파일도 쓰지 않는다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import sqlite3
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import config  # noqa: E402
from app.clients.youtube import (  # noqa: E402
    ChannelNotFound,
    CommentsDisabled,
    QuotaExhausted,
    YouTubeClient,
)

# ---------------------------------------------------------------------------
# 사람이 확정한 설계 — 해석하지 않는다
# ---------------------------------------------------------------------------

CHANNELS = [  # (키, 핸들, 기대 채널명)
    ("A", "@syukaworld", "슈카월드"),
    ("B", "@MBCNEWS11", "MBCNEWS"),
]
VIDEOS_PER_CHANNEL = 2
COMMENTS_PER_VIDEO = 50
TOTAL = len(CHANNELS) * VIDEOS_PER_CHANNEL * COMMENTS_PER_VIDEO  # 200
SHORTS_SUSPECT_MAX_SEC = 180   # 쇼츠 최대 길이. 이하이면 쇼츠 여부를 API로 확정할 수 없다
CANDIDATE_WINDOW = 200         # 최신 업로드 몇 편 안에서 게시 시각 역순으로 본다

COMMENT_PARAMS = {"part": "snippet", "order": "relevance",
                  "textFormat": "plainText", "maxResults": COMMENTS_PER_VIDEO}
ORDERING_STATEMENT = ("YouTube Data API v3 commentThreads.list order=relevance 기준. "
                      "YouTube 웹 UI의 Top comments와 동일한 결과인지는 검증하지 않았다.")

EXCLUDED_NAMES = ["14F", "안원잘부 / Woni", "침착맨", "Carden / 카더정원"]
EXCLUDED_DBS = ["yt_trend.db", "woni.db", "chim.db", "carden.db"]
EXCLUDED_KNOWN_IDS = {"UCUj6rrhMTR9pipbAWBAMvUQ",   # 침착맨
                      "UCWpY0eSJtyO-qNAPbKFRSSg"}   # 안원잘부

RUN_DATE = "2026-09-17"
RAW_DIR = BACKEND / "data" / "phase2-reaction" / RUN_DATE          # .gitignore 대상
SEAL_DIR = BACKEND / "fixtures" / "phase2-reaction"
RAW_PATH = RAW_DIR / "raw_collection.json"                          # 원문 포함
SEALED_PATH = SEAL_DIR / "sealed_sample.jsonl"                      # 원문 미포함
MANIFEST_PATH = SEAL_DIR / "manifest.json"                          # 원문 미포함
REPORT_PATH = REPO / "docs" / "reports" / f"phase2-reaction-sampling-{RUN_DATE}.md"  # 원문 미포함

LABEL_KEY_PATTERN = re.compile(r"reaction|target|sentiment|topic|label", re.I)


class Stop(Exception):
    """사람의 결정이 필요한 지점. 메시지에 댓글 본문·영상 제목을 넣지 않는다."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def iso_seconds(iso: str | None) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str | None) -> str | None:
    return None if s is None else sha256_bytes(s.encode("utf-8"))


def excluded_channel_ids() -> set[str]:
    ids = set(EXCLUDED_KNOWN_IDS)
    for name in EXCLUDED_DBS:
        p = BACKEND / "data" / name
        if p.exists():
            c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            ids |= {r[0] for r in c.execute("SELECT channel_id FROM channels")}
            c.close()
    return ids


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------

def top_level_threads(yt: YouTubeClient, video_id: str) -> list[tuple[dict, str, int]]:
    """order=relevance 로 원댓글 thread 를 최대 50개까지. (item, fetched_at, page) 목록."""
    out: list[tuple[dict, str, int]] = []
    token, page = None, 0
    while len(out) < COMMENTS_PER_VIDEO:
        params = dict(COMMENT_PARAMS, videoId=video_id)
        if token:
            params["pageToken"] = token
        body = yt._get("commentThreads", **params)
        page += 1
        fetched = now()
        for item in body.get("items", []):
            out.append((item, fetched, page))
            if len(out) == COMMENTS_PER_VIDEO:
                break
        token = body.get("nextPageToken")
        if not token:
            break
    return out


def select_videos(yt: YouTubeClient, key: str, ch: dict, excluded: set[str]):
    """최신순으로 걸어 내려가며 규칙에 맞는 영상 2개를 고른다. 댓글 내용은 보지 않는다."""
    ids = yt.list_upload_ids(ch["uploads_playlist"], CANDIDATE_WINDOW)
    metas = yt.fetch_videos(ids)
    metas.sort(key=lambda it: it["snippet"]["publishedAt"], reverse=True)

    selected, log = [], []
    for it in metas:
        sn, cd, st = it["snippet"], it["contentDetails"], it.get("statistics", {})
        vid = it["id"]
        ld = it.get("liveStreamingDetails")
        lbc = sn.get("liveBroadcastContent")
        dur = iso_seconds(cd.get("duration"))
        cc = st.get("commentCount")
        cc = int(cc) if cc is not None else None
        row = {"video_id": vid, "published_at": sn["publishedAt"], "duration_sec": dur,
               "live_broadcast_content": lbc,
               "live_streaming_details": None if not ld else
               {k: bool(ld.get(k)) for k in ("actualStartTime", "actualEndTime", "scheduledStartTime")},
               "comment_count_statistic": cc, "top_level_available": None, "decision": None}
        log.append(row)

        if sn["channelId"] != ch["channel_id"] or sn["channelId"] in excluded:
            raise Stop(f"[{key}] {vid}: 영상 소유 채널이 대상 채널과 다르거나 제외 채널이다")

        if cc is None or cc < COMMENTS_PER_VIDEO:
            row["decision"] = "skip_comment_count_below_50"
            continue

        fmt = None
        if lbc in ("live", "upcoming"):
            fmt = "live_or_upcoming"
        elif ld:
            fmt = "live_archive_or_premiere"
        elif dur is not None and dur <= SHORTS_SUSPECT_MAX_SEC:
            fmt = "shorts_suspect_duration_le_180s"
        if fmt:
            row["decision"] = f"stop_format_judgment:{fmt}"
            raise Stop(f"[{key}] {vid}: 형식 판단 필요 ({fmt}) · 길이 {dur}초 · "
                       f"broadcast={lbc} · liveDetails={row['live_streaming_details']} · "
                       f"댓글 통계 {cc}")

        try:
            threads = top_level_threads(yt, vid)
        except CommentsDisabled:
            row["decision"] = "skip_comments_disabled"
            continue
        row["top_level_available"] = len(threads)
        if len(threads) < COMMENTS_PER_VIDEO:
            row["decision"] = "skip_top_level_below_50"
            continue

        row["decision"] = f"selected_{key}{len(selected) + 1}"
        selected.append((it, threads))
        if len(selected) == VIDEOS_PER_CHANNEL:
            break

    if len(selected) < VIDEOS_PER_CHANNEL:
        raise Stop(f"[{key}] 최신 {CANDIDATE_WINDOW}편 안에서 규칙에 맞는 영상이 "
                   f"{len(selected)}편뿐이다")
    return selected, log


def comment_record(key, slot, pos, ch, video, item, fetched, page):
    th = item["snippet"]
    tlc = th["topLevelComment"]
    sn = tlc["snippet"]
    author = (sn.get("authorChannelId") or {}).get("value")
    original = sn.get("textOriginal")
    display = sn.get("textDisplay")
    text = original if original is not None else display
    video_channel_id = video["snippet"]["channelId"]
    comment_video_id = sn.get("videoId") or th.get("videoId")

    if comment_video_id and comment_video_id != video["id"]:
        eligible, reason = False, "misplaced_data"
    elif author and author == video_channel_id:
        eligible, reason = False, "own_channel"
    else:
        eligible, reason = True, None

    return {
        "sample_id": f"{slot}-{pos:02d}",
        "channel_key": key, "channel_id": ch["channel_id"], "channel_name": ch["title"],
        "video_slot": slot, "video_id": video["id"],
        "video_title": video["snippet"]["title"],
        "video_channel_id": video_channel_id,
        "sample_position": pos,
        "thread_id": item["id"], "comment_id": tlc["id"],
        "thread_channel_id": th.get("channelId"),
        "comment_video_id": comment_video_id,
        "parent_id": sn.get("parentId"),
        "is_reply": False,
        "text": text,
        "text_source": "textOriginal" if original is not None else "textDisplay(textFormat=plainText)",
        "text_display": display,
        "text_original_returned": original is not None,
        "published_at": sn.get("publishedAt"),
        "updated_at": sn.get("updatedAt"),
        "author_channel_id": author,
        "like_count": sn.get("likeCount"),
        "total_reply_count": th.get("totalReplyCount"),
        "can_reply": th.get("canReply"),
        "is_public": th.get("isPublic"),
        "analysis_eligible": eligible,
        "exclusion_reason": reason,
        "collected_at": fetched,
        "api_page": page,
        "collection_method": "commentThreads.list",
        "ordering_method": "order=relevance",
        "provenance": "YouTube Data API v3 · scripts/phase2_collect.py",
    }


def sealed_row(r: dict) -> dict:
    """판정 전 상태만. 원문 대신 원문 해시를 싣는다."""
    return {
        "sample_id": r["sample_id"], "channel_key": r["channel_key"],
        "channel_id": r["channel_id"], "channel_name": r["channel_name"],
        "video_slot": r["video_slot"], "video_id": r["video_id"],
        "video_channel_id": r["video_channel_id"], "sample_position": r["sample_position"],
        "comment_id": r["comment_id"], "thread_id": r["thread_id"],
        "is_top_level": r["parent_id"] is None and r["is_reply"] is False,
        "author_channel_id_present": bool(r["author_channel_id"]),
        "published_at": r["published_at"], "updated_at": r["updated_at"],
        "text_sha256": sha256_text(r["text"]),
        "analysis_eligible": r["analysis_eligible"], "exclusion_reason": r["exclusion_reason"],
        "collected_at": r["collected_at"], "ordering_method": r["ordering_method"],
    }


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> str:
    data = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows)
    path.write_bytes(data.encode("utf-8"))
    return sha256_bytes(data.encode("utf-8"))


def write_json(path: pathlib.Path, obj) -> str:
    data = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def completeness(rows, field):
    return sum(1 for r in rows if r.get(field) not in (None, ""))


def collect() -> int:
    for p in (RAW_PATH, SEALED_PATH, MANIFEST_PATH, REPORT_PATH):
        if p.exists():
            print(f"STOP: 기존 산출물이 있어 덮어쓰지 않는다 — {p.relative_to(REPO)}")
            return 2

    config.load_env()
    key = config.get("YOUTUBE_API_KEY")
    if not key:
        print("STOP: YOUTUBE_API_KEY 없음")
        return 2
    yt = YouTubeClient(api_key=key)
    excluded = excluded_channel_ids()
    started = now()

    channels, videos, comments, selection_log = [], [], [], {}
    try:
        for ckey, handle, expected in CHANNELS:
            ch = yt.resolve_channel(f"https://www.youtube.com/{handle}")
            if ch["title"] != expected or ch["channel_id"] in excluded:
                raise Stop(f"[{ckey}] 채널 식별 불일치 · handle={handle} "
                           f"channel_id={ch['channel_id']} title={ch['title']!r}")
            channels.append({"channel_key": ckey, "handle": handle, "channel_id": ch["channel_id"],
                             "channel_name": ch["title"], "resolved_at": now()})
            selected, log = select_videos(yt, ckey, ch, excluded)
            selection_log[ckey] = log
            for vi, (video, threads) in enumerate(selected, 1):
                slot = f"{ckey}{vi}"
                st = video.get("statistics", {})
                videos.append({
                    "video_slot": slot, "channel_key": ckey, "video_id": video["id"],
                    "video_title": video["snippet"]["title"],
                    "video_channel_id": video["snippet"]["channelId"],
                    "published_at": video["snippet"]["publishedAt"],
                    "duration_sec": iso_seconds(video["contentDetails"].get("duration")),
                    "live_broadcast_content": video["snippet"].get("liveBroadcastContent"),
                    "live_streaming_details_present": bool(video.get("liveStreamingDetails")),
                    "statistics_at_selection": {k: st.get(k) for k in ("viewCount", "likeCount", "commentCount")},
                    "top_level_collected": len(threads),
                })
                for pos, (item, fetched, page) in enumerate(threads, 1):
                    comments.append(comment_record(ckey, slot, pos, ch, video, item, fetched, page))
    except Stop as e:
        print(f"STOP: {e}")
        print(f"(파일을 쓰지 않았다 · 사용 유닛 {yt.units_used})")
        return 2
    except (QuotaExhausted, ChannelNotFound) as e:
        print(f"STOP: {type(e).__name__} (파일을 쓰지 않았다 · 사용 유닛 {yt.units_used})")
        return 2

    if len(comments) != TOTAL:
        print(f"STOP: 표본이 {len(comments)}개라 {TOTAL}개로 봉인할 수 없다")
        return 2

    finished = now()
    SEAL_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    sealed = [sealed_row(r) for r in comments]
    sealed_sha = write_jsonl(SEALED_PATH, sealed)

    design = {"channels": [c[2] for c in CHANNELS], "videos_per_channel": VIDEOS_PER_CHANNEL,
              "top_level_comments_per_video": COMMENTS_PER_VIDEO, "total": TOTAL,
              "excluded_channels": EXCLUDED_NAMES,
              "taxonomy_reference": "docs/reaction-phase1-checkpoint.md (Phase 2 frozen, 수정하지 않음)",
              "replacement": "없음 — 제외된 댓글을 51번째로 보충하지 않는다"}
    api = {"endpoint": "commentThreads.list", "params": COMMENT_PARAMS,
           "ordering_statement": ORDERING_STATEMENT,
           "video_metadata": "channels.list · playlistItems.list(uploads) · videos.list "
                             "part=snippet,contentDetails,statistics,liveStreamingDetails"}
    selection_rule = {
        "rule": "수집 시점 기준 원댓글 50개 이상 확보 가능한 최근 적격 영상 2개",
        "recency": f"업로드 재생목록 최신 {CANDIDATE_WINDOW}편을 publishedAt 역순으로 정렬",
        "skip_rules": ["commentCount 통계 50 미만 또는 비공개 → 다음 영상",
                       "order=relevance 원댓글 50개 미만 → 다음 영상",
                       "댓글 사용 중지 → 다음 영상"],
        "stop_rules": ["댓글 50개 이상인데 live/upcoming", "댓글 50개 이상인데 라이브 다시보기·프리미어",
                       "댓글 50개 이상인데 180초 이하(쇼츠 여부 불확정)"],
        "content_used_for_selection": False,
    }

    raw = {"phase": "reaction-phase2", "artifact": "raw_collection", "contains_raw_text": True,
           "collection_started_at": started, "collection_finished_at": finished,
           "design": design, "api": api, "video_selection": {**selection_rule, "log": selection_log},
           "channels": channels, "videos": videos, "comments": comments,
           "sealed_sample_sha256": sealed_sha, "api_units_used": yt.units_used,
           "not_stored": ["authorDisplayName", "authorProfileImageUrl", "authorChannelUrl"]}
    raw_sha = write_json(RAW_PATH, raw)

    elig = sum(1 for r in comments if r["analysis_eligible"])
    reasons = {}
    for r in comments:
        if r["exclusion_reason"]:
            reasons[r["exclusion_reason"]] = reasons.get(r["exclusion_reason"], 0) + 1
    fields = ["channel_id", "channel_name", "video_id", "video_title", "video_channel_id", "comment_id",
              "text", "published_at", "updated_at", "author_channel_id", "parent_id",
              "collected_at", "collection_method", "ordering_method", "provenance"]
    comp = {f: completeness(comments, f) for f in fields}
    comp["parent_id"] = sum(1 for r in comments if r["parent_id"] is None)  # 원댓글이면 비어 있어야 정상
    comp["text_original_returned"] = sum(1 for r in comments if r["text_original_returned"])

    manifest = {
        "phase": "reaction-phase2", "artifact": "manifest", "contains_raw_text": False,
        "collection_started_at": started, "collection_finished_at": finished,
        "design": design, "api": api,
        "video_selection": {**selection_rule, "log": selection_log},
        "channels": channels,
        "videos": [{k: v for k, v in x.items() if k != "video_title"} for x in videos],
        "counts": {"channels": len(channels), "videos": len(videos), "raw_sample": len(comments),
                   "analysis_eligible": elig, "excluded": len(comments) - elig,
                   "exclusion_reasons": reasons},
        "field_completeness_of_200": comp,
        "files": {
            "raw_collection": {"path": RAW_PATH.relative_to(REPO).as_posix(), "sha256": raw_sha,
                               "contains_raw_text": True, "git": "ignored (backend/data/)"},
            "sealed_sample": {"path": SEALED_PATH.relative_to(REPO).as_posix(), "sha256": sealed_sha,
                              "contains_raw_text": False, "rows": len(sealed)},
        },
        "sealed_sample_sha256": sealed_sha,
        "api_units_used": yt.units_used,
    }
    write_json(MANIFEST_PATH, manifest)
    write_report(manifest, channels, videos, comp, reasons, elig, sealed_sha, raw_sha)

    print(f"수집 완료 · 채널 {len(channels)} · 영상 {len(videos)} · 표본 {len(comments)} · "
          f"분석 대상 {elig} · 유닛 {yt.units_used}")
    print("다음: python scripts/phase2_collect.py validate")
    return 0


def write_report(manifest, channels, videos, comp, reasons, elig, sealed_sha, raw_sha):
    cname = {c["channel_key"]: c for c in channels}
    lines = [
        f"# Reaction Phase 2 표본 수집 보고 — {RUN_DATE}",
        "",
        "댓글 본문은 이 문서에 없다. Reaction·Target 판정은 하지 않았다.",
        "",
        "## 설계 (사람이 확정, 해석하지 않음)",
        "",
        f"- 채널 2개 × 영상 2개 × 원댓글 50개 = {TOTAL}개",
        "- 사용 금지 채널: 14F, 안원잘부 / Woni, 침착맨, Carden / 카더정원",
        "- 기준 체계: `docs/reaction-phase1-checkpoint.md` (Phase 2 동결, 수정하지 않음)",
        "- 교체 없음: 분석 대상에서 빠진 댓글을 51번째 댓글로 채우지 않는다",
        "",
        "## 채널과 영상",
        "",
        "| 슬롯 | 채널 | channel_id | video_id | 게시(UTC) | 길이(초) | 수집 원댓글 |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for v in videos:
        c = cname[v["channel_key"]]
        lines.append(f"| {v['video_slot']} | {c['channel_name']} | `{c['channel_id']}` | `{v['video_id']}` | "
                     f"{v['published_at']} | {v['duration_sec']} | {v['top_level_collected']} |")
    exc = ", ".join(f"{k} {n}" for k, n in reasons.items()) or "없음"
    lines += [
        "",
        "## 표본",
        "",
        f"- 원자료 표본: {manifest['counts']['raw_sample']}개",
        f"- 분석 대상(analysis_eligible): {elig}개",
        f"- 제외 사유별: {exc}",
        "",
        "## 정렬과 선정 방식",
        "",
        f"- 댓글 정렬: {ORDERING_STATEMENT}",
        "- 원댓글만 수집(commentThreads의 topLevelComment). 답글은 표본에 넣지 않았다.",
        f"- 영상 선정: 업로드 재생목록 최신 {CANDIDATE_WINDOW}편을 게시 시각 역순으로 보며, "
        "수집 시점 댓글 통계 50 미만·원댓글 50 미만·댓글 사용 중지인 영상은 건너뛰었다. "
        "댓글 내용은 선정에 쓰지 않았다.",
        "- 댓글이 50개 이상인데 라이브·프리미어·180초 이하인 영상이 선정 순번에 오면 멈추도록 했고, "
        "이번 수집에서는 그런 영상이 선정 순번에 오지 않았다.",
        f"- 수집 시각(UTC): {manifest['collection_started_at']} ~ {manifest['collection_finished_at']}",
        "",
        "## 칸별 채움 (200개 중)",
        "",
        "| 칸 | 채워진 수 |",
        "|---|---:|",
    ]
    for f, n in comp.items():
        note = " (원댓글이면 비어 있어야 정상 — 비어 있는 수)" if f == "parent_id" else ""
        lines.append(f"| `{f}`{note} | {n} |")
    lines += [
        "",
        "저장하지 않은 칸: 작성자 표시 이름, 프로필 이미지, 작성자 채널 URL (요구 칸이 아니다).",
        "",
        "## 무결성",
        "",
        f"- 봉인 표본 SHA-256: `{sealed_sha}`",
        f"- 원자료 SHA-256: `{raw_sha}`",
        "",
        "## 파일",
        "",
        f"- 원자료 (원문 포함, Git 제외 경로): `{RAW_PATH.relative_to(REPO).as_posix()}`",
        f"- 봉인 표본 (원문 미포함, 원문 해시 포함): `{SEALED_PATH.relative_to(REPO).as_posix()}`",
        f"- manifest (원문 미포함): `{MANIFEST_PATH.relative_to(REPO).as_posix()}`",
        f"- 이 보고서 (원문 미포함): `{REPORT_PATH.relative_to(REPO).as_posix()}`",
        "",
        "## 블라인드",
        "",
        "수집 스크립트는 댓글 본문과 영상 제목을 화면에 출력하지 않았다. 댓글 내용으로 영상이나 "
        "댓글을 고르거나 바꾸지 않았고, 키워드 검색·감성·주제·Reaction·Target 판정을 하지 않았다.",
        "",
    ]
    REPORT_PATH.write_bytes("\n".join(lines).encode("utf-8"))


# ---------------------------------------------------------------------------
# 검증 — 숫자만 출력한다
# ---------------------------------------------------------------------------

def validate() -> int:
    raw = json.loads(RAW_PATH.read_bytes().decode("utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_bytes().decode("utf-8"))
    sealed_bytes = SEALED_PATH.read_bytes()
    sealed = [json.loads(line) for line in sealed_bytes.decode("utf-8").splitlines() if line.strip()]
    rc = raw["comments"]
    raw_by_id = {r["comment_id"]: r for r in rc}
    excluded = excluded_channel_ids()

    checks = []
    def check(name, value, ok):
        checks.append((name, value, ok))

    ch_ids = {r["channel_id"] for r in sealed}
    vids = {r["video_id"] for r in sealed}
    per_video = {}
    for r in sealed:
        per_video[r["video_id"]] = per_video.get(r["video_id"], 0) + 1
    ids = [r["comment_id"] for r in sealed]
    sealed_sha = sha256_bytes(sealed_bytes)

    check("channels = 2", len(ch_ids), len(ch_ids) == 2)
    check("videos = 4", len(vids), len(vids) == 4)
    check("sampled comments = 200", len(sealed), len(sealed) == TOTAL)
    check("50 per video", sorted(per_video.values()), all(n == 50 for n in per_video.values()))
    check("duplicate comment_id = 0", len(ids) - len(set(ids)), len(ids) == len(set(ids)))
    check("all top-level (sealed)", sum(1 for r in sealed if r["is_top_level"]),
          all(r["is_top_level"] for r in sealed))
    check("all top-level (raw parent_id empty)", sum(1 for r in rc if r["parent_id"] is None),
          all(r["parent_id"] is None and r["is_reply"] is False for r in rc))
    bad_ch = sum(1 for r in sealed if r["channel_id"] in excluded or r["video_channel_id"] in excluded)
    check("excluded channels present = 0", bad_ch, bad_ch == 0)
    carden = {cid for name in ("carden.db",) for cid in
              ([] if not (BACKEND / "data" / name).exists() else
               [x[0] for x in sqlite3.connect(f"file:{(BACKEND / 'data' / name).as_posix()}?mode=ro",
                                              uri=True).execute("SELECT channel_id FROM channels")])}
    carden_n = sum(1 for r in sealed if r["channel_id"] in carden or r["video_channel_id"] in carden)
    check("Carden present = 0", carden_n, carden_n == 0 and bool(carden))
    label_keys = sorted({k for r in sealed for k in r if LABEL_KEY_PATTERN.search(k)})
    check("Reaction/Target/label keys in sealed = 0", len(label_keys), not label_keys)
    trace = sum(1 for r in sealed if r["comment_id"] in raw_by_id
                and raw_by_id[r["comment_id"]]["video_id"] == r["video_id"]
                and sha256_text(raw_by_id[r["comment_id"]]["text"]) == r["text_sha256"])
    check("traceable to raw (id + video + text hash)", trace, trace == len(sealed) and len(rc) == len(sealed))
    check("sealed SHA-256 matches manifest", sealed_sha[:16] + "…",
          sealed_sha == manifest["sealed_sample_sha256"] == raw["sealed_sample_sha256"])
    raw_sha = sha256_bytes(RAW_PATH.read_bytes())
    check("raw SHA-256 matches manifest", raw_sha[:16] + "…",
          raw_sha == manifest["files"]["raw_collection"]["sha256"])

    own = sum(1 for r in sealed if r["exclusion_reason"] == "own_channel")
    own_recheck = sum(1 for r in rc if r["author_channel_id"] and r["author_channel_id"] == r["video_channel_id"])
    check("own_channel count = recomputed", own, own == own_recheck)
    elig = sum(1 for r in sealed if r["analysis_eligible"])
    check("eligible + excluded = 200", f"{elig} + {len(sealed) - elig}", elig + (len(sealed) - elig) == TOTAL)
    reason_ok = all((r["analysis_eligible"] and r["exclusion_reason"] is None) or
                    (not r["analysis_eligible"] and r["exclusion_reason"]) for r in sealed)
    check("eligibility ↔ exclusion_reason consistent", reason_ok, reason_ok)

    width = max(len(c[0]) for c in checks)
    for name, value, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {value}")

    reasons = {}
    for r in sealed:
        if r["exclusion_reason"]:
            reasons[r["exclusion_reason"]] = reasons.get(r["exclusion_reason"], 0) + 1
    print("\n  completeness (of 200)")
    for f in ("author_channel_id", "published_at", "updated_at", "video_channel_id", "text"):
        print(f"    {f:<18} {completeness(rc, f)}")
    print(f"    text_original_returned {sum(1 for r in rc if r['text_original_returned'])}")
    print(f"\n  own_channel {own} · analysis_eligible {elig} · exclusion_reasons {reasons or '{}'}")
    print(f"  sealed SHA-256 {sealed_sha}")
    failed = sum(1 for c in checks if not c[2])
    print(f"\n  {len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "collect":
        sys.exit(collect())
    if cmd == "validate":
        sys.exit(validate())
    print(__doc__.splitlines()[0])
    print("usage: python scripts/phase2_collect.py collect|validate")
    sys.exit(2)
