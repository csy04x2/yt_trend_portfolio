# -*- coding: utf-8 -*-
"""채널 단위 추출기 계약 검사. 판정기는 주입한 가짜를 쓴다 — 네트워크·API·DB 없음."""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.feature_extractor import channel as ch  # noqa: E402
from tools.feature_extractor.core import FEATURE_ROUTING, TEXT_ONLY, TEXT_THEN_VISUAL, set_feature_routing  # noqa: E402

DEFAULT_ROUTING = dict(FEATURE_ROUTING)


@pytest.fixture(autouse=True)
def restore_routing():
    yield
    set_feature_routing(DEFAULT_ROUTING)


def feature(fid, name=None):
    return {"feature_id": fid, "name": name or fid, "version": "0.1", "scope": "video", "value_type": "binary",
            "definition": f"{fid} 정의", "inclusion_examples": ["예"], "exclusion_examples": [f"{fid} 제외 예"],
            "required_evidence": ["근거"], "source": "llm", "status": "candidate"}


def registry(ids):
    return {"schema_version": "0.1", "notice": "test", "features": [feature(f) for f in ids]}


def video(i, axis="long", views=None):
    row = {"video_id": f"v{i:02d}abcdefghi"[:11], "title": f"영상 {i}", "duration_sec": 1200 if axis == "long" else 30,
           "published_at": "2026-06-01T00:00:00Z", "length_axis": axis}
    if views is not None:
        row["view_count"] = views
    return row


def judgments(defs, label="U", conf="medium"):
    return [{"feature_id": f["feature_id"], "label": label, "confidence": conf, "reason": "r"} for f in defs]


def write(tmp, name, data):
    p = tmp / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_content_projection_drops_outcome_fields(tmp_path):
    p = write(tmp_path, "e.json", {"videos": [video(1, views=100), video(2)]})
    rows = ch.load_content(p)
    assert all("view_count" not in r for r in rows) and len(rows) == 2


def test_scope_and_holdout_seal(tmp_path):
    rows = [video(1), video(2), video(3)]
    split = {rows[0]["video_id"]: "development", rows[1]["video_id"]: "holdout", rows[2]["video_id"]: "discovery"}
    assert [r["video_id"] for r in ch.select_scope(rows, split, "development")] == [rows[0]["video_id"]]
    with pytest.raises(ValueError):
        ch.select_scope(rows, split, "holdout")
    with pytest.raises(ValueError):
        ch.select_scope(rows, split, "all")
    assert len(ch.select_scope(rows, split, "all", unseal_holdout=True)) == 3
    assert len(ch.select_scope(rows, None, "development")) == 3   # 분할이 없으면 전체(제품 모드)


def test_routing_default_file_and_fallback(tmp_path):
    feats = [feature(f) for f in FEATURE_ROUTING]
    assert ch.routing_for(feats)[1] == "default"
    other = [feature("food_eating"), feature("title_quote")]
    routing, src = ch.routing_for(other)
    assert src == "all_visual_fallback" and set(routing.values()) == {TEXT_THEN_VISUAL}
    rp = write(tmp_path, "routing.json", {"food_eating": TEXT_THEN_VISUAL, "title_quote": TEXT_ONLY})
    routing, src = ch.routing_for(other, rp)
    assert src == "file" and routing["title_quote"] == TEXT_ONLY
    with pytest.raises(ValueError):
        ch.routing_for(other + [feature("x")], rp)


def test_swapped_registry_flows_through_extract_video():
    ids = ["food_eating", "title_quote"]
    set_feature_routing({"food_eating": TEXT_THEN_VISUAL, "title_quote": TEXT_ONLY})
    defs = ch.definitions_by_id([feature(f) for f in ids])
    calls = []
    def tj(m, c, fs, model):
        calls.append(len(fs))
        return judgments(fs, "1")
    res = ch.run_one(video(1), defs, None, caption="먹는다", packet=None, model="m", text_judge=tj,
                     visual_judge=None, cache=ch.Cache(None), prompt_sha="p", registry_sha="r")
    assert res["labels"] == {"food_eating": "1", "title_quote": "1"} and calls == [2]


def test_chunk_merge_rules():
    fids = ["a", "b", "c"]
    j = lambda fid, lab, conf="medium": {"feature_id": fid, "label": lab, "confidence": conf, "reason": "r"}
    b1 = [j("a", "1", "low"), j("b", "0"), j("c", "0")]
    b2 = [j("a", "1", "high"), j("b", "0"), j("c", "U")]
    m = {x["feature_id"]: x for x in ch.merge_chunk_judgments([b1, b2], fids)}
    assert m["a"]["label"] == "1" and m["a"]["confidence"] == "high"   # 하나라도 1이면 1, 가장 자신 있는 것
    assert m["b"]["label"] == "0"                                       # 전부 0일 때만 0
    assert m["c"]["label"] == "U"                                       # 섞이면 U
    assert ch.chunk_caption("x" * 250, size=100) == ["x" * 100, "x" * 100, "x" * 50]


def test_cache_prevents_second_call(tmp_path):
    defs = ch.definitions_by_id([feature(f) for f in FEATURE_ROUTING])
    n = {"calls": 0}
    def tj(m, c, fs, model):
        n["calls"] += 1
        return judgments(fs, "U")
    cache = ch.Cache(tmp_path / "cache")
    for _ in range(2):
        ch.run_one(video(1), defs, None, caption=None, packet=None, model="m", text_judge=tj,
                   visual_judge=None, cache=cache, prompt_sha="p", registry_sha="r")
    assert n["calls"] == 1 and cache.hits == 1


def test_visual_only_for_text_U_and_zero_needs_positive_exclusion():
    defs = ch.definitions_by_id([feature(f) for f in FEATURE_ROUTING])
    packet = {"metadata": {k: v for k, v in video(1).items()}, "caption": "자막",
              "frames": [{"frame_id": "frame_1", "timestamp_sec": 3.0, "image_base64": "QUJD"}]}
    seen = {}
    def tj(m, c, fs, model):
        out = judgments(fs, "U")
        out[0]["label"] = "1"                       # guest_present는 텍스트에서 이미 1
        return out
    def vj(pkt, subset, model):
        seen["ids"] = sorted(f["feature_id"] for f in subset)
        return [{"feature_id": f["feature_id"], "label": "0", "confidence": "high", "reason": "안 보임",
                 "positive_exclusion": None} for f in subset]
    res = ch.run_one(video(1), defs, None, caption="자막", packet=packet, model="m", text_judge=tj,
                     visual_judge=vj, cache=ch.Cache(None), prompt_sha="p", registry_sha="r")
    assert "guest_present" not in seen["ids"]                         # 텍스트로 끝난 특징은 화면을 안 본다
    assert all(f in seen["ids"] for f in ("eating_content", "on_location"))
    assert "tournament_format" not in seen["ids"]                     # TEXT_ONLY는 시각 단계 없음
    assert res["labels"]["guest_present"] == "1"
    assert res["labels"]["eating_content"] == "U"                     # 프레임에 안 보임 ≠ 0


def test_review_sample_picks_low_confidence_visual_and_random():
    defs = ch.definitions_by_id([feature(f) for f in FEATURE_ROUTING])
    rows = [video(i) for i in range(1, 21)]
    results = []
    for i, r in enumerate(rows):
        conf = "low" if i == 0 else "high"
        res = ch.run_one(r, defs, None, caption=None, packet=None, model="m",
                         text_judge=lambda m, c, fs, mo, conf=conf: judgments(fs, "0", conf),
                         visual_judge=None, cache=ch.Cache(None), prompt_sha="p", registry_sha="r")
        results.append(res)
    q = ch.review_sample(results, rows, share=0.1, seed=1)
    ids = {x["video_id"] for x in q}
    assert rows[0]["video_id"] in ids and len(q) == 1 + 2
    assert any("자신 없음" in w for w in q[0]["why"]) if q[0]["video_id"] == rows[0]["video_id"] else True


def test_offline_export_import_roundtrip(tmp_path, monkeypatch):
    ids = list(FEATURE_ROUTING)
    content = write(tmp_path, "e.json", {"videos": [video(1, views=5), video(2, "shorts")]})
    reg = write(tmp_path, "r.json", registry(ids))
    caps = tmp_path / "caps"
    caps.mkdir()
    (caps / f"{video(1)['video_id']}.txt").write_text("오늘 게스트와 먹방", encoding="utf-8")
    out = tmp_path / "run1"
    assert ch.main(["run", "--content", str(content), "--registry", str(reg), "--out", str(out), "--captions", str(caps)]) == 0
    inputs = sorted((out / "judge_input").glob("*.json"))
    assert len(inputs) == 2
    first = json.loads(inputs[0].read_text(encoding="utf-8"))
    assert "view_count" not in json.dumps(first) and set(first) >= {"definitions", "metadata", "caption", "answer_format"}
    ans = tmp_path / "answers"
    ans.mkdir()
    for p in inputs:
        d = json.loads(p.read_text(encoding="utf-8"))
        js = [{"feature_id": f["feature_id"], "label": "1" if f["feature_id"] == "eating_content" and d["caption"] else "U",
               "confidence": "high", "reason": "자막에 먹방"} for f in d["definitions"]]
        (ans / p.name).write_text(json.dumps({"judgments": js}, ensure_ascii=False), encoding="utf-8")
    assert ch.main(["import", "--run", str(out), "--answers", str(ans)]) == 0
    labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))
    assert labels["complete_registry_matrix"] and labels["labels"][video(1)["video_id"]]["eating_content"] == "1"
    assert labels["labels"][video(2)["video_id"]]["eating_content"] == "U"
    assert (out / "summary.md").exists() and (out / "review_queue.jsonl").exists()
    # feature_outcome 이 그대로 읽는다 (문자열 0/1/U)
    sys.path.insert(0, str(ROOT / "backend"))
    from feature_outcome.labels import load_labels, load_registry
    got = load_labels(out / "labels.json", load_registry(reg))
    assert got[video(1)["video_id"]]["eating_content"] == 1
    # 같은 출력 폴더 재사용은 거부
    assert ch.main(["run", "--content", str(content), "--registry", str(reg), "--out", str(out)]) == 2


def test_evaluate_keeps_U_out_of_accuracy():
    pred = {"a": {"f": "1"}, "b": {"f": "U"}, "c": {"f": "0"}, "d": {"f": "1"}}
    ref = {"a": {"f": 1}, "b": {"f": 1}, "c": {"f": "U"}, "d": {"f": 0}}
    r = ch.evaluate(pred, ref, {"a": "long", "b": "long", "c": "shorts", "d": "shorts"})["f"]
    assert r["ref_nonU"] == 3 and r["pred_nonU_on_ref_nonU"] == 2 and r["agree"] == 1 and r["false_1"] == 1
    assert r["coverage"] == pytest.approx(2 / 3) and r["accuracy_on_covered"] == 0.5


def test_offline_visual_roundtrip(tmp_path):
    ids = list(FEATURE_ROUTING)
    content = write(tmp_path, "e.json", {"videos": [video(1)]})
    reg = write(tmp_path, "r.json", registry(ids))
    out = tmp_path / "run"
    assert ch.main(["run", "--content", str(content), "--registry", str(reg), "--out", str(out)]) == 0
    vid = video(1)["video_id"]
    ans = tmp_path / "answers"; ans.mkdir()
    (ans / f"{vid}.json").write_text(json.dumps({"judgments": judgments([feature(f) for f in ids], "U")}), encoding="utf-8")
    ev = tmp_path / "frames" / vid; ev.mkdir(parents=True)
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 64
    (ev / "frame_1.jpg").write_bytes(jpg)
    (ev / "evidence_packet.json").write_text(json.dumps({"frames": [{"path": "frame_1.jpg", "timestamp_sec": 5.0, "ratio": 0.25}]}), encoding="utf-8")
    # 1차 import: 시각 입력이 내보내진다
    assert ch.main(["import", "--run", str(out), "--answers", str(ans), "--evidence-root", str(tmp_path / "frames")]) == 0
    vi = json.loads((out / "visual_input" / f"{vid}.json").read_text(encoding="utf-8"))
    assert {f["feature_id"] for f in vi["features"]} == {f for f, r in FEATURE_ROUTING.items() if r == TEXT_THEN_VISUAL}
    assert json.loads((out / "labels.json").read_text(encoding="utf-8"))["labels"][vid]["eating_content"] == "U"
    # 2차 import: 시각 답안 반영. 프레임 근거로 1, 배제 근거 없는 0은 U
    vans = tmp_path / "vanswers"; vans.mkdir()
    js = [{"feature_id": f["feature_id"], "label": "0", "confidence": "high", "reason": "안 보임", "positive_exclusion": None} for f in vi["features"]]
    js[0].update(label="1", reason="프레임에 먹는 장면")
    (vans / f"{vid}.json").write_text(json.dumps({"judgments": js}), encoding="utf-8")
    assert ch.main(["import", "--run", str(out), "--answers", str(ans), "--evidence-root", str(tmp_path / "frames"), "--visual-answers", str(vans)]) == 0
    labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))["labels"][vid]
    assert labels[js[0]["feature_id"]] == "1" and labels[js[1]["feature_id"]] == "U"
