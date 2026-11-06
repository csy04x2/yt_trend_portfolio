"""고정 reference population 선정과 canonical 조회 배수.

설계 문서: `docs/design/reference-population.md`. 순수 함수만 둔다 — 파일·DB·네트워크를
모른다. 수집(YouTube API)과 파일 쓰기는 `backend/scripts/build_reference_population.py`
가 맡는다.

왜 따로 두나. 기존 `view_multiple` 세 정의(normalize·observable.compare·
breakout.recompute_multiples)는 모두 **실험 split 300편 안에서** 비교군을 고른다.
Development 영상의 분모에 Discovery/Holdout 영상이 섞이고, 세 정의끼리도 교환이
안 된다. 여기서는 split과 겹치지 않는 채널의 과거 업로드를 **결과를 보기 전에**
규칙으로 골라 동결하고, 그 동결본 하나만 분모로 쓴다.

두 단계:

    select_reference(uploads, split_ids, ...)   → manifest (규칙·ID·통계 스냅샷·SHA-256)
    canonical_view_multiple(video, manifest)     → 배수 + basis/provenance

선정 규칙은 **조회수를 보지 않는다.** 조회수는 스냅샷으로 manifest에 기록될 뿐
어떤 영상이 reference에 드느냐를 바꾸지 않는다 (조회수 비공개 영상만 "값 없음"으로
빠진다 — 값의 크기가 아니라 존재 여부다).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
from collections import Counter
from dataclasses import asdict, dataclass

from app.pipeline.normalize import LONG, SHORTS, STANDARD

MANIFEST_SCHEMA = "reference-population-manifest-v0.1"
UPLOADS_SCHEMA = "reference-uploads-snapshot-v0.1"
CANONICAL_DEFINITION = "view-multiple-reference-v0.1"
AXES = (SHORTS, STANDARD, LONG)

# 제외 사유. 앞에서부터 처음 걸린 하나만 센다.
EXCLUSION_REASONS = (
    "channel_mismatch",       # 다른 채널 영상
    "in_split",               # 실험 split(Discovery/Development/Holdout) 영상 — 절대 포함 금지
    "not_before_boundary",    # split 최초 게시 시각 이후 게시
    "outside_window",         # boundary 이전 window_days 밖
    "live_or_premiere",       # is_live 또는 liveStreamingDetails 근거 있음
    "upcoming_or_live_now",   # 예약·진행 중 방송
    "duration_unknown",       # 길이 축을 정할 수 없음
    "captured_at_unknown",    # 스냅샷 시각 없음 → 성숙도 판정 불가
    "not_matured",            # 게시 후 maturity_days 미만
    "views_unavailable",      # 조회수 비공개/누락
)


@dataclass(frozen=True)
class ReferenceRules:
    """선정 규칙. 값은 **제안(proposal)** 이며 사람 승인 전이다.

    승인되면 rules_status 를 "approved" 로 바꾸고 rules_version 을 올린다.
    결과를 본 뒤 값을 조정하지 않는다 — 조정이 필요하면 새 버전으로 다시 동결한다.
    """

    rules_version: str = "ref-rules-v0.1"
    rules_status: str = "proposal"
    # split 최초 게시 시각 이전 몇 일까지를 reference 창으로 보나
    window_days: int = 365
    # 게시 후 이만큼 지나야 누적 조회수가 "성숙"했다고 본다. 대상 영상에도 똑같이 적용한다
    maturity_days: int = 90
    # 길이 축별 최소 reference 편수. 모자라면 그 축은 배수를 내지 않는다
    min_per_axis: int = 20
    # normalize.NormalizeConfig 와 같은 경계 (180초 / 1200초)
    shorts_max_sec: int = 180
    standard_max_sec: int = 1200
    # liveStreamingDetails 가 있으면(프리미어 포함) 제외. classify_live 가 미확정이라 보수적으로
    exclude_live_evidence: bool = True
    stratum: str = "length_axis"


DEFAULT_RULES = ReferenceRules()


# --------------------------------------------------------------------------
# 공통
# --------------------------------------------------------------------------

def _ts(value: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"시간대 없는 시각은 받지 않는다: {value}")
    return d.astimezone(dt.timezone.utc)


def _iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quarter(d: dt.datetime) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def axis_of(duration_sec, rules: ReferenceRules = DEFAULT_RULES) -> str | None:
    if not isinstance(duration_sec, int) or isinstance(duration_sec, bool) or duration_sec <= 0:
        return None
    if duration_sec <= rules.shorts_max_sec:
        return SHORTS
    if duration_sec <= rules.standard_max_sec:
        return STANDARD
    return LONG


def _is_live(item: dict, rules: ReferenceRules) -> bool:
    if item.get("is_live"):
        return True
    return bool(rules.exclude_live_evidence and item.get("live_evidence"))


def _views(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def ids_sha256(ids) -> str:
    """ID 집합의 해시. 순서와 무관하다."""
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def manifest_sha256(manifest: dict) -> str:
    """manifest_sha256 필드를 뺀 나머지 전체의 SHA-256."""
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def verify_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("reference manifest schema 가 다르다")
    if manifest.get("manifest_sha256") != manifest_sha256(manifest):
        raise ValueError("reference manifest 해시 불일치 — 동결 후 수정된 manifest 는 쓰지 않는다")


# --------------------------------------------------------------------------
# 수집 결과 → 업로드 메타 (네트워크 없음)
# --------------------------------------------------------------------------

def upload_from_api_item(item: dict, captured_at: str) -> dict:
    """videos.list 응답 한 항목을 선정 입력 형식으로 바꾼다. 메타·통계만 쓴다.

    조회수 비공개면 0 이 아니라 None 이다 (0 으로 채우면 "안 봤다"로 읽힌다).
    """
    from app.pipeline.collect import parse_duration  # 순수 함수. DB 를 열지 않는다

    sn = item.get("snippet", {})
    st = item.get("statistics", {})
    lsd = item.get("liveStreamingDetails")
    return {
        "video_id": item["id"],
        "channel_id": sn.get("channelId"),
        "published_at": sn.get("publishedAt"),
        "duration_sec": parse_duration(item.get("contentDetails", {}).get("duration")),
        "is_live": 0,
        "live_evidence": canonical_json(lsd) if lsd else "",
        "live_broadcast_content": sn.get("liveBroadcastContent"),
        "view_count": int(st["viewCount"]) if "viewCount" in st else None,
        "captured_at": captured_at,
    }


# --------------------------------------------------------------------------
# 선정 + manifest
# --------------------------------------------------------------------------

def split_boundary(uploads: list[dict], split_ids) -> str:
    """split 영상 중 가장 이른 게시 시각. 모든 split ID 가 uploads 에 있어야 한다."""
    split_ids = set(split_ids)
    found = {u["video_id"]: u for u in uploads if u["video_id"] in split_ids}
    missing = split_ids - set(found)
    if missing:
        raise ValueError(
            f"split 영상 {len(missing)}편의 게시 시각이 uploads 에 없다 — boundary 를 명시해야 한다")
    return _iso(min(_ts(u["published_at"]) for u in found.values()))


def select_reference(
    uploads: list[dict],
    split_ids,
    *,
    channel_id: str | None = None,
    boundary: str | None = None,
    rules: ReferenceRules = DEFAULT_RULES,
) -> dict:
    """채널 업로드 메타에서 reference set 을 골라 manifest 로 돌려준다.

    uploads 각 항목: video_id, published_at, duration_sec, view_count, captured_at
    (선택: channel_id, is_live, live_evidence, live_broadcast_content).

    split_ids 의 영상은 어떤 경우에도 reference 에 들어가지 않는다.
    반환값은 입력 순서와 무관하게 같은 manifest(같은 해시)다.
    """
    split_ids = set(split_ids)
    if not split_ids:
        raise ValueError("split ID 가 비어 있다 — 제외 대상 없이 reference 를 만들지 않는다")
    seen = set()
    for u in uploads:
        if u["video_id"] in seen:
            raise ValueError(f"uploads 에 중복 video_id: {u['video_id']}")
        seen.add(u["video_id"])

    if boundary is None:
        boundary = split_boundary(uploads, split_ids)
    bound = _ts(boundary)
    early = [u for u in uploads if u["video_id"] in split_ids and _ts(u["published_at"]) < bound]
    if early:
        raise ValueError("boundary 보다 먼저 게시된 split 영상이 있다 — boundary 가 잘못됐다")
    window_start = bound - dt.timedelta(days=rules.window_days)

    excluded = Counter()
    chosen = []
    for u in uploads:
        vid = u["video_id"]
        pub = _ts(u["published_at"])
        axis = axis_of(u.get("duration_sec"), rules)
        views = _views(u.get("view_count"))
        if channel_id and u.get("channel_id") and u["channel_id"] != channel_id:
            reason = "channel_mismatch"
        elif vid in split_ids:
            reason = "in_split"
        elif pub >= bound:
            reason = "not_before_boundary"
        elif pub < window_start:
            reason = "outside_window"
        elif _is_live(u, rules):
            reason = "live_or_premiere"
        elif u.get("live_broadcast_content") in ("live", "upcoming"):
            reason = "upcoming_or_live_now"
        elif axis is None:
            reason = "duration_unknown"
        elif not u.get("captured_at"):
            reason = "captured_at_unknown"
        elif (_ts(u["captured_at"]) - pub).total_seconds() / 86400 < rules.maturity_days:
            reason = "not_matured"
        elif views is None:
            reason = "views_unavailable"
        else:
            reason = None
        if reason:
            excluded[reason] += 1
            continue
        age = (_ts(u["captured_at"]) - pub).total_seconds() / 86400
        chosen.append({
            "video_id": vid,
            "published_at": _iso(pub),
            "duration_sec": u["duration_sec"],
            "length_axis": axis,
            "view_count": views,
            "captured_at": _iso(_ts(u["captured_at"])),
            "age_days": round(age, 3),
        })

    chosen.sort(key=lambda r: r["video_id"])
    if split_ids & {r["video_id"] for r in chosen}:  # 방어. 위 규칙상 도달 불가
        raise AssertionError("split 영상이 reference 에 들어갔다")

    strata = {}
    for axis in AXES:
        rows = [r for r in chosen if r["length_axis"] == axis]
        n = len(rows)
        strata[axis] = {
            "n": n,
            "min_required": rules.min_per_axis,
            "status": "sufficient" if n >= rules.min_per_axis else "insufficient",
            "median_view_count": statistics.median(r["view_count"] for r in rows) if rows else None,
            # 참고용. 매칭 층이 아니다 — 분기 쏠림(드리프트)을 사람이 확인하는 데 쓴다
            "by_quarter": dict(sorted(Counter(_quarter(_ts(r["published_at"])) for r in rows).items())),
        }

    captured = [r["captured_at"] for r in chosen]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "canonical_definition": CANONICAL_DEFINITION,
        "rules": asdict(rules),
        "channel_id": channel_id,
        "boundary_published_before": _iso(bound),
        "window_start": _iso(window_start),
        "split": {"n": len(split_ids), "ids_sha256": ids_sha256(split_ids)},
        "input": {"uploads_n": len(uploads), "uploads_ids_sha256": ids_sha256(seen)},
        "exclusions": {k: excluded[k] for k in EXCLUSION_REASONS if excluded[k]},
        "reference_n": len(chosen),
        "strata": strata,
        "snapshot": {"captured_at_min": min(captured) if captured else None,
                     "captured_at_max": max(captured) if captured else None},
        "reference": chosen,
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def manifest_summary(manifest: dict) -> dict:
    """ID·조회수 없이 개수만. dry-run 출력용."""
    return {
        "rules_version": manifest["rules"]["rules_version"],
        "rules_status": manifest["rules"]["rules_status"],
        "boundary_published_before": manifest["boundary_published_before"],
        "window_start": manifest["window_start"],
        "uploads_n": manifest["input"]["uploads_n"],
        "split_n": manifest["split"]["n"],
        "reference_n": manifest["reference_n"],
        "exclusions": manifest["exclusions"],
        "strata": {a: {"n": s["n"], "status": s["status"], "by_quarter": s["by_quarter"]}
                   for a, s in manifest["strata"].items()},
        "manifest_sha256": manifest["manifest_sha256"],
    }


# --------------------------------------------------------------------------
# canonical view_multiple
# --------------------------------------------------------------------------

def _target_age(video: dict) -> float | None:
    age = video.get("age_days")
    if isinstance(age, (int, float)) and not isinstance(age, bool):
        return float(age)
    if video.get("captured_at") and video.get("published_at"):
        return (_ts(video["captured_at"]) - _ts(video["published_at"])).total_seconds() / 86400
    return None


def canonical_view_multiple(video: dict, manifest: dict, *, verify: bool = True) -> dict:
    """영상 하나의 canonical 조회 배수와 근거.

    정의 (view-multiple-reference-v0.1):
        대상 스냅샷 조회수 ÷ 동결 reference 중 같은 길이 축 영상들의 스냅샷 조회수 중앙값.
        대상도 reference 와 같은 성숙 기준(게시 후 maturity_days 이상)·live 제외를 통과해야 한다.
        축별 reference 가 min_per_axis 미만이면 값을 내지 않는다.

    값을 못 내면 None 과 status 를 남긴다. 0 이나 1 로 채우지 않는다.
    """
    if verify:
        verify_manifest(manifest)
    rules = ReferenceRules(**manifest["rules"])
    duration = video.get("duration_sec")
    axis = axis_of(duration, rules) if duration is not None else video.get("length_axis")
    age = _target_age(video)
    views = _views(video.get("view_count"))
    ref_ids = {r["video_id"] for r in manifest["reference"]}
    peers = [r["view_count"] for r in manifest["reference"] if r["length_axis"] == axis]
    median = statistics.median(peers) if peers else None

    if video.get("video_id") in ref_ids:
        status = "target_in_reference"
    elif _is_live(video, rules):
        status = "target_live_or_premiere"
    elif axis not in AXES:
        status = "target_axis_unknown"
    elif views is None:
        status = "target_views_missing"
    elif age is None:
        status = "target_age_unknown"
    elif age < rules.maturity_days:
        status = "target_not_matured"
    elif len(peers) < rules.min_per_axis:
        status = "reference_insufficient"
    elif not median or median <= 0:
        status = "reference_median_nonpositive"
    else:
        status = "available"

    value = views / median if status == "available" else None
    if status == "available":
        basis = (f"동결 reference({manifest['manifest_sha256'][:12]}) {axis} {len(peers)}편의 "
                 f"스냅샷 조회수 중앙값 {median:,.0f} 대비")
    else:
        basis = f"값 없음: {status} (축 {axis}, reference {len(peers)}편, 최소 {rules.min_per_axis})"
    return {
        "video_id": video.get("video_id"),
        "view_multiple": value,
        "status": status,
        "basis": basis,
        "definition": CANONICAL_DEFINITION,
        "canonical": True,
        "length_axis": axis,
        "target_view_count": views,
        "target_age_days": age,
        "maturity_days": rules.maturity_days,
        "reference_n": len(peers),
        "reference_median_views": median,
        "reference_manifest_sha256": manifest["manifest_sha256"],
        "reference_rules_version": rules.rules_version,
        "reference_rules_status": rules.rules_status,
        # 규칙이 사람 승인을 받기 전에는 final Finding 입력 자격이 없다
        "final_eligible": rules.rules_status == "approved",
    }
