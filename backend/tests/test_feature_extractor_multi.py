import base64
import copy
import inspect
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]))
from tools.feature_extractor.core import FEATURE_ROUTING, TEXT_THEN_VISUAL
from tools.feature_extractor.multi import extract_video, validate_judgments, definitions_by_id
from tools.feature_extractor import judge as adapter


@pytest.fixture
def data():
    features=[{"feature_id":fid,"definition":"Synthetic frozen definition for "+fid,
               "exclusion_examples":["External media only"]} for fid in FEATURE_ROUTING]
    metadata={"video_id":"synthetic01","title":"Content","description":"","duration_sec":100,"length_axis":"shorts"}
    caption="This person appears only inside external media."
    packet={"metadata":metadata,"caption":caption,"frames":[{"frame_id":"f1","timestamp_sec":1,
        "image_base64":base64.b64encode(b"\xff\xd8mock").decode()}]}
    return metadata,caption,features,packet


def judgments(features,label="U"):
    return [dict(feature_id=f["feature_id"],label=label,confidence="medium",reason="Supplied evidence is insufficient.") for f in features]


def test_single_text_and_bundled_visual_calls(data):
    m,c,fs,p=data; calls=[]
    def text(metadata,caption,features,model):
        calls.append(("text",len(features)))
        assert caption==c and metadata==m
        return judgments(features)
    def visual(packet,features,model):
        calls.append(("visual",len(features)))
        assert {f["feature_id"] for f in features}=={f for f,r in FEATURE_ROUTING.items() if r==TEXT_THEN_VISUAL}
        return judgments(features,"1")
    result=extract_video(m,c,fs,text_judge=text,visual_judge=visual,visual_packet=p)
    assert calls==[("text",12),("visual",7)]
    assert set(result["labels"])==set(FEATURE_ROUTING) and len(result["provenance"])==12
    for fid,route in FEATURE_ROUTING.items():
        assert result["labels"][fid]==("1" if route==TEXT_THEN_VISUAL else "U")
        assert result["provenance"][fid]["visual_escalated"]==(route==TEXT_THEN_VISUAL)


@pytest.mark.parametrize("label",["0","1"])
def test_text_decisions_survive_and_zero_visual_calls(data,label):
    m,c,fs,p=data
    def forbidden(*args):pytest.fail("Unexpected visual call")
    result=extract_video(m,c,fs,text_judgments=judgments(fs,label),visual_judge=forbidden,visual_packet=p)
    assert set(result["labels"].values())=={label}
    assert not any(v["visual_escalated"] for v in result["provenance"].values())


def test_text_only_u_does_not_call_visual(data):
    m,c,fs,p=data; batch=judgments(fs,"1")
    for item in batch:
        if FEATURE_ROUTING[item["feature_id"]]!=TEXT_THEN_VISUAL:item["label"]="U"
    def forbidden(*args):pytest.fail("TEXT_ONLY escalation")
    extract_video(m,c,fs,text_judgments=batch,visual_judge=forbidden,visual_packet=p)


def test_unrequested_visual_cannot_overwrite_text(data):
    m,c,fs,p=data; batch=judgments(fs);batch[0]["label"]="1"
    with pytest.raises(ValueError):
        extract_video(m,c,fs,text_judgments=batch,visual_packet=p,visual_judge=lambda *a:judgments(fs,"0"))


def test_visual_absence_stays_u_and_preserves_raw_provenance(data):
    m,c,fs,p=data
    result=extract_video(m,c,fs,text_judgments=judgments(fs),visual_packet=p,
        visual_judge=lambda packet,features,model:judgments(features,"0"))
    assert set(result["labels"].values())=={"U"}
    v=result["provenance"]["guest_present"]
    assert v["text"]["label"]=="U" and v["visual"]["label"]=="0" and v["final_label"]=="U"


def test_positive_exclusion_allows_visual_zero(data):
    m,c,fs,p=data
    def visual(packet,features,model):
        batch=judgments(features,"0")
        for item in batch:item["positive_exclusion"]={"exclusion":"External media only","caption_quote":c,
            "explanation":"The caption positively identifies the shown person as external media only."}
        return batch
    result=extract_video(m,c,fs,text_judgments=judgments(fs),visual_packet=p,visual_judge=visual)
    assert result["labels"]["guest_present"]=="0"


@pytest.mark.parametrize("problem",["missing","duplicate","unknown","label","confidence","reason","extra"])
@pytest.mark.parametrize("stage",["text","visual"])
def test_invalid_batches_fail_closed(data,problem,stage):
    m,c,fs,p=data
    def broken(features):
        batch=judgments(features)
        if problem=="missing":batch.pop()
        elif problem=="duplicate":batch.append(copy.deepcopy(batch[0]))
        elif problem=="unknown":batch[0]["feature_id"]="unknown"
        elif problem=="label":batch[0]["label"]=0
        elif problem=="confidence":batch[0]["confidence"]="certain"
        elif problem=="reason":batch[0]["reason"]=" "
        else:batch[0]["outcome"]=100
        return batch
    with pytest.raises(ValueError):
        if stage=="text":extract_video(m,c,fs,text_judgments=broken(fs))
        else:extract_video(m,c,fs,text_judgments=judgments(fs),visual_packet=p,
            visual_judge=lambda packet,features,model:broken(features))


@pytest.mark.parametrize("field",["view_count","view_multiple","audience","popularity","human_labels"])
def test_contamination_rejected_before_judge(data,field):
    m,c,fs,p=data;m[field]=1
    def forbidden(*args):pytest.fail("Contaminated call")
    with pytest.raises(ValueError):extract_video(m,c,fs,text_judge=forbidden)


def test_packet_extra_fields_and_wrong_video_rejected(data):
    m,c,fs,p=data;p["outcome"]=10
    with pytest.raises(ValueError):extract_video(m,c,fs,text_judgments=judgments(fs),visual_packet=p)
    del p["outcome"];p["metadata"]=dict(m,video_id="different")
    with pytest.raises(ValueError):extract_video(m,c,fs,text_judgments=judgments(fs),visual_packet=p)


@pytest.mark.parametrize("change",["missing","duplicate","unknown"])
def test_exact_definition_coverage(data,change):
    m,c,fs,p=data
    if change=="missing":fs.pop()
    elif change=="duplicate":fs.append(copy.deepcopy(fs[0]))
    else:fs[0]["feature_id"]="unknown"
    with pytest.raises(ValueError):definitions_by_id(fs)


def test_no_visual_evidence_retains_u_and_inputs_unchanged(data):
    before=copy.deepcopy(data);m,c,fs,p=data
    result=extract_video(m,c,fs,text_judgments=judgments(fs))
    assert set(result["labels"].values())=={"U"} and data==before


def mock_provider(monkeypatch, reply, requests):
    monkeypatch.setenv("ANTHROPIC_API_KEY","fake-test-key")
    def open_request(request,timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"stop_reason":"tool_use","content":[{"type":"tool_use",
            "name":"record_features","input":{"judgments":reply}}]}).encode())
    monkeypatch.setattr(adapter.urllib.request,"urlopen",open_request)


def test_text_provider_one_call_full_caption(data,monkeypatch):
    m,c,fs,p=data;c="a"*90000+"FULL_CAPTION_END";requests=[]
    mock_provider(monkeypatch,judgments(fs),requests)
    assert len(adapter.text_judge(m,c,fs,"mock-model"))==12
    assert len(requests)==1
    supplied=json.loads(requests[0]["messages"][0]["content"][0]["text"])
    assert supplied["caption"]==c


def test_visual_provider_one_subset_call(data,monkeypatch):
    m,c,fs,p=data;subset=[f for f in fs if FEATURE_ROUTING[f["feature_id"]]==TEXT_THEN_VISUAL];requests=[]
    mock_provider(monkeypatch,judgments(subset),requests)
    assert len(adapter.visual_judge(p,subset,"mock-model"))==7 and len(requests)==1
    assert any(x["type"]=="image" for x in requests[0]["messages"][0]["content"])


def test_provider_coverage_validation(data,monkeypatch):
    m,c,fs,p=data;requests=[]
    mock_provider(monkeypatch,judgments(fs)[:-1],requests)
    with pytest.raises(ValueError):adapter.text_judge(m,c,fs,"mock-model")


def test_guest_judge_backward_compatible(monkeypatch):
    assert list(inspect.signature(adapter.judge).parameters)==["packet","feature","model"]
    monkeypatch.setenv("ANTHROPIC_API_KEY","fake")
    answer={"label":"U","confidence":"low","role":"unclear","participation":"","evidence":[]}
    def open_request(request,timeout):
        body=json.loads(request.data)
        assert body["tools"][0]["name"]=="record_judgment"
        return io.BytesIO(json.dumps({"stop_reason":"tool_use","content":[{"type":"tool_use",
            "name":"record_judgment","input":answer}],"model":"mock","id":"r"}).encode())
    monkeypatch.setattr(adapter.urllib.request,"urlopen",open_request)
    result,provenance=adapter.judge({"frames":[],"metadata":{},"caption":None,"caption_truncated":False},
        {"feature_id":"guest_present"},"mock")
    assert result==answer and provenance["response_id"]=="r"
