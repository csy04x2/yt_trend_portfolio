"""3단계 영상 유형 — 체계 저장, 라벨 적재, 유형별 성과 집계.

판정 자체는 아직 오프라인이다. 5단계 댓글 라벨과 같은 방식으로, Claude Code
가 제목을 보고 유형을 붙인 JSON 을 여기서 검증해 넣는다.

**성과는 세 판으로 낸다 — 쇼츠 / 롱폼 / 합침.**

합쳐서만 보면 정반대인 두 집단이 상쇄된다. 14F 에서 역사·인문은 쇼츠 조회
배수 0.59(최하위)인데 롱폼은 1.61(1위)이고, 합치면 0.88 이 나온다. 그 0.88 은
어느 쪽도 설명하지 못한다. 쇼츠와 롱폼은 시청자가 다른 것을 하러 오는 자리라
같은 표에 놓으면 서로를 지운다.

그래도 합침을 남기는 것은 채널 전체를 한눈에 볼 자리가 필요해서다. 대신
리포트가 "가려질 수 있다"를 함께 말해야 한다.

롱폼 = standard + long. 조회 배수의 분모는 여전히 세 축(shorts/standard/long)
으로 나눠 계산한다 — 여기서 묶는 것은 보여주는 단위일 뿐 계산 단위가 아니다.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics as st
from collections import defaultdict

SHORTS, LONGFORM, ALL = "shorts", "longform", "all"


def view_group(length_axis: str) -> str:
    """세 길이 축을 보여주기용 두 묶음으로. 계산용 축은 건드리지 않는다."""
    return SHORTS if length_axis == "shorts" else LONGFORM


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 체계와 라벨 적재
# --------------------------------------------------------------------------

class ValidationError(ValueError):
    pass


def validate(payload: dict, video_ids: dict[str, str]) -> list[dict]:
    """{index: type_code} 라벨을 검증한다. 조용히 넘기지 않는다.

    video_ids 는 {index: video_id}. 댓글 판정과 같은 규칙 — 없는 번호,
    빠진 번호, 정의되지 않은 유형 코드를 전부 모아 한 번에 알린다.
    """
    types = payload.get("types") or {}
    labels = payload.get("labels") or {}
    if not types:
        raise ValidationError("types 가 비었다 — 유형 체계 없이 라벨만 넣을 수 없다")

    problems: list[str] = []
    out: list[dict] = []
    for idx, code in labels.items():
        if idx not in video_ids:
            problems.append(f"입력에 없는 번호 {idx}")
            continue
        if code not in types:
            problems.append(f"{idx}: 정의되지 않은 유형 코드 {code!r}")
            continue
        out.append({"index": idx, "video_id": video_ids[idx], "type_code": code})

    missing = sorted(set(video_ids) - set(labels), key=lambda x: int(x))
    if missing:
        problems.append(f"빠진 번호 {missing[:20]}"
                        + (f" 외 {len(missing)-20}개" if len(missing) > 20 else ""))
    if problems:
        raise ValidationError("\n  - ".join(["유형 라벨이 입력과 맞지 않는다:"] + problems))
    return out


def save_taxonomy(conn, channel_id: str, types: dict[str, str],
                  source: str, prompt_version: str, axis: str = "topic") -> int:
    """새 버전으로 저장하고 **같은 축의** 이전 버전만 비활성화한다.

    축이 둘(topic, segment)이라 채널마다 활성 체계도 둘이다. 축을 구분하지
    않고 끄면 코너를 넣는 순간 주제가 꺼진다.
    """
    row = conn.execute(
        "SELECT MAX(version) FROM video_taxonomies WHERE channel_id=?",
        (channel_id,)).fetchone()
    version = (row[0] or 0) + 1
    conn.execute("UPDATE video_taxonomies SET is_active=0 WHERE channel_id=? AND axis=?",
                 (channel_id, axis))
    cur = conn.execute(
        """INSERT INTO video_taxonomies
               (channel_id, axis, version, source, prompt_version, types_json,
                created_at, is_active)
           VALUES (?,?,?,?,?,?,?,1)""",
        (channel_id, axis, version, source, prompt_version,
         json.dumps(types, ensure_ascii=False), _now()))
    return cur.lastrowid


def active_taxonomy(conn, channel_id: str, axis: str = "topic"):
    return conn.execute(
        "SELECT * FROM video_taxonomies WHERE channel_id=? AND axis=? AND is_active=1",
        (channel_id, axis)).fetchone()


def save_labels(conn, taxonomy_id: int, rows: list[dict],
                prompt_version: str, model: str) -> int:
    for r in rows:
        conn.execute(
            """INSERT INTO video_type_labels
                   (video_id, taxonomy_id, prompt_version, model, type_code, labeled_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(video_id, taxonomy_id, prompt_version, model)
               DO UPDATE SET type_code=excluded.type_code, labeled_at=excluded.labeled_at""",
            (r["video_id"], taxonomy_id, prompt_version, model, r["type_code"], _now()))
    return len(rows)


# --------------------------------------------------------------------------
# 유형별 성과 — 세 판
# --------------------------------------------------------------------------

METRIC_KEYS = ("view_count", "like_rate", "comment_rate",
               "view_multiple", "comment_rate_multiple")


def _med(group: list[dict], key: str) -> float | None:
    xs = [g[key] for g in group if g.get(key) is not None]
    return st.median(xs) if xs else None


def aggregate(conn, channel_id: str, run_id: str, taxonomy_id: int,
              prompt_version: str, model: str) -> list[dict]:
    """쇼츠 / 롱폼 / 합침 세 판을 만들어 type_metrics 에 넣는다.

    평균이 아니라 중앙값을 쓴다. 조회수는 한두 편이 크게 튀어 평균을 끌고
    가는데, 그 한 편이 유형 전체의 성격은 아니다.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT l.type_code, v.length_axis, m.*
           FROM video_type_labels l
           JOIN videos v ON v.video_id = l.video_id
           JOIN video_metrics m ON m.video_id = l.video_id
           WHERE l.taxonomy_id=? AND l.prompt_version=? AND l.model=?
             AND v.channel_id=?
             AND m.run_id = (SELECT run_id FROM video_metrics
                             ORDER BY computed_at DESC LIMIT 1)""",
        (taxonomy_id, prompt_version, model, channel_id))]

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        buckets[(r["type_code"], view_group(r["length_axis"]))].append(r)
        buckets[(r["type_code"], ALL)].append(r)

    out = []
    now = _now()
    for (code, axis), group in buckets.items():
        rec = {"type_code": code, "length_axis": axis, "video_count": len(group)}
        for k in METRIC_KEYS:
            rec[f"med_{k}"] = _med(group, k)
        conn.execute(
            """INSERT INTO type_metrics
                   (channel_id, run_id, taxonomy_id, type_code, length_axis,
                    video_count, med_view_count, med_like_rate, med_comment_rate,
                    med_view_multiple, med_comment_rate_multiple, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(channel_id, run_id, taxonomy_id, type_code, length_axis)
               DO UPDATE SET video_count=excluded.video_count,
                   med_view_count=excluded.med_view_count,
                   med_like_rate=excluded.med_like_rate,
                   med_comment_rate=excluded.med_comment_rate,
                   med_view_multiple=excluded.med_view_multiple,
                   med_comment_rate_multiple=excluded.med_comment_rate_multiple,
                   computed_at=excluded.computed_at""",
            (channel_id, run_id, taxonomy_id, code, axis, len(group),
             rec["med_view_count"], rec["med_like_rate"], rec["med_comment_rate"],
             rec["med_view_multiple"], rec["med_comment_rate_multiple"], now))
        out.append(rec)
    return out


def masked_types(metrics: list[dict], gap: float = 0.6) -> list[dict]:
    """합침이 가리고 있는 유형을 찾는다.

    쇼츠와 롱폼의 조회 배수가 크게 갈리는데 합침만 보면 그 사실이 사라진다.
    리포트가 "이 줄은 믿지 말고 아래 두 판을 보라"고 말할 수 있어야 한다.
    """
    by = defaultdict(dict)
    for m in metrics:
        by[m["type_code"]][m["length_axis"]] = m
    flagged = []
    for code, d in by.items():
        s, l = d.get(SHORTS), d.get(LONGFORM)
        if not s or not l:
            continue
        a, b = s.get("med_view_multiple"), l.get("med_view_multiple")
        if a is None or b is None:
            continue
        if abs(a - b) >= gap:
            flagged.append({"type_code": code, "shorts": a, "longform": b,
                            "gap": abs(a - b)})
    return sorted(flagged, key=lambda x: -x["gap"])
