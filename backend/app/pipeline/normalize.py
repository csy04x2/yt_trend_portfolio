"""2단계 정규화.

3년 전 영상과 지난주 영상의 누적 조회수는 비교 대상이 아니다. 이 단계가
비교 가능한 형태로 바꾼다.

내는 값 네 가지:

    length_axis    shorts / standard / long
    like_rate      좋아요 ÷ 조회      시간 영향이 적어 "평가"에 가장 가깝다
    comment_rate   댓글 ÷ 조회        반응의 강도. 긍정·부정 양쪽 다 올린다
    views_per_day  조회 ÷ 경과일      보조. 오래된 영상에 불리해 단독 사용 금지
    view_multiple  조회 ÷ 비교군 중앙값

**조회 배수의 분모는 아직 미결이다** (결정 문서 3장). 여기서는 후보 ①
"같은 길이 축 · 같은 분기의 중앙값"을 기본값으로 쓰되, 표본이 모자라면
값을 내지 않고 `view_multiple_basis` 에 이유를 남긴다. 영상 두 개로 낸
배수는 자기 자신이 분모라 항상 1 근처가 나오고, 그 1은 정보가 아니라
착시다. 근거를 함께 저장하면 리포트가 "왜 비었는지"를 말할 수 있다.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

SHORTS = "shorts"
STANDARD = "standard"
LONG = "long"


@dataclass
class NormalizeConfig:
    shorts_max_sec: int = 180
    standard_max_sec: int = 1200
    # 비교군이 이보다 작으면 조회 배수를 내지 않는다.
    # 자기 자신을 뺀 나머지가 최소 이만큼은 있어야 중앙값이 의미를 갖는다.
    view_multiple_min_pop: int = 3
    # 채널 내 이 비율 이상의 영상에 똑같이 나타나는 줄은 상용구로 본다
    boilerplate_ratio: float = 0.3


DEFAULT = NormalizeConfig()


def length_axis(duration_sec: int, cfg: NormalizeConfig = DEFAULT) -> str:
    if duration_sec <= cfg.shorts_max_sec:
        return SHORTS
    if duration_sec <= cfg.standard_max_sec:
        return STANDARD
    return LONG


def quarter_of(published_at: str) -> str:
    """2026-09-09T… → 2026Q3."""
    d = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def days_since(published_at: str, now: dt.datetime | None = None) -> float:
    d = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return max((now - d).total_seconds() / 86400, 1.0)


def strip_boilerplate(descriptions: list[str], cfg: NormalizeConfig = DEFAULT) -> list[str]:
    """채널 내 여러 영상에 공통으로 반복되는 줄을 뺀다.

    구독 안내나 SNS 링크가 유형화 입력을 오염시킨다. 영상이 적으면
    (3개 미만) 우연히 겹친 줄까지 지울 위험이 커서 그대로 둔다.
    """
    if len(descriptions) < 3:
        return list(descriptions)

    counts: dict[str, int] = {}
    for d in descriptions:
        for line in {ln.strip() for ln in (d or "").splitlines() if ln.strip()}:
            counts[line] = counts.get(line, 0) + 1

    threshold = max(2, int(len(descriptions) * cfg.boilerplate_ratio))
    boiler = {ln for ln, n in counts.items() if n >= threshold}

    out = []
    for d in descriptions:
        kept = [ln for ln in (d or "").splitlines() if ln.strip() not in boiler]
        out.append("\n".join(kept).strip())
    return out


def view_multiple(
    video: dict,
    population: list[dict],
    cfg: NormalizeConfig = DEFAULT,
) -> tuple[float | None, str]:
    """조회 배수와 그 근거를 함께 돌려준다.

    population 은 같은 채널의 모든 영상. 여기서 같은 길이 축·같은 분기이고
    라이브가 아닌 것만 골라 비교군으로 쓴다. 자기 자신은 뺀다 — 넣으면
    분모가 자기를 포함해 배수가 1 쪽으로 눌린다.
    """
    peers = [
        v for v in population
        if v["video_id"] != video["video_id"]
        and not v.get("is_live")
        and v.get("length_axis") == video.get("length_axis")
        and quarter_of(v["published_at"]) == quarter_of(video["published_at"])
        and v.get("view_count")
    ]
    if len(peers) < cfg.view_multiple_min_pop:
        return None, (
            f"비교군 부족: 같은 길이 축({video.get('length_axis')}) · "
            f"{quarter_of(video['published_at'])} 영상이 {len(peers)}개 "
            f"(최소 {cfg.view_multiple_min_pop}개 필요)"
        )
    med = statistics.median(v["view_count"] for v in peers)
    if not med:
        return None, "비교군 중앙값이 0"
    basis = (f"같은 길이 축·분기 {len(peers)}개의 중앙값 {med:,.0f} "
             f"(분모 정의는 미결 — 아키텍처 6.2)")
    return video["view_count"] / med, basis


def compute(video: dict, population: list[dict],
            cfg: NormalizeConfig = DEFAULT) -> dict:
    """영상 하나의 정규화 지표. 순수 함수 — DB 를 모른다."""
    views = video.get("view_count") or 0
    likes = video.get("like_count")
    comments = video.get("comment_count") or 0

    mult, basis = view_multiple(video, population, cfg)
    return {
        "video_id": video["video_id"],
        "length_axis": video.get("length_axis"),
        "view_count": views,
        # 좋아요가 비공개면 좋아요율도 없다. 0 으로 채우면 "평가가 나쁘다"로 읽힌다
        "like_rate": (likes / views) if (likes is not None and views) else None,
        "comment_rate": (comments / views) if views else None,
        "views_per_day": views / days_since(video["published_at"]) if views else None,
        "view_multiple": mult,
        "view_multiple_basis": basis,
    }


# --------------------------------------------------------------------------
# DB 연결부
# --------------------------------------------------------------------------

def run(conn, channel_id: str, run_id: str, cfg: NormalizeConfig = DEFAULT) -> list[dict]:
    """채널 하나를 정규화하고 videos·video_metrics 를 채운다.

    항상 전체 재계산한다 (싸다). 최신 스냅샷을 쓴다.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT v.video_id, v.title, v.description, v.duration_sec,
                  v.published_at, v.is_live,
                  s.view_count, s.like_count, s.comment_count
           FROM videos v
           JOIN video_stats_snapshots s ON s.video_id = v.video_id
           WHERE v.channel_id = ?
             AND s.snapshot_id = (SELECT MAX(snapshot_id)
                                  FROM video_stats_snapshots
                                  WHERE video_id = v.video_id)""",
        (channel_id,),
    )]
    if not rows:
        return []

    for r in rows:
        r["length_axis"] = length_axis(r["duration_sec"], cfg)

    cleaned = strip_boilerplate([r.get("description") or "" for r in rows], cfg)
    for r, c in zip(rows, cleaned):
        r["description_clean"] = c

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out = []
    for r in rows:
        conn.execute(
            "UPDATE videos SET length_axis=?, description_clean=? WHERE video_id=?",
            (r["length_axis"], r["description_clean"], r["video_id"]),
        )
        m = compute(r, rows, cfg)
        conn.execute(
            """INSERT INTO video_metrics (video_id, run_id, length_axis, view_count,
                   like_rate, comment_rate, views_per_day, view_multiple,
                   view_multiple_basis, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id, run_id) DO UPDATE SET
                   length_axis=excluded.length_axis, view_count=excluded.view_count,
                   like_rate=excluded.like_rate, comment_rate=excluded.comment_rate,
                   views_per_day=excluded.views_per_day,
                   view_multiple=excluded.view_multiple,
                   view_multiple_basis=excluded.view_multiple_basis,
                   computed_at=excluded.computed_at""",
            (m["video_id"], run_id, m["length_axis"], m["view_count"],
             m["like_rate"], m["comment_rate"], m["views_per_day"],
             m["view_multiple"], m["view_multiple_basis"], now),
        )
        m["title"] = r["title"]
        out.append(m)
    return out
