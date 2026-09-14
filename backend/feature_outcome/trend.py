"""게시 월 코호트별 중앙값 — 전체와 급등 영상 제외. 시계열이 아니다(스냅샷 1회). age_days 있으면 views/day도."""
import statistics as st
from collections import defaultdict


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def monthly_cohorts(videos, flags):
    groups = defaultdict(list)
    for v in videos:
        groups[(v["length_axis"], v["published_at"][:7])].append(v)
    rows = []
    for (axis, month), vs in sorted(groups.items()):
        ex = [v for v in vs if not flags[v["video_id"]]["breakout"]]

        def stat(sub, key):
            return _med([v.get(key) for v in sub])

        def vpd(sub):
            return _med([v["view_count"] / v["age_days"] for v in sub if v.get("age_days")])

        rows.append({
            "axis": axis, "month": month,
            "n_all": len(vs), "n_ex": len(ex),
            "views_all": stat(vs, "view_count"), "views_ex": stat(ex, "view_count"),
            "like_rate_all": stat(vs, "like_rate"), "like_rate_ex": stat(ex, "like_rate"),
            "comment_rate_all": stat(vs, "comment_rate"), "comment_rate_ex": stat(ex, "comment_rate"),
            "vpd_all": vpd(vs), "vpd_ex": vpd(ex),
        })
    return rows
