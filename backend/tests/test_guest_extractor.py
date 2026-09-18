"""Synthetic contracts, not gold-derived decision rules or accuracy evidence."""
import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from tools.feature_extractor.core import inputs, stage1, evidence_packet, adjudicate, sha, FEATURE_ROUTING, TEXT_ONLY, TEXT_THEN_VISUAL, validate_text_judgment, can_escalate_visual
from tools.feature_extractor.__main__ import extract
from tools.feature_extractor.evaluate import evaluate
from tools.stage2_evidence import stage2_collect


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def row(title="", description="", vid="d0000000001"):
    return dict(video_id=vid, title=title, description=description, length_axis="shorts", duration_sec=100)


@pytest.mark.parametrize("text,label", [
    ("이 영상에서 게스트 손님가와 인터뷰를 진행합니다", "1"),
    ("이번 영상은 게스트 손님나와 요리를 함께 진행했습니다.", "1"),
    ("이번 영상은 처음부터 끝까지 게스트 없이 침착맨 혼자 진행합니다", "0"),
    ("혼자 먹방", "U"), ("게스트: 손님가", "U"), ("손님가와 함께", "U"),
    ("이 영상에서 게스트 촬영자와 인터뷰를 진행합니다", "U"),
    ("이 영상에서 게스트 손님가와 인터뷰를 진행합니다?", "U"),
    ("이 영상에서 게스트 외부 영상 속 인물과 게임을 합니다", "U"),
    ("이 영상에서 게스트 손님가와 인터뷰를 진행합니다\n풀버전 보기", "U"),
    ("이 영상에서 게스트 손님가와 인터뷰를 진행합니다\n게스트는 없습니다", "U"),
    ("", "U"),
])
def test_metadata_classification_is_retired(text, label):
    actual = stage1(row(description=text))
    assert actual["label"] == "U"
    assert actual["reason"] == "text_judgment_required"
    assert actual["evidence"] == []
    with pytest.raises(ValueError): can_escalate_visual(actual)


def test_conflicting_declarations_abstain():
    r = row("이 영상에서 게스트 손님가와 인터뷰를 진행합니다",
            "이 영상은 처음부터 끝까지 게스트 없이 침착맨 혼자 진행합니다")
    assert stage1(r)["label"] == "U"


@pytest.fixture
def case(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    split, registry, metadata = [folder / n for n in ("split.csv", "registry.json", "metadata.jsonl")]
    split.write_text("video_id,split\nd0000000001,development\nd0000000002,development\nh0000000001,holdout\ns0000000001,discovery\n", encoding="utf-8")
    feature = dict(feature_id="guest_present", name="게스트 출연", version="A-v0.1", scope="video",
                   value_type="categorical", categories=["0", "1", "U"], definition="침착맨 외 인물이 콘텐츠 참여자로 직접 출연한다.",
                   inclusion_examples=["대화·활동 참여"], exclusion_examples=["스태프·배경·외부 영상"], required_evidence=["실제 참여"], source="human", status="testing")
    dump(registry, {"registry": {"schema_version":"0.1", "notice":"synthetic", "features":[feature]},
                    "freeze_metadata":{"registry_version":"A-v0.1", "freeze_status":"frozen", "definitions_frozen_before_development":True}})
    rs = [row("이 영상에서 게스트 손님가와 인터뷰를 진행합니다"),row(vid="d0000000002")]
    metadata.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rs),encoding="utf-8")
    evidence = tmp_path / "evidence"
    vdir = evidence / rs[1]["video_id"]
    vdir.mkdir(parents=True)
    image = vdir / "test.jpg";image.write_bytes(b'\xff\xd8synthetic')
    packet = {"video_id": rs[1]["video_id"], "feature":"guest_present", "stage1_label":"U",
              "caption":{"available":True,"text":"함께 요리합니다"},
              "frames":[{"path":str(image),"timestamp_sec":50,"ratio":.5}]}
    dump(vdir / "evidence_packet.json",packet)
    return dict(metadata=metadata,split=split,registry=registry,out=tmp_path/"output",evidence=evidence,packet=packet,rows=rs,feature=feature)


def args(case):
    return [case[k] for k in ("metadata","split","registry","out")]


def answer(label="1", role="active_content_participant"):
    return {"label":label,"role":role,"confidence":"high","participation":"함께 재료를 준비함",
            "evidence":[{"type":"visual","ref":"frame_1","detail":"출연자가 조리 활동에 직접 참여"}]}


@pytest.mark.parametrize("field", ["view_count","audience","comments","outcome","human_label","extra"])
def test_closed_metadata_fields(case,field):
    r=case["rows"][0];r[field]=1;case["metadata"].write_text(json.dumps(r),encoding="utf-8")
    with pytest.raises(ValueError):inputs(case["metadata"],case["split"],case["registry"])


@pytest.mark.parametrize("vid", ["h0000000001","s0000000001","z0000000001"])
def test_only_development_input(case,vid):
    case["metadata"].write_text(json.dumps(row(vid=vid)),encoding="utf-8")
    with pytest.raises(ValueError):extract(*args(case))
    assert not case["out"].exists()


def test_cascade_escalates_only_U_and_keeps_partial_interface(case):
    seen=[]
    def judge(packet,feature,model):
        seen.append(packet["metadata"]["video_id"])
        assert feature==case["feature"] and "human_label" not in packet
        return answer(),{"model_returned":model}
    before={p:sha(p) for p in case["metadata"].parent.iterdir()}
    report=extract(*args(case),evidence_root=case["evidence"],model="test-model",judge_fn=judge)
    assert seen==["d0000000002"] and report["label_counts"]=={"0":0,"1":1,"U":1}
    labels=json.loads((case["out"]/"labels.json").read_text(encoding="utf-8"))
    assert all(set(x)=={"guest_present"} for x in labels["labels"].values())
    assert labels["complete_registry_matrix"] is False
    assert all(sha(p)==h for p,h in before.items())


def test_no_model_no_implicit_network(case):
    def forbidden(*a,**kw):raise AssertionError("network")
    report=extract(*args(case),evidence_root=case["evidence"],judge_fn=forbidden,collector=forbidden)
    assert report["label_counts"]=={"0":0,"1":0,"U":2}
    assert report["empirically_validated"] is False


def test_reuse_collector_cookie_free_and_inject_exact_definition(case,monkeypatch):
    monkeypatch.setattr(stage2_collect,"require",lambda _:None)
    seen=[]
    def collector(item,outroot,cookie,keep,feature_definition):
        seen.append(item["video_id"]);assert cookie is None and keep is False
        assert feature_definition==case["feature"]["definition"]
        p=copy.deepcopy(case["packet"]);p["frames"]=[]
        dump(outroot/item["video_id"]/"evidence_packet.json",p)
    report=extract(*args(case),collect=True,collector=collector)
    assert seen==["d0000000001","d0000000002"] and report["label_counts"]["U"]==2
    cmd=stage2_collect.yt_base(None)
    assert "--ignore-config" in cmd and "--cookies-from-browser" not in cmd


@pytest.mark.parametrize("label,role,expected", [("1","active_content_participant","1"),("1","excluded_person","U"),("0","unclear","U"),("U","unclear","U")])
def test_sampled_evidence_cannot_prove_absence(case,label,role,expected):
    r=case["rows"][1];p=evidence_packet(case["evidence"]/r["video_id"]/"evidence_packet.json",r)
    assert adjudicate(r,p,answer(label,role))["label"]==expected


@pytest.mark.parametrize("kind", ["wrong_id","escape","outcome","invented_frame","invented_caption"])
def test_evidence_validation(case,kind):
    r=case["rows"][1];path=case["evidence"]/r["video_id"]/"evidence_packet.json"
    p=case["packet"]
    if kind=="wrong_id":p["video_id"]="h0000000001"
    if kind=="escape":p["frames"][0]["path"]=str(case["metadata"])
    if kind=="outcome":p["view_count"]=100
    dump(path,p)
    if kind in ("wrong_id","escape","outcome"):
        with pytest.raises(ValueError):evidence_packet(path,r)
    else:
        packet=evidence_packet(path,r);a=answer()
        a["evidence"]=[{"type":"visual","ref":"frame_99","detail":"x"}] if kind=="invented_frame" else [{"type":"caption","ref":"caption","detail":"not in transcript"}]
        with pytest.raises(ValueError):adjudicate(r,packet,a)


def test_judge_failure_preserves_U(case):
    def bad(*a):raise TimeoutError()
    extract(*args(case),evidence_root=case["evidence"],model="test",judge_fn=bad)
    rs=[json.loads(x) for x in (case["out"]/"predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rs[1]["label"]=="U" and "TimeoutError" in rs[1]["reason"]


def test_no_overwrite_and_no_artifact_directory_writes(case):
    extract(*args(case))
    with pytest.raises(FileExistsError):extract(*args(case))
    case["out"]=case["metadata"].parent/"new"
    with pytest.raises(ValueError):extract(*args(case))


def test_eval_is_separate_and_checks_prediction_hash(case):
    extract(*args(case));ref=case["out"].parent/"reference.json"
    dump(ref,{"labels":{"d0000000001":{"guest_present":1},"d0000000002":{"guest_present":0}}})
    before=sha(case["out"]/"predictions.jsonl")
    report=evaluate(case["out"],ref,case["split"])
    assert report["coverage"]==0 and report["accuracy_non_u"] is None and report["n_u"]==2
    assert sha(case["out"]/"predictions.jsonl")==before
    dump(ref,{"labels":{"h0000000001":{"guest_present":0}}})
    with pytest.raises(ValueError):evaluate(case["out"],ref,case["split"])
    (case["out"]/"predictions.jsonl").write_text('',encoding="utf-8")
    with pytest.raises(ValueError):evaluate(case["out"],ref,case["split"])


@pytest.mark.skip(reason="Provider execution is outside this provider-neutral patch")
def test_vision_request_uses_frozen_feature_and_only_projected_evidence(case,monkeypatch):
    import io
    from pathlib import Path
    from tools.feature_extractor import judge as adapter
    r=case["rows"][1]
    packet=evidence_packet(case["evidence"]/r["video_id"]/"evidence_packet.json",r)
    Path(packet["frames"][0]["path"]).write_bytes(b'\xff\xd8mock-jpeg')
    monkeypatch.setenv("ANTHROPIC_API_KEY","test-key-never-logged")
    def fake_open(request,timeout):
        body=json.loads(request.data)
        assert json.dumps(case["feature"],ensure_ascii=False) in body["system"]
        assert body["model"]=="test-model"
        content=body["messages"][0]["content"]
        assert any(x["type"]=="image" for x in content)
        projected=json.loads(content[-1]["text"])
        assert set(projected)=={"metadata","caption","caption_truncated"}
        assert projected["metadata"]==r
        return io.BytesIO(json.dumps({"stop_reason":"tool_use","model":"test-model","id":"test-response",
            "content":[{"type":"tool_use","name":"record_judgment","input":answer()}]}).encode())
    monkeypatch.setattr(adapter.urllib.request,"urlopen",fake_open)
    response,provenance=adapter.judge(packet,case["feature"],"test-model")
    assert response==answer() and provenance["response_id"]=="test-response"
    assert "test-key-never-logged" not in json.dumps(provenance)


TEXT_ONLY_IDS = {"tournament_format", "experiential_activity", "food_evaluation",
                 "work_or_character_focus", "challenge_activity"}
VISUAL_IDS = {"guest_present", "guest_conversation", "browse_and_comment", "eating_content",
              "external_content_reaction", "cooking_content", "on_location"}


def test_exact_frozen_routing():
    assert len(FEATURE_ROUTING) == 12
    assert {f for f,r in FEATURE_ROUTING.items() if r == TEXT_ONLY} == TEXT_ONLY_IDS
    assert {f for f,r in FEATURE_ROUTING.items() if r == TEXT_THEN_VISUAL} == VISUAL_IDS
    with pytest.raises(TypeError): FEATURE_ROUTING["guest_present"] = TEXT_ONLY


@pytest.mark.parametrize("feature", sorted(TEXT_ONLY_IDS | VISUAL_IDS))
@pytest.mark.parametrize("label", ["0", "1", "U"])
def test_text_routing_contract(feature, label):
    judgment = dict(feature_id=feature, label=label, confidence="medium", reason="Content evidence is insufficient.")
    before = dict(judgment)
    assert can_escalate_visual(judgment) == (label == "U" and feature in VISUAL_IDS)
    assert judgment == before


@pytest.mark.parametrize("invalid", [None, [], {},
    {"feature_id":"unknown"}, {"feature_id":[]}, {"label":0}, {"label":False}, {"label":"u"},
    {"confidence":"certain"}, {"confidence":None}, {"reason":" "}, {"reason":[]}, {"outcome":1}])
def test_invalid_text_judgment_fails_closed(invalid):
    valid = dict(feature_id="guest_present", label="U", confidence="low", reason="Insufficient participation evidence.")
    judgment = {**valid, **invalid} if isinstance(invalid,dict) and invalid else invalid
    with pytest.raises(ValueError): validate_text_judgment(judgment)
    with pytest.raises(ValueError): can_escalate_visual(judgment)


@pytest.mark.parametrize("field,value", [("freeze_status","draft"),("registry_version","other"),
    ("definitions_frozen_before_development",False)])
def test_frozen_registry_guard(case,field,value):
    registry=json.loads(case["registry"].read_text(encoding="utf-8"))
    registry["freeze_metadata"][field]=value
    dump(case["registry"],registry)
    with pytest.raises(ValueError): inputs(case["metadata"],case["split"],case["registry"])
