"""급등 영상(breakout) 표시. 삭제하지 않는다 — 표시하고, 분석은 전체/제외 두 판을 낸다.

규칙 셋. 어느 하나라도 걸리면 breakout=1.
- rule_iqr      같은 (길이축, 게시 분기) 안에서 view_count > Q3 + k·IQR (기본 k=3, 그룹 n≥4)
- rule_multiple view_multiple ≥ multiple_min (기본 3)
- rule_event    events.json — 제목 정규식, 또는 (축, 날짜 창, 최소 배수) 창. 사람이 적는 사건 묶음
"""
import re
import statistics as st
from collections import defaultdict


def quarter_key(v):
    m = int(v["published_at"][5:7])
    return f"{v['published_at'][:4]}Q{(m - 1) // 3 + 1}"


def _quartiles(xs):
    xs = sorted(xs)
    n = len(xs)

    def q(p):
        pos = (n - 1) * p
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

    return q(0.25), q(0.75)


def flag_breakouts(videos, k_iqr=3.0, multiple_min=3.0, events=None, min_group=4):
    groups = defaultdict(list)
    for v in videos:
        groups[(v["length_axis"], quarter_key(v))].append(v)
    thr = {}
    for g, vs in groups.items():
        if len(vs) >= min_group:
            q1, q3 = _quartiles([v["view_count"] for v in vs])
            thr[g] = q3 + k_iqr * (q3 - q1)
    ev = events or {}
    pat = re.compile(ev["title_regex"]) if ev.get("title_regex") else None
    out = {}
    for v in videos:
        g = (v["length_axis"], quarter_key(v))
        r_iqr = int(g in thr and v["view_count"] > thr[g])
        vm = v.get("view_multiple")
        r_mul = int(vm is not None and vm >= multiple_min)
        r_ev = int(bool(pat and pat.search(v.get("title") or "")))
        for w in ev.get("windows", []):
            same_axis = v["length_axis"] == w.get("axis", v["length_axis"])
            in_win = w["start"] <= v["published_at"][:10] <= w["end"]
            if same_axis and in_win and vm is not None and vm >= w.get("min_multiple", multiple_min):
                r_ev = 1
        out[v["video_id"]] = {
            "rule_iqr": r_iqr,
            "rule_multiple": r_mul,
            "rule_event": r_ev,
            "breakout": int(r_iqr or r_mul or r_ev),
        }
    return out


def recompute_multiples(videos, flags, min_peers=5):
    """같은 (축, 분기) 동료 중앙값 대비 배수. 자기 자신과 급등 영상을 분모에서 뺀다.

    동료가 min_peers 미만이면 None — 숫자를 만들지 않고 이유를 남기는 저장소 원칙.
    """
    groups = defaultdict(list)
    for v in videos:
        groups[(v["length_axis"], quarter_key(v))].append(v)
    out = {}
    for v in videos:
        peers = [
            p["view_count"]
            for p in groups[(v["length_axis"], quarter_key(v))]
            if p["video_id"] != v["video_id"] and not flags[p["video_id"]]["breakout"]
        ]
        m = st.median(peers) if len(peers) >= min_peers else None
        out[v["video_id"]] = v["view_count"] / m if m else None
    return out


def breakouts_in_split(flags, split):
    """분할별 급등 영상 ID. discovery에 들어 있으면 패킷을 다시 잘라야 한다."""
    out = defaultdict(list)
    for vid, f in flags.items():
        if f["breakout"]:
            out[split.get(vid, "unsplit")].append(vid)
    return dict(out)
