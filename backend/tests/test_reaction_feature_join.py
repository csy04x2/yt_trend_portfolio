"""Reaction × Content Feature × 상대 성과 결합 분석 테스트.

합성 데이터만 쓴다. 댓글 문장은 이 파일에서 지어낸 표식 문자열이고, 실제 수집
댓글·실제 DB·유료 API 를 건드리지 않는다.
"""
import copy
import csv
import json
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from feature_outcome import frozen, reaction_join as rj, runner  # noqa: E402
from feature_outcome import reaction_profile as rprof  # noqa: E402
from feature_outcome.finding import AUDIENCE_METRICS, OBSERVATION_QUALITY_METRICS, build_findings  # noqa: E402
from feature_outcome.outcome import HoldoutSealed  # noqa: E402
from test_finding_engine import data as engine_data, frozen_registry  # noqa: E402

PV, MODEL = "reaction-v1", "synthetic-model"
SECRET = "합성원문표식"  # 보고서에 절대 나오면 안 되는 문자열
RATIONALE = "합성근거표식"


def c(vid, i, reactions, targets=None, *, eligible=1, parent=None, review=False, owner=None, reason=None):
    return {"video_id": vid, "comment_id": f"{vid}-c{i}", "parent_id": parent, "analysis_eligible": eligible,
            "reactions": reactions, "targets": targets if targets is not None else ([] if reactions is None else
                                                                                   (["T2"] if reactions else [])),
            "review_flag": review, "author_is_channel_owner": owner,
            "exclusion_reason": reason}


# ------------------------------------------------------------------ 프로필 계산

def test_profile_math_multi_label_none_unknown_and_target_denominator():
    rows = [c("v", 0, ["R1", "R7"], ["T2"]), c("v", 1, ["R1"], ["T3", "T4"]), c("v", 2, []),
            c("v", 3, ["UNKNOWN"], ["UNKNOWN"]), c("v", 4, ["R4"], ["UNKNOWN"], review=True),
            c("v", 5, None)]  # 판정 없음
    p = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL, min_labeled=5)
    assert p["status"] == "available" and p["reason"] is None
    assert (p["eligible_n"], p["n_labeled"], p["reacting_n"]) == (6, 5, 3)
    assert p["label_coverage"] == pytest.approx(5 / 6)
    s = p["shares"]
    assert s["reaction_share_R1"] == pytest.approx(2 / 5)
    assert s["reaction_share_R7"] == pytest.approx(1 / 5) and s["reaction_share_R4"] == pytest.approx(1 / 5)
    assert s["reaction_share_R2"] == 0
    assert s["reaction_none_share"] == pytest.approx(1 / 5)
    assert s["reaction_unknown_share"] == pytest.approx(1 / 5)
    # Target 분모 = 전체 판정 eligible 5건. None·UNKNOWN도 분모에 포함한다.
    assert s["reaction_target_share_T2"] == pytest.approx(1 / 5)
    assert s["reaction_target_share_T3"] == pytest.approx(1 / 5)
    assert s["reaction_target_unknown_share"] == pytest.approx(2 / 5)
    assert p["review_flag_share"] == pytest.approx(1 / 5)
    assert p["validation_status"] == "검증 전 AI 판정" and p["mvp_input_eligible"] is False
    assert set(s) == set(rprof.SHARE_KEYS) and all(k.startswith("reaction_") for k in s)


def test_eligibility_filter_uses_only_confirmed_eligible_comments():
    rows = [c("v", i, ["R1"]) for i in range(3)]
    rows += [c("v", 10, ["R4"], eligible=0), c("v", 11, ["R4"], eligible=None),
             c("v", 12, ["R4"], eligible="1"), c("v", 13, ["R4"], eligible=False)]
    p = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL, min_labeled=1)
    assert (p["eligible_n"], p["n_labeled"], p["ineligible_labeled_n"]) == (3, 3, 4)
    assert p["shares"]["reaction_share_R1"] == 1 and p["shares"]["reaction_share_R4"] == 0


def test_owner_comment_is_excluded_even_if_analysis_eligible():
    rows = [c("v", 0, ["R1"]), c("v", 1, ["R4"], owner=True),
            c("v", 2, ["R4"], reason="own_channel")]
    p = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL, min_labeled=1)
    assert p["eligible_n"] == 1 and p["n_labeled"] == 1
    assert p["ineligible_labeled_n"] == 2
    assert p["shares"]["reaction_share_R1"] == 1
    assert p["shares"]["reaction_share_R4"] == 0


def test_replies_excluded_by_default_and_opt_in():
    rows = [c("v", 0, ["R1"]), c("v", 1, ["R3"], parent="v-c0")]
    top = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL, min_labeled=1)
    both = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL, min_labeled=1, include_replies=True)
    assert top["n_labeled"] == 1 and top["label_unit"] == "top_level"
    assert both["n_labeled"] == 2 and both["shares"]["reaction_share_R3"] == 0.5


@pytest.mark.parametrize("rows,status", [
    ([], "no_eligible_comments"),
    ([c("v", 0, ["R1"], eligible=0)], "no_eligible_comments"),
    ([c("v", 0, None), c("v", 1, None)], "no_reaction_labels"),
    ([c("v", i, ["R1"]) for i in range(29)], "insufficient_labeled_n"),
])
def test_missing_and_low_n_give_null_shares_with_reason(rows, status):
    p = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL)
    assert p["status"] == status and p["reason"]
    assert all(v is None for v in p["shares"].values())
    assert p["min_labeled"] == rprof.MIN_LABELED_PER_VIDEO == 30


def test_exactly_min_n_is_available_and_invalid_labels_are_dropped():
    rows = [c("v", i, ["R1"]) for i in range(30)]
    rows += [c("v", 90, ["R11"]), c("v", 91, ["R1"], []), c("v", 92, ["UNKNOWN", "R1"])]
    p = rprof.build_profile("v", rows, prompt_version=PV, model=MODEL)
    assert p["status"] == "available" and p["n_labeled"] == 30 and p["invalid_label_n"] == 3


def test_no_reacting_comments_keeps_target_prevalence_zero():
    p = rprof.build_profile("v", [c("v", 0, []), c("v", 1, [])], prompt_version=PV, model=MODEL, min_labeled=1)
    assert p["shares"]["reaction_none_share"] == 1
    assert p["shares"]["reaction_target_share_T1"] == 0
    assert p["target_share_reason"] is None


def test_min_labeled_must_be_positive():
    with pytest.raises(ValueError):
        rprof.build_profile("v", [], prompt_version=PV, model=MODEL, min_labeled=0)


# ------------------------------------------------------------------ 합성 입력 파일

def make_db(path, comments, *, sampling=None, other_version=True):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE comments (comment_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, text TEXT NOT NULL,
            parent_id TEXT, analysis_eligible INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE comment_reactions (comment_id TEXT NOT NULL, prompt_version TEXT NOT NULL,
            model TEXT NOT NULL, reactions_json TEXT NOT NULL, targets_json TEXT NOT NULL,
            timestamps_json TEXT NOT NULL DEFAULT '[]', review_flag INTEGER NOT NULL DEFAULT 0,
            review_reason TEXT, rationale TEXT, labeled_at TEXT NOT NULL,
            PRIMARY KEY (comment_id, prompt_version, model));
        CREATE TABLE observation_sampling (run_id TEXT, video_id TEXT, split TEXT, decision TEXT, reason TEXT,
            completeness TEXT, inclusion_prob REAL, label_cap INTEGER, policy_name TEXT, policy_version TEXT,
            PRIMARY KEY (run_id, video_id));
    """)
    for x in comments:
        conn.execute("INSERT INTO comments VALUES (?,?,?,?,?)",
                     (x["comment_id"], x["video_id"], f"{SECRET} {x['comment_id']}", x["parent_id"],
                      x["analysis_eligible"]))
        if x["reactions"] is not None:
            conn.execute("INSERT INTO comment_reactions VALUES (?,?,?,?,?,'[\"1:23\"]',?,NULL,?,'t')",
                         (x["comment_id"], PV, MODEL, json.dumps(x["reactions"]), json.dumps(x["targets"]),
                          int(x["review_flag"]), RATIONALE))
            if other_version:  # 다른 버전 판정은 섞이면 안 된다 — 전부 R5 로 둔다
                conn.execute("INSERT INTO comment_reactions VALUES (?,?,?,'[\"R5\"]','[\"T1\"]','[]',0,NULL,?,'t')",
                             (x["comment_id"], "reaction-v0", MODEL, RATIONALE))
    for row in sampling or []:
        conn.execute("INSERT INTO observation_sampling VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()


def video_comments(vid, n, r1_n, *, ineligible=0, replies=0):
    out = [c(vid, i, ["R1"] if i < r1_n else ["R3"], ["T3"]) for i in range(n)]
    out += [c(vid, 100 + i, ["R4"], ["T1"], eligible=0) for i in range(ineligible)]
    out += [c(vid, 200 + i, ["R4"], ["T1"], parent=f"{vid}-c0") for i in range(replies)]
    return out


@pytest.fixture
def jcase(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    monkeypatch.setattr(rj, "OUTPUT_ROOT", root / "reaction-feature-join")
    monkeypatch.setattr(frozen, "OUTPUT_ROOT", root / "experiment-analysis")
    envelope = copy.deepcopy(frozen_registry()["_envelope"])
    envelope["registry"]["notice"] = "Synthetic"  # 파일 경로는 registry 스키마 검증을 거친다
    reg, ev, labels, split, db = [tmp_path / n for n in
                                  ("registry.json", "evidence.json", "labels.json", "split.csv", "d.db")]
    reg.write_text(json.dumps(envelope), encoding="utf-8")
    videos, labs, comments = [], {}, []
    for i in range(10):
        lab = "1" if i < 4 else "0" if i < 8 else "U"
        videos.append(dict(video_id=f"d{i}", title=SECRET, length_axis="shorts", duration_sec=45,
                           published_at="2026-01-01T00:00:00Z", view_count=100 * (i + 1), age_days=120,
                           view_multiple=(3.0 - i * 0.2), like_rate=None, comment_rate=None))
        labs[f"d{i}"] = {"f": lab}
        # R1 비율: d0 이 가장 높고 i 가 커질수록 낮다. d9 는 판정 5건뿐 (최소 n 미달)
        comments += video_comments(f"d{i}", 5 if i == 9 else 40, 40 - 4 * i if i < 9 else 5,
                                   ineligible=10, replies=3)
    videos += [dict(video_id="h", title=SECRET, length_axis="shorts", duration_sec=45, view_count=500,
                    age_days=120, view_multiple=1.0),
               dict(video_id="s", view_count="DO NOT AGGREGATE")]
    labs.update({"h": {"f": "1"}, "s": {"f": "U"}})
    comments += video_comments("h", 40, 40) + video_comments("s", 40, 40)
    ev.write_text(json.dumps({"channel": "synthetic", "videos": videos}), encoding="utf-8")
    labels.write_text(json.dumps({"labels": labs}), encoding="utf-8")
    with split.open("w", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(["video_id", "split", "seed", "created_at"])
        for v in videos:
            part = "holdout" if v["video_id"] == "h" else "discovery" if v["video_id"] == "s" else "development"
            w.writerow([v["video_id"], part, 42, "2026-01-01T00:00:00Z"])
    sampling = [("run1", f"d{i}", "development", "selected", None, "complete", 1.0, 100, "p", "comment-sampling-v0.1")
                for i in range(8)]
    sampling += [("run1", "d8", "development", "selected", None, "capped", 1.0, 100, "p", "v"),
                 ("run2", "d8", "development", "selected", None, "complete", 1.0, 100, "p", "v")]
    make_db(db, comments, sampling=sampling)
    out = rj.OUTPUT_ROOT / "run1"
    kw = dict(registry=reg, labels=labels, split=split, evidence=ev, db=db, prompt_version=PV, model=MODEL, out=out)
    argv = ["--registry", str(reg), "--labels", str(labels), "--split", str(split), "--evidence", str(ev),
            "--db", str(db), "--prompt-version", PV, "--model", MODEL, "--out", str(out)]
    return dict(kw=kw, argv=argv, out=out, root=root, tmp=tmp_path, videos=videos, db=db, ev=ev,
                reg=reg, labels=labels, split=split)


def read_report(out):
    text = (out / "reaction_join.json").read_text(encoding="utf-8")
    return text, json.loads(text)


# ------------------------------------------------------------------ 실행 전체

def test_development_run_joins_profiles_features_and_legacy_outcome(jcase):
    inputs = {k: jcase[k].read_bytes() for k in ("ev", "reg", "labels", "split", "db")}
    assert rj.main(jcase["argv"]) == 0
    assert {p.name for p in jcase["out"].iterdir()} == {"manifest.json", "reaction_join.json"}
    text, report = read_report(jcase["out"])
    assert report["validation_status"] == "검증 전 AI 판정" and report["mvp_input_eligible"] is False
    assert report["scope"]["split"] == "development" and report["thresholds_applied"] == []
    rows = {r["video_id"]: r for r in report["rows"]}
    assert set(rows) == {f"d{i}" for i in range(10)}  # holdout·discovery 없음
    for r in report["rows"]:
        assert r["validation_status"] == "검증 전 AI 판정" and r["mvp_input_eligible"] is False
        assert r["relative_performance"] == {"canonical": False, "status": "provisional_legacy",
                                             "canonical_value_status": None, "final_eligible": False}
        assert "title" not in r
    assert report["input_contract"]["relative_performance"]["canonical_status"] == "provisional_legacy"
    p0 = rows["d0"]["reaction_profile"]
    # 부적격 10건·답글 3건·다른 버전 판정(R5)은 빠진다
    assert (p0["eligible_n"], p0["n_labeled"], p0["ineligible_labeled_n"]) == (40, 40, 10)
    assert p0["shares"]["reaction_share_R1"] == 1 and p0["shares"]["reaction_share_R5"] == 0
    assert p0["shares"]["reaction_share_R4"] == 0
    assert rows["d3"]["reaction_profile"]["shares"]["reaction_share_R1"] == pytest.approx(28 / 40)
    assert rows["d9"]["reaction_profile"]["status"] == "insufficient_labeled_n"
    assert rows["d0"]["reaction_profile"]["sampling"]["completeness"] == "complete"
    assert rows["d8"]["reaction_profile"]["sampling"]["status"] == "ambiguous_multiple_runs"
    assert rows["d9"]["reaction_profile"]["sampling"] == {"status": "not_recorded"}
    rc = report["reaction_contract"]
    assert rc["profile_status_counts"] == {"available": 9, "insufficient_labeled_n": 1}
    assert {(v["prompt_version"], v["model"]) for v in rc["label_versions_in_db"]} == {(PV, MODEL), ("reaction-v0", MODEL)}

    calc = report["calculations"]
    fr = {x["metric"]: x for x in calc["feature_to_reaction"]}
    leg = fr["reaction_share_R1"]
    # f=1: d0..d3 R1 = 1.0,.9,.8,.7 → median .85 ; f=0: d4..d7 = .6,.5,.4,.3 → .45 ; U(d8,d9) 제외
    assert leg["effect"]["estimate"] == pytest.approx(0.4)
    assert (leg["n"], leg["comparison_n"], leg["missingness"]["u_n"]) == (4, 4, 2)
    rp = {x["behavior_metric"]: x for x in calc["reaction_to_performance"]}
    leg = rp["reaction_share_R1"]
    assert leg["relation"] == "reaction_to_performance"
    assert leg["effect"]["estimate"] == pytest.approx(1.0) and leg["n"] == 9  # d9 는 비율 null
    assert leg["missingness"]["missing_behavior_n"] == 1
    for group in calc.values():
        for x in group:
            assert x["validation_status"] == "검증 전 AI 판정" and x["mvp_input_eligible"] is False
    # 원문·rationale·timestamp·제목 표식은 어디에도 없다
    assert SECRET not in text and RATIONALE not in text and "1:23" not in text
    manifest = json.loads((jcase["out"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mvp_input_eligible"] is False and manifest["relative_performance_mode"] == "provisional_legacy"
    for key, content in inputs.items():
        assert jcase[key].read_bytes() == content


def test_loader_never_selects_comment_text_or_rationale(jcase):
    conn = rprof.open_readonly(jcase["db"])
    seen = []
    conn.set_trace_callback(seen.append)
    rows = rprof.load_comment_reactions(conn, {"d0"}, prompt_version=PV, model=MODEL)
    rprof.load_sampling(conn, {"d0"})
    rprof.label_versions(conn)
    assert rows and all("text" not in r and "rationale" not in r for r in rows)
    sql = " ".join(seen).lower()
    assert "c.text" not in sql and "rationale" not in sql and "timestamps_json" not in sql
    with pytest.raises(sqlite3.OperationalError):  # 읽기 전용
        conn.execute("DELETE FROM comments")
    conn.close()


def test_db_without_eligibility_columns_is_refused(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE comments (comment_id TEXT, video_id TEXT, text TEXT);"
                       "CREATE TABLE comment_reactions (comment_id TEXT);")
    conn.close()
    conn = rprof.open_readonly(db)
    with pytest.raises(ValueError, match="analysis_eligible"):
        rprof.load_comment_reactions(conn, {"v"}, prompt_version=PV, model=MODEL)
    conn.close()


def test_sampling_run_id_selects_one_run(jcase):
    conn = rprof.open_readonly(jcase["db"])
    assert rprof.load_sampling(conn, {"d8"}, "run2")["d8"]["completeness"] == "complete"
    conn.close()


# ------------------------------------------------------------------ Holdout 봉인

@pytest.mark.parametrize("extra", [{"split_name": "holdout"}, {"split_name": "discovery"},
                                   {"split_name": "discovery", "unseal_holdout": True}])
def test_holdout_sealed_and_discovery_refused_before_input_access(jcase, extra):
    for k in ("ev", "labels", "db", "split", "reg"):
        jcase[k].unlink()
    with pytest.raises((HoldoutSealed, ValueError)) as error:
        rj.run(**jcase["kw"], **extra)
    if extra["split_name"] == "holdout":
        assert error.type is HoldoutSealed
    assert not jcase["out"].exists()


def test_cli_refuses_holdout_without_unseal(jcase):
    with pytest.raises(SystemExit) as error:
        rj.main(jcase["argv"] + ["--split-name", "holdout"])
    assert error.value.code == 2 and not jcase["out"].exists()


def test_explicit_unseal_reads_only_holdout(jcase):
    assert rj.main(jcase["argv"] + ["--split-name", "holdout", "--unseal-holdout"]) == 0
    _, report = read_report(jcase["out"])
    assert [r["video_id"] for r in report["rows"]] == ["h"]
    assert report["scope"]["unseal_holdout"] is True and report["rows"][0]["split"] == "holdout"


# ------------------------------------------------------------------ 상대 성과 표시

def test_reference_manifest_marks_canonical_rows(jcase):
    from test_reference_population import BOUNDARY, iso, manifest_for, up

    split_ids = {v["video_id"] for v in jcase["videos"]}
    m = manifest_for([up(f"r{i}", 10 + i, views=100) for i in range(5)], split_ids, boundary=iso(BOUNDARY))
    path = jcase["tmp"] / "reference.json"
    path.write_text(json.dumps(m), encoding="utf-8")
    rj.run(**jcase["kw"], reference_manifest=path)
    _, report = read_report(jcase["out"])
    rows = {r["video_id"]: r for r in report["rows"]}
    assert rows["d2"]["view_multiple"] == pytest.approx(3.0)  # 300 / reference 중앙값 100
    assert rows["d2"]["relative_performance"] == {"canonical": True, "status": "canonical_reference",
                                                  "canonical_value_status": "available", "final_eligible": False}
    contract = report["input_contract"]["relative_performance"]
    assert contract["canonical"] is True and contract["reference_manifest_sha256"] == m["manifest_sha256"]
    assert json.loads((jcase["out"] / "manifest.json").read_text(encoding="utf-8"))[
        "relative_performance_mode"] == "canonical_reference"


# ------------------------------------------------------------------ MVP 격리

def test_join_rows_cannot_enter_finding_engine(jcase):
    rj.run(**jcase["kw"])
    _, report = read_report(jcase["out"])
    labels = {r["video_id"]: r["features"] for r in report["rows"]}
    with pytest.raises(ValueError, match="검증 전 AI 판정"):
        build_findings(report["rows"], labels, frozen_registry())
    with pytest.raises(ValueError, match="검증 전 AI 판정"):
        build_findings(rj._flat(report["rows"]), labels, frozen_registry())


@pytest.mark.parametrize("extra", [{"reaction_share_R1": 0.5}, {"reaction_profile": {}},
                                   {"mvp_input_eligible": False}])
def test_finding_engine_rejects_any_reaction_marked_video(extra):
    videos, labels = engine_data()
    videos[3].update(extra)
    with pytest.raises(ValueError, match="MVP Finding"):
        build_findings(videos, labels, frozen_registry())


def test_finding_engine_default_unchanged_without_reaction_fields():
    videos, labels = engine_data()
    before = copy.deepcopy(videos)
    out = build_findings(videos, labels, frozen_registry())
    assert videos == before and "reaction" not in json.dumps(out)


def test_reaction_fields_in_evidence_never_reach_mvp_findings(jcase):
    d = json.loads(jcase["ev"].read_text(encoding="utf-8"))
    for v in d["videos"]:
        v.update(reaction_share_R1=0.9, reaction_profile={"status": "available"}, mvp_input_eligible=False)
    jcase["ev"].write_text(json.dumps(d), encoding="utf-8")
    out = frozen.OUTPUT_ROOT / "mvp-run"
    runner.run(registry=jcase["reg"], labels=jcase["labels"], split=jcase["split"], evidence=jcase["ev"], out=out)
    text = (out / "findings.json").read_text(encoding="utf-8")
    assert "reaction" not in text and "mvp_input_eligible" not in text


def test_mvp_contracts_have_no_reaction_fields():
    for name in (*AUDIENCE_METRICS, *OBSERVATION_QUALITY_METRICS, *frozen.ANALYSIS_FIELDS):
        assert not name.startswith("reaction_") and name != "mvp_input_eligible"


def test_output_root_is_separate_new_directory(jcase):
    with pytest.raises(ValueError, match="MVP Finding"):
        rj.run(**{**jcase["kw"], "out": frozen.OUTPUT_ROOT / "x"})
    with pytest.raises(ValueError):
        rj.run(**{**jcase["kw"], "out": jcase["tmp"] / "elsewhere"})
    with pytest.raises(ValueError):
        rj.run(**{**jcase["kw"], "out": rj.OUTPUT_ROOT})
    rj.run(**jcase["kw"])
    with pytest.raises(FileExistsError):
        rj.run(**jcase["kw"])


def test_requires_frozen_registry_and_complete_labels(jcase):
    reg = json.loads(jcase["reg"].read_text(encoding="utf-8"))
    jcase["reg"].write_text(json.dumps(reg["registry"]), encoding="utf-8")
    with pytest.raises(ValueError, match="동결"):
        rj.run(**jcase["kw"])
    jcase["reg"].write_text(json.dumps(reg), encoding="utf-8")
    labs = json.loads(jcase["labels"].read_text(encoding="utf-8"))
    del labs["labels"]["d4"]
    jcase["labels"].write_text(json.dumps(labs), encoding="utf-8")
    with pytest.raises(ValueError, match="판정"):
        rj.run(**jcase["kw"])
    assert not jcase["out"].exists()


@pytest.mark.parametrize("missing", ["prompt_version", "model"])
def test_prompt_version_and_model_required(jcase, missing):
    with pytest.raises(ValueError, match="prompt_version"):
        rj.run(**{**jcase["kw"], missing: ""})
