"""댓글 표본 정책 테스트 — 합성 영상 메타만 쓴다. API·실데이터·댓글 원문 없음."""

import pathlib
import sys
import tempfile
from dataclasses import replace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients.youtube import QuotaExhausted  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.pipeline import comment_sampling as cs  # noqa: E402
from app.pipeline.observable_collect import (  # noqa: E402
    collect_planned, collect_sample, ensure_schema)


def synth(n=300, seed_types=("A", "B", "C", "D"), splits=True):
    """침착맨 모양의 합성 채널: 300편, Discovery 90 / Development 90 / Holdout 120."""
    out = []
    for i in range(n):
        split = ("discovery" if i % 10 < 3 else "development" if i % 10 < 6 else "holdout")
        out.append({
            "video_id": f"v{i:03d}",
            "split": split if splits else None,
            "type_code": seed_types[i % len(seed_types)],
            "length_axis": ("shorts", "standard", "long")[i % 3],
            "view_multiple": (i * 37 % 101) / 20,
            "comment_count": 50 + i * 13 % 900,
            "comments_disabled": 0,
            "is_live": 0,
        })
    return out


def policy(**kw):
    base = cs.SamplingPolicy(
        name="t", split_rules={"discovery": cs.SplitRule(cs.STRATIFIED, 30),
                               "development": cs.SplitRule(cs.CENSUS),
                               "holdout": cs.SplitRule(cs.BLIND, 24)},
        collect_cap=200, reply_threads=5, reply_pages=1, label_cap=80)
    return replace(base, **kw)


# ---------------------------------------------------------------- 자격·제외

def test_exclusion_reasons_and_every_video_gets_a_row():
    vs = synth(30)
    vs[0]["comments_disabled"] = 1
    vs[1]["is_live"] = 1
    vs[2]["comment_count"] = 5
    vs[3]["comment_count"] = None
    p = cs.plan(vs, policy())
    rows = p.by_id()
    assert len(p.decisions) == 30
    assert rows["v000"]["reason"] == "comments_disabled"
    assert rows["v001"]["reason"] == "live"
    assert rows["v002"]["reason"] == "below_comment_threshold"
    assert rows["v003"]["reason"] == "comment_count_unknown"
    for vid in ("v000", "v001", "v002", "v003"):
        assert rows[vid]["decision"] == cs.EXCLUDED
        assert rows[vid]["collect_cap"] == 0


def test_live_can_be_kept_when_policy_says_so():
    vs = synth(10)
    vs[5]["is_live"] = 1
    p = cs.plan(vs, policy(exclude_live=False))
    assert p.by_id()["v005"]["decision"] != cs.EXCLUDED


def test_census_takes_all_eligible_development():
    vs = synth()
    vs[3]["comments_disabled"] = 1          # v003 은 development
    p = cs.plan(vs, policy())
    dev = [d for d in p.decisions if d["split"] == "development"]
    assert len(dev) == 90
    chosen = [d for d in dev if d["decision"] == cs.SELECTED]
    assert len(chosen) == 89
    assert all(d["inclusion_prob"] == 1.0 for d in chosen)


def test_skip_rule_and_unlisted_split():
    vs = synth(20)
    pol = policy(split_rules={"development": cs.SplitRule(cs.CENSUS)})
    p = cs.plan(vs, pol)
    others = [d for d in p.decisions if d["split"] != "development"]
    assert others and all(d["decision"] == cs.NOT_SAMPLED for d in others)
    assert all(d["reason"] == "split_rule:skip" for d in others)


# ---------------------------------------------------------------- 층화·최소치

def test_stratified_hits_target_and_cell_minimums():
    vs = synth()
    p = cs.plan(vs, policy())
    disc = [d for d in p.selected() if d["split"] == "discovery"]
    assert len(disc) == 30
    cells = {d["cell"] for d in p.decisions if d["split"] == "discovery"}
    counts = {c: sum(d["cell"] == c for d in disc) for c in cells}
    # 4 유형 × 2 길이 묶음 = 8칸, 최소 2편씩
    assert len(cells) == 8
    assert min(counts.values()) >= 2
    assert not p.warnings


def test_each_tier_represented_inside_cell_when_slots_allow():
    vs = synth()
    p = cs.plan(vs, policy(split_rules={"discovery": cs.SplitRule(cs.STRATIFIED, 60)}))
    disc = p.selected()
    for cell in {d["cell"] for d in disc}:
        tiers_avail = {d["tier"] for d in p.decisions
                       if d["cell"] == cell and d["split"] == "discovery"
                       and d["decision"] != cs.EXCLUDED}
        k = sum(d["cell"] == cell for d in disc)
        if k >= len(tiers_avail):
            assert {d["tier"] for d in disc if d["cell"] == cell} == tiers_avail


def test_small_cell_takes_all_and_warns():
    vs = synth(90, splits=False)
    for v in vs:
        v["type_code"] = "BIG"
    vs[0]["type_code"] = "RARE"             # 한 편뿐인 칸
    pol = policy(split_rules={cs.ANY_SPLIT: cs.SplitRule(cs.STRATIFIED, 10)})
    p = cs.plan(vs, pol)
    assert p.by_id()["v000"]["decision"] == cs.SELECTED
    assert any("RARE" in w for w in p.warnings)


def test_minimums_exceeding_target_are_kept_and_reported():
    vs = synth(300, seed_types=tuple("ABCDEFGHIJ"), splits=False)
    pol = policy(split_rules={cs.ANY_SPLIT: cs.SplitRule(cs.STRATIFIED, 10)}, min_per_cell=2)
    p = cs.plan(vs, pol)
    assert len(p.selected()) == 40          # 10 유형 × 2 길이 × 2
    assert any("최소치" in w for w in p.warnings)


def test_inclusion_prob_matches_stratum_share():
    p = cs.plan(synth(), policy())
    for d in p.decisions:
        if d["split"] != "discovery" or d["decision"] == cs.EXCLUDED:
            continue
        members = [x for x in p.decisions
                   if x["stratum"] == d["stratum"] and x["split"] == "discovery"
                   and x["decision"] != cs.EXCLUDED]
        chosen = sum(x["decision"] == cs.SELECTED for x in members)
        assert d["inclusion_prob"] == pytest.approx(chosen / len(members))


def test_apportion_minimum_proportional_and_monotone():
    sizes = {"a": 50, "b": 30, "c": 1, "d": 0}
    assert cs.apportion(sizes, 12, 2) == {"a": 7, "b": 4, "c": 1, "d": 0}
    prev = cs.apportion(sizes, 0, 2)
    for total in range(1, 82):
        cur = cs.apportion(sizes, total, 2)
        assert all(cur[k] >= prev[k] for k in sizes)
        assert all(cur[k] <= sizes[k] for k in sizes)
        prev = cur


def test_tiers_and_unknown_performance():
    vs = synth(30, splits=False)
    vs[4]["view_multiple"] = None
    pol = policy(split_rules={cs.ANY_SPLIT: cs.SplitRule(cs.STRATIFIED, 30)})
    p = cs.plan(vs, pol)
    assert p.by_id()["v004"]["tier"] == cs.UNKNOWN_TIER
    assert set(p.cutpoints) == {"shorts", "longform"}
    assert all(len(c) == 2 for c in p.cutpoints.values())
    assert {d["tier"] for d in p.decisions} <= {"t1", "t2", "t3", cs.UNKNOWN_TIER}


# ---------------------------------------------------------------- holdout 보호

def test_holdout_performance_never_changes_the_plan():
    a = synth()
    b = synth()
    for v in b:
        if v["split"] == "holdout":
            v["view_multiple"] = 1000.0 if int(v["video_id"][1:]) % 2 else None
    pa, pb = cs.plan(a, policy()), cs.plan(b, policy())
    assert pa.cutpoints == pb.cutpoints
    assert pa.decisions == pb.decisions
    assert all(d["tier"] == cs.BLIND_TIER for d in pa.decisions if d["split"] == "holdout")


def test_holdout_blind_is_type_length_only():
    p = cs.plan(synth(), policy())
    hold = [d for d in p.selected() if d["split"] == "holdout"]
    assert len(hold) == 24
    assert all(d["stratum"].endswith("|blind") for d in hold)


def test_stratified_holdout_rule_is_rejected():
    pol = policy(split_rules={"holdout": cs.SplitRule(cs.STRATIFIED, 10)})
    with pytest.raises(ValueError):
        cs.plan(synth(), pol)


def test_split_is_never_rewritten():
    vs = synth()
    before = [(v["video_id"], v["split"]) for v in vs]
    p = cs.plan(vs, policy())
    assert [(v["video_id"], v["split"]) for v in vs] == before
    assert [(d["video_id"], d["split"]) for d in p.decisions] == before


# ---------------------------------------------------------------- 결정성

def test_deterministic_and_order_independent():
    vs = synth()
    p1 = cs.plan(vs, policy())
    p2 = cs.plan(list(reversed(vs)), policy())
    assert {d["video_id"] for d in p1.selected()} == {d["video_id"] for d in p2.selected()}
    assert p1.by_id() == p2.by_id()


def test_seed_changes_selection():
    vs = synth()
    a = {d["video_id"] for d in cs.plan(vs, policy(seed=1)).selected()}
    b = {d["video_id"] for d in cs.plan(vs, policy(seed=2)).selected()}
    assert a != b


def test_duplicate_ids_rejected():
    vs = synth(3)
    vs[2]["video_id"] = vs[0]["video_id"]
    with pytest.raises(ValueError):
        cs.plan(vs, policy())


def test_label_subset_deterministic_and_bounded():
    ids = [f"c{i}" for i in range(250)]
    a = cs.label_subset(ids, 100, 42, "v1")
    assert a == cs.label_subset(list(reversed(ids)), 100, 42, "v1")
    assert len(a) == 100 and set(a) <= set(ids)
    assert a != cs.label_subset(ids, 100, 42, "v2")
    assert cs.label_subset(ids[:30], 100, 42, "v1") == sorted(ids[:30])


# ---------------------------------------------------------------- 프리셋·예산

def test_presets_validate_and_standard_counts():
    for name in cs.PRESETS:
        cs.PRESETS[name].validate()
    p = cs.plan(synth(), cs.preset("standard"))
    by_split = {}
    for d in p.selected():
        by_split[d["split"]] = by_split.get(d["split"], 0) + 1
    assert by_split == {"development": 90, "discovery": 45, "holdout": 60}


def test_estimate_upper_bound_arithmetic():
    vs = synth(10, splits=False)
    for v in vs:
        v["comment_count"] = 1000
    vs[0]["comment_count"] = 150            # 2페이지, 판정 100
    pol = cs.SamplingPolicy(name="e", split_rules={cs.ANY_SPLIT: cs.SplitRule(cs.CENSUS)},
                            collect_cap=500, reply_threads=20, reply_pages=1, label_cap=100)
    e = cs.estimate(cs.plan(vs, pol), metadata_videos=300,
                    price_per_mtok=(2.0, 10.0))
    assert e["units_top_pages"] == 9 * 5 + 2
    assert e["units_replies_max"] == 10 * 20
    assert e["units_metadata"] == 6
    assert e["labeled_comments"] == 10 * 100
    # 1000 × (165×2 + 80×10) / 1e6 = 1.13
    assert e["cost_usd_sync"] == pytest.approx(1.13)
    assert e["cost_usd_batch"] == pytest.approx(0.565, abs=0.01)


# ---------------------------------------------------------------- 수집 연결

class FakeYT:
    """commentThreads 3페이지(페이지당 2 thread), thread 마다 답글 1개."""

    def __init__(self, quota_after=None):
        self.units_used = 0
        self.quota_after = quota_after
        self.orders = []

    def _get(self, endpoint, **kw):
        if self.quota_after is not None and self.units_used >= self.quota_after:
            raise QuotaExhausted("fake")
        self.units_used += 1
        if endpoint == "commentThreads":
            self.orders.append(kw["order"])
            page = int(kw.get("pageToken", "0"))
            vid = kw["videoId"]
            items = [{"id": f"{vid}-t{page}{j}", "snippet": {
                "topLevelComment": {"id": f"{vid}-c{page}{j}", "snippet": {"textOriginal": "x"}},
                "totalReplyCount": 1}} for j in range(2)]
            body = {"items": items}
            if page < 2:
                body["nextPageToken"] = str(page + 1)
            return body
        return {"items": [{"id": kw["parentId"] + "-r", "snippet": {"textOriginal": "y"}}]}


def test_collect_sample_defaults_unchanged():
    with tempfile.TemporaryDirectory() as t:
        c = connect(pathlib.Path(t) / "t.db")
        ensure_schema(c)
        yt = FakeYT()
        collect_sample(c, yt, "r", "v")
        assert yt.orders == ["time"]
        assert c.execute("select top_count, status from observation_collection").fetchone()[:] == (2, "capped")
        assert {r[0] for r in c.execute("select status from observation_threads")} == {"complete"}
        c.close()


def test_collect_sample_pages_and_reply_thread_cap():
    with tempfile.TemporaryDirectory() as t:
        c = connect(pathlib.Path(t) / "t.db")
        ensure_schema(c)
        yt = FakeYT()
        collect_sample(c, yt, "r", "v", 1, top_pages=5, max_reply_threads=2)
        row = c.execute("select top_count, status, next_page_token from observation_collection").fetchone()
        assert tuple(row) == (6, "complete", None)
        states = [r[0] for r in c.execute("select status from observation_threads order by top_id")]
        assert states.count("complete") == 2 and states.count("replies_not_fetched") == 4
        assert yt.units_used == 3 + 2
        c.close()


def test_collect_planned_records_provenance_and_resumes():
    vs = synth(20, splits=False)
    pol = cs.SamplingPolicy(name="p", split_rules={cs.ANY_SPLIT: cs.SplitRule(cs.STRATIFIED, 4)},
                            collect_cap=200, reply_threads=1, reply_pages=1, label_cap=50,
                            min_per_cell=0)
    p = cs.plan(vs, pol)
    chosen = [d["video_id"] for d in p.selected()]
    assert len(chosen) == 4
    with tempfile.TemporaryDirectory() as t:
        c = connect(pathlib.Path(t) / "t.db")
        ensure_schema(c)
        # 한 영상 = 원댓글 2페이지 + 답글 1회 = 3유닛. 두 번째 영상 중간에 할당량 소진
        with pytest.raises(QuotaExhausted):
            collect_planned(c, FakeYT(quota_after=4), "run", p, log=lambda _: None)
        rows = {r["video_id"]: dict(r) for r in c.execute("select * from observation_sampling")}
        assert len(rows) == 20
        assert rows[chosen[0]]["completeness"] == "capped"
        assert rows[chosen[1]]["completeness"] == "error:QuotaExhausted"
        assert all(rows[v]["completeness"] == "pending" for v in chosen[2:])
        assert all(r["completeness"] == "not_sampled" for v, r in rows.items() if v not in chosen)
        assert rows[chosen[0]]["ordering"] == "time" and rows[chosen[0]]["collect_cap"] == 200
        assert rows[chosen[0]]["collected_at"]

        yt = FakeYT()
        collect_planned(c, yt, "run", p, log=lambda _: None)
        assert yt.units_used == 3 * 3        # 첫 영상은 건너뜀
        rows = {r["video_id"]: dict(r) for r in c.execute("select * from observation_sampling")}
        assert all(rows[v]["completeness"] == "capped" for v in chosen)
        assert c.execute("select status from observation_runs").fetchone()[0] == "complete"
        c.close()
