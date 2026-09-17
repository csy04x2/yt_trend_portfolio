"""Synthetic Discovery worksheet tests; no actual video judgments."""
import copy
import csv
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from feature_discovery.labeling import COLUMNS, export_worksheet, compile_worksheet
from feature_outcome.labels import load_labels


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(rows)


@pytest.fixture
def case(tmp_path):
    content, split, registry = [tmp_path/name for name in ("content.json","split.csv","registry.json")]
    feature=dict(feature_id="f",name="Example",version="0.1",scope="video",value_type="binary",
        definition="Example content property",inclusion_examples=["present"],exclusion_examples=["absent"],
        required_evidence=["content"],source="comment-derived",status="candidate")
    reg={"schema_version":"0.1","notice":"Synthetic", "features":[feature,dict(feature,feature_id="g")]}
    dump(registry,reg)
    split.write_text("video_id,split\na,discovery\nb,discovery\nc,discovery\nd,development\nh,holdout\n",encoding="utf-8")
    data=[dict(video_id=v,title="Discovery "+v,transcript="Allowed evidence") for v in "abc"]
    data += [dict(video_id="d",title="SECRET_DEVELOPMENT"),dict(video_id="h",title="SECRET_HOLDOUT")]
    dump(content,data)
    out=tmp_path/"worksheet"
    export_worksheet(content,split,registry,out)
    sheet=out/"worksheet.csv"
    with sheet.open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.DictReader(stream))
    return dict(content=content,split=split,registry=registry,reg=reg,sheet=sheet,rows=rows,out=tmp_path/"compiled")


def complete(case):
    for row in case["rows"]:
        row["label"]={"a":"0","b":"1","c":"U"}[row["video_id"]]
        row["notes"]="manual observation"
    write_rows(case["sheet"],case["rows"])


def compile_case(case):
    return compile_worksheet(case["sheet"],case["split"],case["registry"],case["out"])


def test_discovery_only_blank_worksheet(case):
    assert len(case["rows"])==6
    assert {r["video_id"] for r in case["rows"]}==set("abc")
    text=case["sheet"].read_text(encoding="utf-8-sig")
    assert "SECRET_DEVELOPMENT" not in text and "SECRET_HOLDOUT" not in text
    assert all(r["label"]==r["notes"]=="" for r in case["rows"])
    assert all(json.loads(r["feature_json"])["status"]=="candidate" for r in case["rows"])


def test_complete_labels_u_summary_and_downstream_contract(case):
    before=case["registry"].read_bytes();complete(case)
    summary=compile_case(case)
    labels=load_labels(case["out"]/"labels.json",case["reg"])
    assert labels=={v:{"f":x,"g":x} for v,x in zip("abc",(0,1,"U"))}
    for counts in summary["features"].values():
        assert counts==dict(n_total=3,n_0=1,n_1=1,n_u=1,judged_n=2,coverage=2/3,u_rate=1/3)
    assert case["registry"].read_bytes()==before
    assert "freeze_metadata" not in summary
    assert json.loads((case["out"]/"notes.json").read_text())["c"]["g"]=="manual observation"


@pytest.mark.parametrize("value",["","2","u","true","None"," 1"])
def test_invalid_labels(case,value):
    complete(case);case["rows"][0]["label"]=value;write_rows(case["sheet"],case["rows"])
    with pytest.raises(ValueError):compile_case(case)
    assert not case["out"].exists()


@pytest.mark.parametrize("mutation",["missing_pair","missing_video","duplicate","unknown","development","holdout","definition","evidence"])
def test_invalid_matrix(case,mutation):
    complete(case);rows=case["rows"]
    if mutation=="missing_pair":rows.pop()
    elif mutation=="missing_video":rows[:]=[r for r in rows if r["video_id"]!="c"]
    elif mutation=="duplicate":rows.append(copy.deepcopy(rows[0]))
    elif mutation=="unknown":rows[0]["feature_id"]="unknown"
    elif mutation in ("development","holdout"):rows[0]["video_id"]="d" if mutation=="development" else "h"
    elif mutation=="definition":rows[0]["feature_json"]="{}"
    else:
        evidence=json.loads(rows[0]["evidence_json"]);evidence["comments"]="forbidden"
        rows[0]["evidence_json"]=json.dumps(evidence)
    write_rows(case["sheet"],rows)
    with pytest.raises(ValueError):compile_case(case)


@pytest.mark.parametrize("field",["view_count","view_multiple","comments","reaction","audience"])
def test_forbidden_content_fails_before_export(case,field):
    data=json.loads(case["content"].read_text());data[0][field]=100;dump(case["content"],data)
    with pytest.raises(ValueError):export_worksheet(case["content"],case["split"],case["registry"],case["out"])
    assert not case["out"].exists()


def test_no_overwrite(case):
    with pytest.raises(FileExistsError):export_worksheet(case["content"],case["split"],case["registry"],case["sheet"].parent)
    complete(case);compile_case(case)
    with pytest.raises(FileExistsError):compile_case(case)
