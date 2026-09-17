"""Reaction Phase 3 평가 도구와 사람 판정 시트.

작은 합성 표본으로 지표를 손으로 계산한 값과 대조한다. 댓글 원문은 전부 이
파일에서 지어낸 문장이다.
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import label_reactions as lr  # noqa: E402
from app.pipeline import reaction_eval as ev  # noqa: E402
from app.pipeline import reaction_sheet as sh  # noqa: E402

SECRET = "합성근거-원문조각-노출금지"


def L(cid, reactions, targets, flag=False):
    return {"comment_id": cid, "reactions": reactions, "targets": targets,
            "explicit_timestamps": [], "review_flag": flag,
            "review_reason": "DEFINITION_BOUNDARY" if flag else None,
            "rationale": SECRET}


# A = 기준, B = 비교. 4건 공통 + 각자 1건씩.
A = [L("a1", ["R1", "R7"], ["T2"]),
     L("a2", [], []),
     L("a3", ["R4"], ["T4"]),
     L("a4", ["R6"], ["UNKNOWN"], flag=True),
     L("only_a", ["R2"], ["T3"])]
B = [L("a1", ["R1"], ["T2"]),
     L("a2", [], []),
     L("a3", [], ["T4"]),
     L("a4", ["R6"], ["T2"]),
     L("only_b", ["R3"], ["T5"])]


def _report():
    return ev.evaluate(ev.parse_labels({"labels": A}), ev.parse_labels({"labels": B}))


# --------------------------------------------------------------------------
# 기본 지표
# --------------------------------------------------------------------------

def test_binary_and_kappa_hand_computed():
    m = ev.binary([True, True, False, False], [True, False, False, False])
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 0, 1, 2)
    assert m["precision"] == 1.0 and m["recall"] == 0.5
    assert abs(m["f1"] - 2 / 3) < 1e-9
    # po = .75, pe = (1·2 + 3·2)/16 = .5 → kappa = .5
    assert abs(m["kappa"] - 0.5) < 1e-9


def test_undefined_metrics_are_none_not_zero():
    m = ev.binary([False] * 4, [False] * 4)
    assert m["precision"] is None and m["recall"] is None and m["f1"] is None
    assert m["kappa"] is None
    assert ev.cohen_kappa(0, 0, 0, 0) is None
    one_sided = ev.binary([True, False], [False, False])
    assert one_sided["precision"] is None and one_sided["f1"] == 0.0


def test_jaccard_both_empty_is_agreement():
    assert ev.jaccard([], []) == 1.0
    assert ev.jaccard(["R1", "R7"], ["R1"]) == 0.5


# --------------------------------------------------------------------------
# evaluate
# --------------------------------------------------------------------------

def test_evaluate_on_synthetic_fixture():
    r = _report()
    assert r["n_compared"] == 4
    assert r["only_in_a_ids"] == ["only_a"] and r["only_in_b_ids"] == ["only_b"]

    rx = r["reactions"]
    assert rx["exact_match_rate"] == 0.5                  # a2, a4
    assert abs(rx["jaccard_mean"] - (0.5 + 1 + 0 + 1) / 4) < 1e-9
    assert rx["disagreeing_ids"] == ["a1", "a3"]
    r7 = rx["per_label"]["R7"]
    assert (r7["tp"], r7["fn"], r7["recall"]) == (0, 1, 0.0)
    assert r7["precision"] is None                        # B 는 R7 을 한 번도 안 씀
    assert r7["f1"] == 0.0                                # 그래도 놓친 것은 F1 0 이다
    assert rx["per_label"]["R1"]["f1"] == 1.0
    assert rx["per_label"]["R5"]["f1"] is None            # 표본에 없는 희귀 라벨
    assert "R5" not in rx["macro_f1_labels"] and "R7" in rx["macro_f1_labels"]
    # 두 쪽 중 하나라도 쓴 라벨: R1, R4, R6, R7 → F1 1, 0, 1, 0
    assert rx["macro_f1"] == 0.5

    none = r["reaction_none"]
    assert none["confusion"] == {"a_none_b_none": 1, "a_none_b_some": 0,
                                 "a_some_b_none": 1, "a_some_b_some": 2}
    assert none["disagreeing_ids"] == ["a3"]

    tg = r["targets"]
    assert tg["exact_match_rate"] == 0.75 and tg["disagreeing_ids"] == ["a4"]
    assert tg["per_label"]["UNKNOWN"]["fn"] == 1
    assert r["both_exact_match_rate"] == 0.25             # a2 만
    assert r["review_flag_counts"] == {"a": 1, "b": 0}


def test_report_and_render_contain_no_text_or_rationale():
    r = _report()
    blob = json.dumps(r, ensure_ascii=False) + ev.render(r, {"labeler": "human:x"},
                                                         {"labeler": "ai:m"})
    assert SECRET not in blob, "보고서에 rationale 이 새었다"
    assert "a3" in blob


def test_parse_rejects_bad_codes_and_duplicates():
    bad = {"labels": [L("x", ["R11"], ["T1"]), L("y", ["R1", "UNKNOWN"], ["T1"]),
                      L("z", ["R1"], []), L("x", [], [])]}
    try:
        ev.parse_labels(bad, "bad.json")
    except lr.ValidationError as e:
        msg = str(e)
        for x in ("R11", "섞을 수 없다", "targets 가 비었다", "두 번"):
            assert x in msg, f"'{x}' 를 못 잡았다: {msg}"
        return
    raise AssertionError("규칙을 어긴 라벨 파일로 지표를 냈다")


def test_parse_accepts_minimal_human_rows():
    got = ev.parse_labels([{"comment_id": "h1", "reactions": [], "targets": []}])
    assert got["h1"]["review_flag"] is False and got["h1"]["rationale"] == ""


def test_load_labels_reads_meta():
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t) / "ai.json"
        p.write_text(json.dumps(lr.label_file(
            [dict(x) for x in A], labeler="ai:m", prompt_version="reaction-v1", model="m"),
            ensure_ascii=False), encoding="utf-8")
        labels, meta = ev.load_labels(p)
        assert len(labels) == 5 and meta["labeler"] == "ai:m"


# --------------------------------------------------------------------------
# 사람 판정 시트
# --------------------------------------------------------------------------

def _raw(tmp: pathlib.Path) -> pathlib.Path:
    p = tmp / "raw.json"
    p.write_text(json.dumps({"comments": [
        {"comment_id": "s1", "video_id": "v", "video_title": "합성 영상",
         "channel_name": "합성채널", "text": "합성댓글 </script><b>태그</b> 3:21",
         "analysis_eligible": True},
        {"comment_id": "s2", "video_id": "v", "text": "합성댓글 채널 본인",
         "analysis_eligible": False, "exclusion_reason": "own_channel"},
    ]}, ensure_ascii=False), encoding="utf-8")
    return p


def test_sheet_written_only_inside_base():
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        base = tmp / "data"
        try:
            sh.write_sheet(_raw(tmp), tmp / "sheet.html", base=base)
        except lr.UnsafePath:
            pass
        else:
            raise AssertionError("원문이 든 시트를 base 밖에 썼다")
        assert not (tmp / "sheet.html").exists()


def test_sheet_embeds_eligible_comments_safely():
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        base = tmp / "data"
        info = sh.write_sheet(_raw(tmp), base / "sheets" / "s.html", base=base)
        assert info["comments"] == 1 and info["skipped_ineligible"] == 1
        html = (base / "sheets" / "s.html").read_text(encoding="utf-8")
        assert "s1" in html and "s2" not in html
        # 원문 속 </script> 가 태그를 닫지 않는다 — 템플릿의 script 3개만 닫힌다
        assert html.count("</script>") == 3
        for code in ("R1", "R10", "T5", "UNKNOWN", "DEFINITION_BOUNDARY"):
            assert code in html
        assert '"3:21"' in html            # 원문에 있는 timestamp 는 미리 채운다
        assert "http://" not in html and "https://" not in html   # 외부 자원 없음


def test_sheet_json_roundtrips_original_text():
    items = [{"comment_id": "q", "text": "합성 <!-- </script> \\ \" 끝"}]
    html = sh.build_sheet(items, sheet_id="t")
    start = html.index('id="items">') + len('id="items">')
    payload = html[start:html.index("</script>", start)]
    assert json.loads(payload)[0]["text"] == items[0]["text"]


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"  ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)
