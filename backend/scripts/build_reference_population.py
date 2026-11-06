"""채널의 고정 reference population manifest 를 만들고 동결 준비한다.

설계: docs/design/reference-population.md. 두 단계를 **명령으로 분리**한다.

1. fetch  — (네트워크) YouTube Data API 로 업로드 메타·통계만 받아 스냅샷 JSON 으로 저장.
            댓글 엔드포인트는 쓰지 않는다. `--confirm-api` 없이는 예상 유닛만 출력하고 끝난다.
2. build  — (오프라인) 스냅샷 JSON 또는 기존 DB(read-only)와 split CSV 로 manifest 를 만든다.
            기본은 dry-run: 개수와 해시만 출력하고 아무것도 쓰지 않는다. `--write PATH` 일 때만 저장.

backend 에서 실행:

    python scripts/build_reference_population.py fetch --channel "<채널 URL>" \
        --max-uploads 1500 --out data/reference/chim-uploads-YYYYMMDD.json            # 예상 유닛만 출력
    python scripts/build_reference_population.py fetch ... --confirm-api                # 실제 호출
    python scripts/build_reference_population.py build --uploads-json data/reference/chim-uploads-YYYYMMDD.json \
        --split fixtures/labeled/discovery-chim-claude-20260914/split.csv                # dry-run
    python scripts/build_reference_population.py build ... --write ../docs/reference/chim-reference-manifest.json

동결은 사람이 한다: manifest 를 git 에 커밋한 뒤에만 split 결과와 비교한다.
출력에는 ID·조회수·제목을 찍지 않는다 (개수·해시만).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.reference import (  # noqa: E402
    DEFAULT_RULES,
    UPLOADS_SCHEMA,
    manifest_summary,
    select_reference,
    upload_from_api_item,
    verify_manifest,
)


def _print(value) -> None:
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# --------------------------------------------------------------------------
# 입력 (오프라인)
# --------------------------------------------------------------------------

def read_split_ids(path: str) -> set[str]:
    with open(path, encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [r.get("video_id") for r in rows]
    if not ids or any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("split CSV 의 video_id 가 비었거나 중복됐다")
    return set(ids)


def read_uploads_json(path: str) -> tuple[list[dict], str | None]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if raw.get("schema") != UPLOADS_SCHEMA:
            raise ValueError("uploads 스냅샷 schema 가 다르다")
        return raw["videos"], raw.get("channel_id")
    return raw, None


def read_uploads_db(path: str) -> tuple[list[dict], str | None]:
    """기존 DB 를 **읽기 전용**으로 연다. 영상별 최신 스냅샷만 쓴다."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT v.video_id, v.channel_id, v.published_at, v.duration_sec,
                      v.is_live, v.live_evidence, s.view_count, s.captured_at
               FROM videos v
               JOIN video_stats_snapshots s ON s.video_id = v.video_id
               WHERE s.snapshot_id = (SELECT MAX(snapshot_id) FROM video_stats_snapshots
                                      WHERE video_id = v.video_id)""")]
        channels = [r[0] for r in conn.execute("SELECT channel_id FROM channels")]
    finally:
        conn.close()
    return rows, channels[0] if len(channels) == 1 else None


# --------------------------------------------------------------------------
# build (오프라인)
# --------------------------------------------------------------------------

def cmd_build(a) -> int:
    split_ids = read_split_ids(a.split)
    if a.uploads_json:
        uploads, channel = read_uploads_json(a.uploads_json)
    else:
        uploads, channel = read_uploads_db(a.uploads_db)
    manifest = select_reference(uploads, split_ids, channel_id=a.channel_id or channel,
                                boundary=a.boundary, rules=DEFAULT_RULES)
    verify_manifest(manifest)
    summary = manifest_summary(manifest)
    summary["mode"] = "write" if a.write else "dry-run"
    _print(summary)
    if not a.write:
        return 0
    out = Path(a.write)
    if out.exists():
        raise FileExistsError(f"manifest 가 이미 있다 — 덮어쓰지 않는다: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    sys.stdout.buffer.write((
        f"\n저장: {out}\n동결 절차: 규칙 사람 승인 확인 → git add {out} → 커밋 "
        "(split 결과와 비교하기 전에). 커밋 후 manifest 를 수정하면 해시 검증에서 거부된다.\n"
    ).encode("utf-8"))
    return 0


# --------------------------------------------------------------------------
# fetch (네트워크 — 이 경로만 API 를 부른다)
# --------------------------------------------------------------------------

def estimate_units(max_uploads: int) -> int:
    """channels.list 1 + playlistItems 페이지 + videos.list 묶음. 전부 1유닛 엔드포인트."""
    pages = math.ceil(max_uploads / 50)
    return 1 + pages + pages


def cmd_fetch(a) -> int:
    est = estimate_units(a.max_uploads)
    plan = {"mode": "api" if a.confirm_api else "dry-run", "channel": a.channel,
            "max_uploads": a.max_uploads, "estimated_units_max": est,
            "endpoints": ["channels", "playlistItems", "videos"], "comments": False}
    _print(plan)
    if not a.confirm_api:
        return 0
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(f"스냅샷이 이미 있다 — 덮어쓰지 않는다: {out}")

    from app import config
    from app.clients.youtube import YouTubeClient

    config.load_env()
    yt = YouTubeClient(config.require("YOUTUBE_API_KEY", "YouTube API 키 필요"), daily_quota=max(est * 2, 50))
    ch = yt.resolve_channel(a.channel)
    ids = yt.list_upload_ids(ch["uploads_playlist"], a.max_uploads)
    captured_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos = [upload_from_api_item(item, captured_at) for item in yt.fetch_videos(ids)]
    snapshot = {
        "schema": UPLOADS_SCHEMA,
        "channel_id": ch["channel_id"],
        "fetched_at": captured_at,
        "requested_max_uploads": a.max_uploads,
        "listed_ids_n": len(ids),
        "videos_n": len(videos),
        "units_used": yt.units_used,
        "videos": sorted(videos, key=lambda v: v["video_id"]),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    _print({"saved": str(out), "videos_n": len(videos), "units_used": yt.units_used})
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="오프라인: manifest 생성 (기본 dry-run)")
    src = b.add_mutually_exclusive_group(required=True)
    src.add_argument("--uploads-json")
    src.add_argument("--uploads-db", help="기존 SQLite DB (read-only 로 연다)")
    b.add_argument("--split", required=True)
    b.add_argument("--channel-id")
    b.add_argument("--boundary", help="split 최초 게시 시각(ISO). 없으면 uploads 에서 계산")
    b.add_argument("--write", help="manifest 저장 경로. 없으면 dry-run")
    b.set_defaults(fn=cmd_build)

    f = sub.add_parser("fetch", help="네트워크: 업로드 메타·통계 스냅샷 수집")
    f.add_argument("--channel", required=True)
    f.add_argument("--max-uploads", type=int, default=1500)
    f.add_argument("--out", required=True)
    f.add_argument("--confirm-api", action="store_true", help="실제로 API 를 호출한다")
    f.set_defaults(fn=cmd_fetch)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as error:
        sys.stderr.buffer.write(f"거부: {error}\n".encode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
