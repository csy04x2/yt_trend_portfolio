"""Synthetic integration contracts; never reads a real experiment or database."""
import copy
import csv
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from feature_outcome import __main__ as cli
from feature_outcome import frozen
from feature_outcome.labels import load_labels, load_registry, validate_labels
from feature_outcome.outcome import feature_outcome


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    monkeypatch.setattr(frozen, "OUTPUT_ROOT", root)
    feature = dict(feature_id="f", name="Synthetic", version="A-v0.1", scope="video",
                   value_type="categorical", categories=["0", "1", "U"], definition="Synthetic definition",
                   inclusion_examples=["present"], exclusion_examples=["absent"],
                   required_evidence=["content"], source="human", status="testing")
    envelope = {
        "registry": {"schema_version": "0.1", "notice": "Synthetic", "features": [feature]},
        "feature_metadata": {"f": {"dimension": "test", "source": "human_derived", "provenance": ["original name"]}},
        "freeze_metadata": {"registry_version": "A-v0.1", "dataset": "synthetic",
                            "freeze_status": "frozen", "definitions_frozen_before_development": True,
                            "testing_feature_count": 1},
    }
    reg, ev, labels, split = [tmp_path / n for n in ("registry.json", "evidence.json", "labels.json", "split.csv")]
    dump(reg, envelope)
    vs = [dict(video_id="d"+str(i), title="Synthetic", length_axis="shorts", duration_sec=30,
               published_at="2026-01-01T00:00:00Z", view_count=100+i, view_multiple=1+i/10,
               like_rate=None, comment_rate=None) for i in range(10)]
    # Nonselected payloads cannot be processed by numeric aggregate functions.
    vs += [{"video_id": "h", "view_count": "DO NOT AGGREGATE"},
           {"video_id": "s", "view_count": "DO NOT AGGREGATE"}]
    vs[0]["comparison_ids"] = ["h"]
    dump(ev, {"channel": "synthetic", "videos": vs, "summary": {"secret": "held-out cached result"}})
    dump(labels, {"labels": {**{"d"+str(i): {"f": "1" if i<4 else "0" if i<8 else "U"} for i in range(10)},
                            "h": {"not_in_registry": "do not inspect"}, "s": {"f": "U"}}})
    with split.open("w", encoding="utf-8", newline="") as stream:
        w=csv.writer(stream);w.writerow(["video_id", "split", "seed", "created_at"])
        w.writerows((v["video_id"], "holdout" if v["video_id"]=="h" else "discovery" if v["video_id"]=="s" else "development", 42, "2026-01-01T00:00:00Z") for v in vs)
    out=root/"run1"
    args=["run", "--evidence", str(ev), "--registry", str(reg), "--labels", str(labels),
          "--split", str(split), "--out", str(out)]
    return dict(root=root, reg=reg, ev=ev, labels=labels, split=split, out=out, args=args, envelope=envelope)


def test_envelope_and_string_labels_preserve_provenance_and_files(case):
    before={k:case[k].read_bytes() for k in ("reg", "labels")}
    reg=load_registry(case["reg"])
    assert reg["_envelope"]==case["envelope"]
    labs=load_labels(case["labels"], reg, {"d0", "d4", "d8"})
    assert labs=={"d0":{"f":1},"d4":{"f":0},"d8":{"f":"U"}}
    assert all(case[k].read_bytes()==v for k,v in before.items())


@pytest.mark.parametrize("value", [True, False, 0.0, 1.0, None, "", "unknown", 2])
def test_label_values_reject_coercion(value):
    assert validate_labels({"v":{"f":value}}, {"features":[{"feature_id":"f"}]})


def test_development_scoped_before_every_aggregate_and_export(case, monkeypatch):
    seen=[]
    for name in ("flag_breakouts", "recompute_multiples", "monthly_cohorts", "feature_outcome"):
        original=getattr(cli,name)
        def checked(videos, *args, _fn=original, **kwargs):
            assert {v["video_id"] for v in videos}=={"d"+str(i) for i in range(10)}
            seen.append(_fn.__name__)
            return _fn(videos,*args,**kwargs)
        monkeypatch.setattr(cli,name,checked)
    exported=case["out"]/"evidence.json"
    assert cli.main(case["args"]+["--evidence-out",str(exported)])==0
    result=json.loads((case["out"]/"results.json").read_text(encoding="utf-8"))["outcome"][0]
    assert result["all"]["n1"]==4 and result["all"]["n0"]==4 and result["all"]["n_u"]==2
    assert result["u_as_control"] is False
    assert set(seen)=={"flag_breakouts","recompute_multiples","monthly_cohorts","feature_outcome"}
    d=json.loads(exported.read_text(encoding="utf-8"))
    assert "summary" not in d and "comparison_ids" not in d["videos"][0]
    assert set(d["feature_outcome"]["labels"])=={"d"+str(i) for i in range(10)}
    with (case["out"]/"breakout.csv").open() as stream:
        assert {r["split"] for r in csv.DictReader(stream)}=={"development"}
    assert not (case["out"]/"report.md").exists()  # prototype UI not repurposed


@pytest.mark.parametrize("flag", ["--u-as-control", "--split-name"])
def test_rejection_precedes_evidence_and_labels_access(case, monkeypatch, flag):
    case["ev"].unlink();case["labels"].unlink()
    def forbidden(*args,**kwargs):raise AssertionError("aggregate called")
    monkeypatch.setattr(cli,"flag_breakouts",forbidden)
    extra=[flag] if flag=="--u-as-control" else [flag,"holdout"]
    assert cli.main(case["args"]+extra)==2
    assert not case["out"].exists()


def test_explicit_unseal_only_exposes_selected_holdout(case):
    d=json.loads(case["ev"].read_text(encoding="utf-8"));h=copy.deepcopy(d["videos"][0]);h["video_id"]="h"
    d["videos"][-2]=h;dump(case["ev"],d)
    labs=json.loads(case["labels"].read_text(encoding="utf-8"));labs["labels"]["h"]={"f":"U"};dump(case["labels"],labs)
    assert cli.main(case["args"]+["--split-name","holdout","--unseal-holdout"])==0
    result=json.loads((case["out"]/"results.json").read_text(encoding="utf-8"))["outcome"][0]
    assert result["all"]["n_u"]==1 and result["all"]["n0"]==0
    assert json.loads((case["out"]/"manifest.json").read_text(encoding="utf-8"))["unseal_holdout"] is True


def test_unknown_counts_include_missing_outcomes_and_exclusion():
    vs=[{"video_id":x,"view_multiple":None} for x in "abc"]
    labels={"a":{"f":"U"},"b":{"f":"U"},"c":{}}
    flags={x:{"breakout":int(x=="b")} for x in "abc"};split={x:"development" for x in "abc"}
    r=feature_outcome(vs,labels,flags,split,frozen_experiment=True)[0]
    assert r["all"]["n_u"]==2 and r["excluded"]["n_u"]==1
    assert r["all"]["n_missing_label"]==1 and r["all"]["n0"]==0
    with pytest.raises(ValueError):feature_outcome(vs,labels,flags,split,frozen_experiment=True,u_as_control=True)


def test_output_must_be_new_and_separate(case):
    args=case["args"][:-1]+[str(case["root"].parent/"prototype")]
    assert cli.main(args)==2
    assert cli.main(case["args"]+["--evidence-out",str(case["ev"])])==2
    assert cli.main(case["args"])==0
    old=(case["out"]/"results.json").read_bytes()
    assert cli.main(case["args"])==2
    assert (case["out"]/"results.json").read_bytes()==old


@pytest.mark.parametrize("bad", ["duplicate_split", "missing_video", "missing_label", "missing_feature"])
def test_incomplete_inputs_fail_before_outputs(case,bad):
    if bad=="duplicate_split":
        with case["split"].open("a") as f:f.write("d0,development,42,2026-01-01T00:00:00Z\n")
    elif bad=="missing_video":
        d=json.loads(case["ev"].read_text(encoding="utf-8"));d["videos"].pop(0);dump(case["ev"],d)
    else:
        d=json.loads(case["labels"].read_text(encoding="utf-8"))
        if bad=="missing_label":del d["labels"]["d0"]
        else:d["labels"]["d0"]={}
        dump(case["labels"],d)
    assert cli.main(case["args"])==2
    assert not case["out"].exists()


def test_plain_registry_keeps_exploratory_cli(case):
    dump(case["reg"],case["envelope"]["registry"])
    d=json.loads(case["ev"].read_text(encoding="utf-8"));d["videos"]=d["videos"][:10];dump(case["ev"],d)
    labs=json.loads(case["labels"].read_text(encoding="utf-8"));labs["labels"].pop("h");labs["labels"].pop("s");dump(case["labels"],labs)
    assert cli.main(case["args"]+["--u-as-control"])==0
    assert (case["out"]/"report.md").is_file()
    r=json.loads((case["out"]/"results.json").read_text(encoding="utf-8"))["outcome"][0]
    assert r["all"]["n0"]==6


def test_plain_registry_can_explicitly_select_frozen_mode(case):
    dump(case["reg"],case["envelope"]["registry"])
    assert cli.main(case["args"]+["--frozen-experiment"])==0
    assert (case["out"]/"manifest.json").is_file()


def test_outcome_does_not_access_nonselected_values():
    class Sealed(dict):
        def get(self, key, *args):
            if key != "video_id":raise AssertionError("held-out field accessed")
            return super().get(key,*args)
        def __getitem__(self, key):
            if key != "video_id":raise AssertionError("held-out field accessed")
            return super().__getitem__(key)
    vs=[{"video_id":"d","view_multiple":1},Sealed(video_id="h")]
    result=feature_outcome(vs,{"d":{"f":1}},{"d":{"breakout":0}},
                           {"d":"development","h":"holdout"},frozen_experiment=True)
    assert result[0]["all"]["n1"]==1
