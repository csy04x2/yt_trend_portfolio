"""Reaction Stage 09 문장 · 대시보드 블록 · 경계 — 합성 데이터만.

해석 기준값(n·영상 수·UNKNOWN·차이), 상태 접두어, Finding 경계, 빈 상태 블록,
템플릿의 Reaction 자리, 읽기 전용 내보내기.
"""

import importlib.util
import json
import pathlib
import re
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from app.interpret import reaction as ri  # noqa: E402
from app.interpret import reaction_report as rr  # noqa: E402
from app.pipeline import reaction_metrics as rm  # noqa: E402

STATUS = "검증 전 AI 판정"


def _spec(vid, spec):
    out, i = [], 0
    for n, rs, ts in spec:
        for _ in range(n):
            out.append({"comment_id": f"{vid}-{i}", "video_id": vid, "reactions": list(rs),
                        "targets": list(ts), "review_flag": False, "analysis_eligible": 1})
            i += 1
    return out


def _channel(a_spec, b_spec, *, n_a=6, n_b=6, perf=None):
    """유형 A 영상 n_a편, 유형 B 영상 n_b편. 영상마다 spec 대로 댓글 10건 안팎."""
    videos, labels, types = {}, [], {}
    for i in range(n_a):
        vid = f"a{i}"
        videos[vid], types[vid] = {"length_axis": "long"}, "A"
        labels += _spec(vid, a_spec)
    for i in range(n_b):
        vid = f"b{i}"
        videos[vid], types[vid] = {"length_axis": "long"}, "B"
        labels += _spec(vid, b_spec)
    return rm.compute(labels, videos, prompt_version="p", model="m",
                      type_maps=[{"taxonomy_id": 1, "axis": "topic", "labels": types}],
                      performance=perf)


NAMES = {1: {"A": "가형", "B": "나형"}}


def _sentences(res, key="A", axis="all"):
    return [s for s in res["sentences"] if s["group_key"] == key and s["length_axis"] == axis]


# --------------------------------------------------------------------------
# 기준값
# --------------------------------------------------------------------------

def test_difference_above_threshold_becomes_flagged_sentence():
    recs = _channel([(6, ["R7"], ["T2"]), (4, ["R1"], ["T1"])],
                    [(3, ["R7"], ["T2"]), (7, ["R1"], ["T1"])])
    res = ri.interpret(recs, names=NAMES)
    got = {s["label"]: s for s in _sentences(res)}
    assert "R7" in got and got["R7"]["diff_pp"] == pytest.approx(30.0)
    s = got["R7"]
    assert s["text"].startswith("[검증 전 AI 판정] ")
    assert "「가형」 유형 영상 댓글에서 R7 내용 참여 비율이 채널의 나머지 영상 댓글보다 높다" in s["text"]
    assert "60.0% 대 30.0%" in s["text"] and "댓글 60건·영상 6편 대 60건·6편" in s["text"]
    assert s["validation_status"] == STATUS and s["finding_input"] is False
    assert got["R1"]["text"].count("낮다") == 1
    assert "T2" in got, "Target 차이도 문장이 된다"
    assert res["finding_input"] is False and res["validation_status"] == STATUS
    for s in res["sentences"]:
        assert not re.search(r"때문|해야|하면|원인|늘리", s["text"]), "인과·조언 표현"


def test_difference_below_threshold_is_silent():
    # 55% 대 46% = 9%p
    recs = _channel([(11, ["R7"], ["T2"]), (9, [], [])], [(46, ["R7"], ["T2"]), (54, [], [])],
                    n_a=5, n_b=1)
    res = ri.interpret(recs, names=NAMES, cfg=ri.InterpretConfig(min_videos=1))
    assert not [s for s in _sentences(res) if s["label"] == "R7"]


def test_minimum_comments_and_videos_withhold():
    few = _channel([(6, ["R7"], ["T2"]), (2, [], [])], [(1, ["R7"], ["T2"]), (7, [], [])])  # 48건씩
    res = ri.interpret(few, names=NAMES)
    assert not res["sentences"]
    assert any("최소 50건" in w["reason"] for w in res["withheld"])

    thin = _channel([(6, ["R7"], ["T2"]), (4, [], [])], [(1, ["R7"], ["T2"]), (9, [], [])], n_a=4, n_b=8)
    res = ri.interpret(thin, names=NAMES, cfg=ri.InterpretConfig(min_comments=10))
    assert not _sentences(res, "A")
    assert any(w["group_key"] == "A" and "최소 5편" in w["reason"] for w in res["withheld"])


def test_high_unknown_share_withholds():
    recs = _channel([(5, ["R7"], ["T2"]), (3, ["UNKNOWN"], ["UNKNOWN"]), (2, [], [])],
                    [(1, ["R7"], ["T2"]), (9, [], [])])
    res = ri.interpret(recs, names=NAMES)
    assert not _sentences(res, "A")
    assert any(w["group_key"] == "A" and "UNKNOWN" in w["reason"] for w in res["withheld"])


def test_none_and_unknown_differences_are_not_sentences():
    recs = _channel([(9, [], []), (1, ["R7"], ["T2"])], [(1, [], []), (9, ["R7"], ["T2"])])
    res = ri.interpret(recs, names=NAMES)
    assert {s["label"] for s in res["sentences"]} <= set(rm.REACTIONS) | {"T1", "T2", "T3", "T4", "T5"}


def test_tier_sentence_marks_provisional_performance():
    perf = {"values": {**{f"a{i}": 5.0 + i for i in range(6)}, **{f"b{i}": 0.1 * (i + 1) for i in range(6)}},
            "meta": {"canonical": False}}
    recs = _channel([(8, ["R10"], ["T5"]), (2, [], [])], [(1, ["R10"], ["T5"]), (9, [], [])],
                    n_a=6, n_b=6, perf=perf)
    res = ri.interpret(recs, names=NAMES, cfg=ri.InterpretConfig(min_videos=2, min_comments=20))
    tier = [s for s in res["sentences"] if s["scope"] == "tier" and s["label"] == "R10"]
    assert tier
    assert all(s["provisional_performance"] and s["text"].endswith("임시값(provisional)이다.") for s in tier)
    assert any("조회 배수 상위 층(t3)" in s["text"] for s in tier)


def test_mixed_versions_refused():
    a = _channel([(10, ["R1"], ["T1"])], [(10, ["R1"], ["T1"])])
    b = [dict(r, model="other") for r in a]
    with pytest.raises(ValueError):
        ri.interpret(a + b)


def test_thresholds_are_reported_with_output():
    res = ri.interpret([])
    assert res["state"] == "empty" and res["sentences"] == []
    assert res["thresholds"] == {"min_comments": 50, "min_videos": 5,
                                 "max_unknown_share": 0.2, "min_diff": 0.1}


# --------------------------------------------------------------------------
# 경계 — Finding·Stage 08 코드가 해석을 끌어오지 않는다
# --------------------------------------------------------------------------

def test_finding_and_stage08_code_do_not_import_reaction_outputs():
    pat = re.compile(r"(app\.interpret|reaction_metrics|reaction_report)")
    for path in sorted((ROOT / "feature_outcome").glob("*.py")):
        assert not pat.search(path.read_text(encoding="utf-8")), f"{path.name} 가 Reaction 결과를 import 한다"
    for name in ("aggregate.py", "reaction_metrics.py", "observable.py"):
        src = (ROOT / "app/pipeline" / name).read_text(encoding="utf-8")
        assert "app.interpret" not in src and "from app import interpret" not in src, name


# --------------------------------------------------------------------------
# 대시보드 블록
# --------------------------------------------------------------------------

def test_empty_block_has_no_numbers():
    b = rr.build_block([], source={"db": "x.db"})
    assert b["state"] == "empty"
    assert b["empty_message"] == "아직 판정 결과 없음 — 판정 실행 후 채워짐"
    assert b["validation_status"] == STATUS and b["finding_input"] is False
    assert b["rows"] == [] and b["interpretation"]["sentences"] == []
    assert b["source"]["n_labeled_comments"] == 0
    assert [c for c, _ in b["codes"]["reactions"]] == [f"R{i}" for i in range(1, 11)]
    assert [c for c, _ in b["codes"]["targets"]] == ["T1", "T2", "T3", "T4", "T5", "UNKNOWN"]
    assert dict(b["codes"]["reactions"])["R9"] == "행동 지향"


def test_available_block_rows_and_no_comment_ids():
    recs = _channel([(6, ["R7"], ["T2"]), (4, ["R1"], ["T1"])],
                    [(3, ["R7"], ["T2"]), (7, ["R1"], ["T1"])])
    b = rr.build_block(recs, taxonomies=[{"taxonomy_id": 1, "axis": "topic", "names": NAMES[1]}])
    assert b["state"] == "available" and b["source"]["n_labeled_comments"] == 120
    assert {r["scope"] for r in b["rows"]} == {"channel", "type"}, "영상 행은 화면 블록에 싣지 않는다"
    assert {r["group_name"] for r in b["rows"] if r["scope"] == "type"} == {"가형", "나형"}
    assert all(r["validation_status"] == STATUS for r in b["rows"])
    assert b["interpretation"]["sentences"]
    assert "a0-0" not in json.dumps(b, ensure_ascii=False)


def test_template_has_reaction_section_and_no_old_placeholders():
    tpl = (REPO / "docs/prototype/chim-prototype.template.html").read_text(encoding="utf-8-sig")
    assert "reaction_report" in tpl and "검증 전 AI 판정" in tpl
    assert "아직 판정 결과 없음 — 판정 실행 후 채워짐" in tpl
    assert "미게재" not in tpl and "Reaction lift · 싣지 않음" not in tpl
    assert "serif" not in tpl.replace("sans-serif", "")


def test_exporter_writes_empty_block_from_readonly_db():
    spec = importlib.util.spec_from_file_location("export_reaction_report",
                                                  ROOT / "scripts/export_reaction_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from app.db.connection import connect

    with tempfile.TemporaryDirectory() as t:
        tp = pathlib.Path(t)
        c = connect(tp / "e.db")
        c.execute("INSERT INTO channels VALUES ('ch','u',NULL,'합성채널','pl',NULL,'2026-01-01',NULL)")
        c.close()
        before = (tp / "e.db").read_bytes()
        ev = tp / "ev.json"
        ev.write_text(json.dumps({"summary": {"video_n": 1}}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
        assert mod.main(["--db", str(tp / "e.db"), "--evidence", str(ev)]) == 0
        data = json.loads(ev.read_text(encoding="utf-8"))
        assert data["summary"] == {"video_n": 1}
        blk = data["reaction_report"]
        assert blk["state"] == "empty" and blk["rows"] == [] and blk["source"]["channel_id"] == "ch"
        assert (tp / "e.db").read_bytes() == before, "내보내기가 DB 를 고쳤다"
