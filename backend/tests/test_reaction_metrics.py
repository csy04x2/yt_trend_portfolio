"""Reaction Stage 08 수치 — 합성 데이터만 쓴다 (댓글 원문 없음).

분석 대상 필터, 다중 라벨 비율, None·UNKNOWN 분리, 작은 표본 가림, 상태 표시,
유형·성과 층 묶음, 표본 설계 출처, DB 저장·읽기 전용 경로.
"""

import json
import pathlib
import sqlite3
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import connect  # noqa: E402
from app.pipeline import reaction_metrics as rm  # noqa: E402
from app.pipeline import reference  # noqa: E402

STATUS = "검증 전 AI 판정"


def _lab(cid, vid, reactions, targets, *, eligible=1, reason=None, owner=None, flag=False):
    return {"comment_id": cid, "video_id": vid, "reactions": reactions, "targets": targets,
            "review_flag": flag, "analysis_eligible": eligible, "exclusion_reason": reason,
            "author_is_channel_owner": owner}


def _spec(vid, spec, start=0):
    """spec: [(개수, reactions, targets)] → 합성 판정 행."""
    out, i = [], start
    for n, rs, ts in spec:
        for _ in range(n):
            out.append(_lab(f"{vid}-c{i}", vid, list(rs), list(ts)))
            i += 1
    return out


def _one(records, scope, key, axis):
    got = [r for r in records if r["scope"] == scope and r["group_key"] == key and r["length_axis"] == axis]
    assert len(got) == 1, (scope, key, axis, len(got))
    return got[0]


# --------------------------------------------------------------------------
# 분석 대상
# --------------------------------------------------------------------------

def test_is_audience_excludes_ineligible_and_own_channel():
    assert rm.is_audience({"analysis_eligible": 1})
    assert not rm.is_audience({"analysis_eligible": 0, "exclusion_reason": "spam_confirmed"})
    # 표시가 어긋난 옛 행도 채널 본인 댓글이면 뺀다
    assert not rm.is_audience({"analysis_eligible": 1, "exclusion_reason": "own_channel"})
    assert not rm.is_audience({"analysis_eligible": 1, "author_is_channel_owner": 1})
    assert not rm.is_audience({"analysis_eligible": None})


def test_compute_counts_only_eligible_comments():
    labels = _spec("v1", [(10, ["R1"], ["T2"])])
    labels += [_lab("x1", "v1", ["R4"], ["T3"], eligible=0, reason="spam_confirmed"),
               _lab("x2", "v1", ["R4"], ["T3"], eligible=0, reason="own_channel", owner=1),
               _lab("x3", "v1", ["R4"], ["T3"], eligible=1, owner=1),
               _lab("x4", "other", ["R4"], ["T3"])]          # 다른 채널 영상
    recs = rm.compute(labels, {"v1": {"length_axis": "standard"}}, prompt_version="p", model="m",
                      eligible_counts={"v1": 12})
    ch = _one(recs, "channel", "channel", "all")
    assert ch["n_comments"] == 10
    assert ch["reaction_counts"]["R4"] == 0
    assert ch["reaction_shares"]["R1"] == 1.0
    assert ch["labeled_ratio"] == pytest.approx(10 / 12)


# --------------------------------------------------------------------------
# 비율
# --------------------------------------------------------------------------

def test_multilabel_shares_none_and_unknown_are_separate():
    labels = _spec("v1", [(4, ["R1", "R7"], ["T2", "T3"]), (3, ["R7"], ["T2"]),
                          (2, [], []), (1, ["UNKNOWN"], ["UNKNOWN"])])
    r = rm.rollup(labels, n_eligible=10, n_videos=1)
    assert r["n_comments"] == 10
    assert r["reaction_shares"]["R1"] == pytest.approx(0.4)
    assert r["reaction_shares"]["R7"] == pytest.approx(0.7)
    assert sum(v for v in r["reaction_shares"].values()) > 1, "다중 라벨이라 합이 1을 넘어야 한다"
    assert r["none_count"] == 2 and r["none_share"] == pytest.approx(0.2)
    assert r["unknown_count"] == 1 and r["unknown_share"] == pytest.approx(0.1)
    assert "UNKNOWN" not in r["reaction_counts"] and "None" not in r["reaction_counts"]
    assert r["multi_reaction_count"] == 4
    assert r["target_shares"]["T2"] == pytest.approx(0.7)
    assert r["target_shares"]["T3"] == pytest.approx(0.4)
    assert r["target_shares"]["UNKNOWN"] == pytest.approx(0.1)
    assert r["no_target_count"] == 2
    assert set(r["reaction_shares"]) == {f"R{i}" for i in range(1, 11)}
    assert set(r["target_shares"]) == {"T1", "T2", "T3", "T4", "T5", "UNKNOWN"}


def test_small_sample_masks_shares_but_keeps_counts():
    labels = _spec("v1", [(9, ["R3"], ["T1"])])
    r = rm.rollup(labels, n_eligible=9, n_videos=1)
    assert r["masked"] is True
    assert r["reaction_counts"]["R3"] == 9
    assert all(v is None for v in r["reaction_shares"].values())
    assert all(v is None for v in r["target_shares"].values())
    assert r["none_share"] is None and r["unknown_share"] is None
    assert "최소 10건" in r["basis"]
    r10 = rm.rollup(_spec("v1", [(10, ["R3"], ["T1"])]), n_eligible=10, n_videos=1)
    assert r10["masked"] is False and r10["reaction_shares"]["R3"] == 1.0


def test_unknown_code_in_table_is_not_silently_counted():
    with pytest.raises(ValueError):
        rm.rollup([_lab("a", "v", ["R11"], ["T2"])], n_eligible=1, n_videos=1)


def test_every_record_carries_validation_status():
    recs = rm.compute(_spec("v1", [(12, ["R1"], ["T1"])]), {"v1": {"length_axis": "shorts"}},
                      prompt_version="p", model="m")
    assert recs and all(r["validation_status"] == STATUS for r in recs)
    assert all(r["metrics_version"] == rm.METRICS_VERSION for r in recs)


def test_no_labels_no_rows():
    assert rm.compute([], {"v1": {"length_axis": "shorts"}}, prompt_version="p", model="m") == []


# --------------------------------------------------------------------------
# 묶음 — 유형 · 성과 층 · 길이
# --------------------------------------------------------------------------

def _two_types():
    videos, labels, types, perf = {}, [], {}, {}
    for i in range(6):
        vid = f"a{i}"
        videos[vid] = {"length_axis": "shorts" if i < 3 else "long"}
        types[vid] = "A"
        perf[vid] = 2.0 + i
        labels += _spec(vid, [(6, ["R7"], ["T2"]), (4, ["R1"], ["T1"])])
    for i in range(6):
        vid = f"b{i}"
        videos[vid] = {"length_axis": "standard"}
        types[vid] = "B"
        perf[vid] = 0.1 * (i + 1)
        labels += _spec(vid, [(3, ["R7"], ["T2"]), (7, [], [])])
    videos["untyped"] = {"length_axis": "standard"}
    labels += _spec("untyped", [(10, ["R4"], ["T5"])])
    return videos, labels, types, perf


def test_type_and_length_axes_recount_comments():
    videos, labels, types, perf = _two_types()
    recs = rm.compute(labels, videos, prompt_version="p", model="m",
                      type_maps=[{"taxonomy_id": 7, "axis": "topic", "labels": types}])
    a_all = _one(recs, "type", "A", "all")
    assert a_all["taxonomy_id"] == 7 and a_all["n_videos"] == 6 and a_all["n_comments"] == 60
    assert a_all["reaction_shares"]["R7"] == pytest.approx(0.6)
    a_sh = _one(recs, "type", "A", "shorts")
    assert a_sh["n_videos"] == 3
    b_long = _one(recs, "type", "B", "longform")     # standard → longform 묶음
    assert b_long["none_share"] == pytest.approx(0.7)
    assert not [r for r in recs if r["scope"] == "type" and r["group_key"] == "untyped"]
    ch = _one(recs, "channel", "channel", "all")
    assert ch["n_comments"] == 130 and ch["n_videos"] == 13
    assert _one(recs, "video", "a0", "shorts")["n_comments"] == 10


def test_tiers_use_provisional_performance_meta():
    videos, labels, types, perf = _two_types()
    recs = rm.compute(labels, videos, prompt_version="p", model="m",
                      performance={"values": perf, "meta": {"canonical": False,
                                                            "canonical_status": "provisional_legacy"}})
    tiers = [r for r in recs if r["scope"] == "tier"]
    assert tiers
    assert {r["group_key"] for r in tiers} <= {"t1", "t2", "t3", "unknown"}
    assert _one(recs, "tier", "unknown", "longform")["n_videos"] == 1      # 성과값 없는 영상
    meta = tiers[0]["performance"]
    assert meta["canonical"] is False and meta["n_tiers"] == 3 and "cutpoints" in meta
    assert sum(r["n_comments"] for r in tiers if r["length_axis"] == "all") == 130


def test_tier_cutpoints_nearest_rank():
    cuts = rm.tier_cutpoints({f"v{i}": float(i) for i in range(1, 10)},
                             {f"v{i}": "shorts" for i in range(1, 10)})
    assert cuts == {"shorts": [3.0, 6.0]}
    assert rm.tier_of(3.0, cuts["shorts"]) == "t1"
    assert rm.tier_of(6.5, cuts["shorts"]) == "t3"
    assert rm.tier_of(None, cuts["shorts"]) == "unknown"


def test_sampling_provenance_recorded_but_not_weighted():
    labels = _spec("v1", [(10, ["R1"], ["T1"])]) + _spec("v2", [(10, ["R2"], ["T3"])])
    videos = {"v1": {"length_axis": "shorts"}, "v2": {"length_axis": "shorts"}}
    sampling = {"run_id": "s1", "rows": {"v1": {"decision": "selected", "inclusion_prob": 0.5,
                                                 "completeness": "capped", "policy_version": "comment-sampling-v0.1",
                                                 "ordering": "time", "label_cap": 100}}}
    ch = _one(rm.compute(labels, videos, prompt_version="p", model="m", sampling=sampling),
              "channel", "channel", "all")
    s = ch["sampling"]
    assert s["weighted"] is False and s["source"] == "observation_sampling"
    assert s["videos_with_row"] == 1 and s["videos_without_row"] == 1
    assert s["completeness"] == {"capped": 1} and s["inclusion_prob_min"] == 0.5
    ch2 = _one(rm.compute(labels, videos, prompt_version="p", model="m"), "channel", "channel", "all")
    assert ch2["sampling"]["source"] is None and ch2["sampling"]["weighted"] is False
    # 비가중 — 포함 확률이 달라도 비율은 같다
    assert ch["reaction_shares"] == ch2["reaction_shares"]


# --------------------------------------------------------------------------
# DB
# --------------------------------------------------------------------------

def _db(tmp: pathlib.Path):
    c = connect(tmp / "t.db")
    c.execute("INSERT INTO channels VALUES ('ch','u',NULL,'합성채널','pl',NULL,'2026-01-01',NULL)")
    c.execute("INSERT INTO channels VALUES ('ch2','u2',NULL,'다른채널','pl2',NULL,'2026-01-01',NULL)")
    for vid, ch, axis in (("v1", "ch", "shorts"), ("v2", "ch", "long"), ("w1", "ch2", "shorts")):
        c.execute("""INSERT INTO videos (video_id, channel_id, title, duration_sec, published_at,
                     first_seen_at, length_axis) VALUES (?,?,?,?,?,?,?)""",
                  (vid, ch, "합성 영상", 60 if axis == "shorts" else 2000,
                   "2026-01-01T00:00:00Z", "2026-01-01", axis))
    n = 0
    for vid, k in (("v1", 12), ("v2", 12), ("w1", 12)):
        for i in range(k):
            cid = f"{vid}-{i}"
            c.execute("""INSERT INTO comments (comment_id, video_id, text, published_at, fetched_at)
                         VALUES (?,?,?,?,?)""", (cid, vid, "합성", "2026-01-02", "2026-01-03"))
            reactions = ["R1", "R7"] if i % 2 == 0 else []
            targets = ["T2"] if reactions else []
            c.execute("""INSERT INTO comment_reactions (comment_id, prompt_version, model,
                         reactions_json, targets_json, labeled_at) VALUES (?,?,?,?,?,?)""",
                      (cid, "reaction-v1", "m1", json.dumps(reactions), json.dumps(targets), "2026-01-04"))
            n += 1
    # 제외 표시: 채널 본인 1건, 확정 스팸 1건 (둘 다 판정은 있다)
    c.execute("UPDATE comments SET analysis_eligible=0, exclusion_reason='own_channel', "
              "author_is_channel_owner=1 WHERE comment_id='v1-0'")
    c.execute("UPDATE comments SET analysis_eligible=0, exclusion_reason='spam_confirmed' "
              "WHERE comment_id='v1-2'")
    # 다른 (버전, 모델) 판정 — 섞이면 안 된다
    c.execute("""INSERT INTO comment_reactions (comment_id, prompt_version, model, reactions_json,
                 targets_json, labeled_at) VALUES ('v1-1','reaction-v0','m0','["R4"]','["T3"]','2025-01-01')""")
    tid = c.execute("""INSERT INTO video_taxonomies (channel_id, axis, version, source, types_json, created_at)
                       VALUES ('ch','topic',1,'user','{"A":"가형"}','2026-01-01')""").lastrowid
    for vid in ("v1", "v2"):
        c.execute("""INSERT INTO video_type_labels (video_id, taxonomy_id, prompt_version, model,
                     type_code, labeled_at) VALUES (?,?,?,?,?,?)""", (vid, tid, "t", "m", "A", "2026-01-01"))
    c.execute("""INSERT INTO video_metrics (video_id, run_id, length_axis, view_multiple, computed_at)
                 VALUES ('v1','r1','shorts',2.0,'2026-01-05'), ('v2','r1','long',NULL,'2026-01-05')""")
    return c


def test_db_run_persists_rows_with_status_and_filters():
    with tempfile.TemporaryDirectory() as t:
        c = _db(pathlib.Path(t))
        recs = rm.run(c, "ch", "run1", prompt_version="reaction-v1", model="m1")
        ch = _one(recs, "channel", "channel", "all")
        assert ch["n_comments"] == 22, "제외 2건과 다른 채널 12건은 빠져야 한다"
        assert ch["n_eligible_comments"] == 22
        assert ch["reaction_counts"]["R4"] == 0, "다른 버전의 판정이 섞였다"
        v1 = _one(recs, "video", "v1", "shorts")
        assert v1["n_comments"] == 10 and v1["reaction_counts"]["R1"] == 4
        assert _one(recs, "type", "A", "all")["n_videos"] == 2
        assert _one(recs, "tier", "unknown", "longform")["performance"]["canonical"] is False

        rows = c.execute("SELECT * FROM reaction_metrics WHERE run_id='run1'").fetchall()
        assert len(rows) == len(recs)
        assert {r["validation_status"] for r in rows} == {STATUS}
        assert "text" not in rows[0].keys() and "rationale" not in rows[0].keys()
        r = [x for x in rows if x["scope"] == "channel" and x["length_axis"] == "all"][0]
        shares = json.loads(r["reaction_shares_json"])
        assert json.loads(r["reaction_counts_json"])["R1"] == 10
        assert shares["R1"] == pytest.approx(10 / 22)
        # 같은 실행을 다시 돌려도 덮어쓰기만 된다
        rm.run(c, "ch", "run1", prompt_version="reaction-v1", model="m1")
        assert c.execute("SELECT COUNT(*) FROM reaction_metrics WHERE run_id='run1'").fetchone()[0] == len(recs)
        c.close()


def test_versions_are_not_mixed_when_unspecified():
    with tempfile.TemporaryDirectory() as t:
        c = _db(pathlib.Path(t))
        recs = rm.collect(c, "ch")
        assert {(r["prompt_version"], r["model"]) for r in recs} == {("reaction-v1", "m1"), ("reaction-v0", "m0")}
        old = _one([r for r in recs if r["model"] == "m0"], "channel", "channel", "all")
        assert old["n_comments"] == 1 and old["masked"] is True
        c.close()


def test_readonly_connection_without_reaction_table_is_empty():
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t) / "old.db"
        raw = sqlite3.connect(p)
        raw.execute("CREATE TABLE channels (channel_id TEXT)")
        raw.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, length_axis TEXT)")
        raw.execute("CREATE TABLE comments (comment_id TEXT, video_id TEXT)")
        raw.commit()
        raw.close()
        ro = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
        assert rm.label_versions(ro) == []
        assert rm.collect(ro, "ch") == []
        ro.close()


def _manifest():
    uploads = []
    for i in range(6):
        uploads.append({"video_id": f"ref{i}", "channel_id": "ch", "published_at": f"2025-0{1 + i % 6}-01T00:00:00Z",
                        "duration_sec": 60, "view_count": 100, "captured_at": "2026-06-01T00:00:00Z"})
    uploads.append({"video_id": "v1", "channel_id": "ch", "published_at": "2026-01-01T00:00:00Z",
                    "duration_sec": 60, "view_count": 1, "captured_at": "2026-06-01T00:00:00Z"})
    rules = reference.ReferenceRules(min_per_axis=3, maturity_days=30)
    return reference.select_reference(uploads, {"v1", "v2"}, channel_id="ch",
                                      boundary="2026-01-01T00:00:00Z", rules=rules)


def test_canonical_performance_only_with_manifest():
    with tempfile.TemporaryDirectory() as t:
        c = _db(pathlib.Path(t))
        c.execute("""INSERT INTO video_stats_snapshots (video_id, run_id, captured_at, view_count)
                     VALUES ('v1','s','2026-06-01T00:00:00Z',300)""")
        m = _manifest()
        perf = rm.read_performance(c, "ch", m)
        assert perf["meta"]["canonical"] is True
        assert perf["meta"]["reference_manifest_sha256"] == m["manifest_sha256"]
        assert perf["meta"]["final_eligible"] is False           # 규칙이 proposal
        assert perf["values"]["v1"] == pytest.approx(3.0)
        assert perf["values"]["v2"] is None                       # long 축 reference 부족
        legacy = rm.read_performance(c, "ch")
        assert legacy["meta"]["canonical"] is False and legacy["values"]["v1"] == 2.0
        bad = dict(m, reference_n=999)
        with pytest.raises(ValueError):
            rm.read_performance(c, "ch", bad)
        c.close()
