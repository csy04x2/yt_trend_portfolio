"""Runner integration tests use only synthetic artifacts in pytest temp directories."""
import hashlib
import json

import pytest

from test_frozen_feature_outcome import case
from feature_outcome import runner
from feature_outcome.finding import build_findings
from feature_outcome.labels import load_labels, load_registry


def kwargs(case):
    return dict(registry=case["reg"], labels=case["labels"], split=case["split"],
                evidence=case["ev"], out=case["out"])


def test_development_artifacts_match_engine_and_preserve_inputs(case):
    inputs = {k: case[k].read_bytes() for k in ("reg", "labels", "split", "ev")}
    assert runner.main(case["args"][1:]) == 0
    assert {p.name for p in case["out"].iterdir()} == {"manifest.json", "findings.json"}
    findings = json.loads((case["out"] / "findings.json").read_text(encoding="utf-8"))
    registry = load_registry(case["reg"])
    videos = json.loads(case["ev"].read_text(encoding="utf-8"))["videos"][:10]
    labels = load_labels(case["labels"], registry, {v["video_id"] for v in videos})
    assert findings == build_findings(videos, labels, registry)
    leg = findings["calculations"]["feature_to_performance"][0]
    assert (leg["n"], leg["comparison_n"], leg["missingness"]["u_n"]) == (4, 4, 2)
    assert set(leg["comparison_ids"]) == {"d4", "d5", "d6", "d7"}
    manifest = json.loads((case["out"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runner_version"] == "0.1"
    assert manifest["engine_version"] == findings["version"]
    assert manifest["split"] == "development"
    assert manifest["registry_version"] == "A-v0.1"
    assert manifest["created_at"].endswith("+00:00")
    assert manifest["bootstrap_iterations"] is None and manifest["seed"] is None
    for key, content in inputs.items():
        assert case[key].read_bytes() == content
        assert manifest["input_sha256"][str(case[key].resolve())] == hashlib.sha256(content).hexdigest()
    second = case["root"] / "run2"
    runner.run(**{**kwargs(case), "out": second})
    assert (second / "findings.json").read_bytes() == (case["out"] / "findings.json").read_bytes()


@pytest.mark.parametrize("split_name", ["holdout", "discovery", "Development", "", None])
def test_other_splits_fail_before_input_access(case, split_name):
    case["reg"].unlink()
    with pytest.raises(ValueError, match="Development"):
        runner.run(**kwargs(case), split_name=split_name)
    assert not case["out"].exists()


@pytest.mark.parametrize("extra", [["--unseal-holdout"], ["--u-as-control"], ["--split-name", "holdout"]])
def test_cli_has_no_unsafe_options(case, extra):
    with pytest.raises(SystemExit) as error:
        runner.main(case["args"][1:] + extra)
    assert error.value.code == 2
    assert not case["out"].exists()


def test_existing_directory_never_overwritten(case):
    case["out"].mkdir(parents=True)
    marker = case["out"] / "findings.json"
    marker.write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        runner.run(**kwargs(case))
    assert marker.read_bytes() == b"preserve me"
    assert list(case["out"].iterdir()) == [marker]


@pytest.mark.parametrize("bad", ["plain", "spoof", "unfrozen"])
def test_requires_valid_frozen_envelope(case, bad):
    data = case["envelope"]
    if bad in ("plain", "spoof"):
        data = dict(data["registry"])
        if bad == "spoof":
            data["_envelope"] = case["envelope"]
    else:
        data["freeze_metadata"]["freeze_status"] = "draft"
    case["reg"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        runner.run(**kwargs(case))
    assert not case["out"].exists()


def test_quality_evidence_preserved_but_excluded_in_serialized_findings(case, monkeypatch):
    from feature_outcome.finding import AUDIENCE_METRICS, OBSERVATION_QUALITY_METRICS, SAMPLING_SENSITIVE_METRICS

    evidence = json.loads(case["ev"].read_text(encoding="utf-8"))
    expected = {}
    for i, video in enumerate(evidence["videos"][:10]):
        for metric in (*AUDIENCE_METRICS, *OBSERVATION_QUALITY_METRICS):
            video[metric] = i + 1
        expected[video["video_id"]] = dict(video)
    case["ev"].write_text(json.dumps(evidence), encoding="utf-8")
    before = case["ev"].read_bytes()
    original = runner.build_findings

    def checked(videos, *args, **kwargs):
        assert {v["video_id"] for v in videos} == set(expected)
        for video in videos:
            assert "comparison_ids" not in video
            for metric in (*AUDIENCE_METRICS, *OBSERVATION_QUALITY_METRICS, "view_multiple"):
                assert video[metric] == expected[video["video_id"]][metric]
        return original(videos, *args, **kwargs)

    monkeypatch.setattr(runner, "build_findings", checked)
    runner.run(**kwargs(case))
    out = json.loads((case["out"] / "findings.json").read_text(encoding="utf-8"))
    assert case["ev"].read_bytes() == before
    assert set(out["observable_audience_metrics"]) == set(AUDIENCE_METRICS)
    assert {c["behavior_metric"] for c in out["candidates"]} == set(AUDIENCE_METRICS)
    for metric in SAMPLING_SENSITIVE_METRICS:
        assert out["input_contract"]["metrics"][metric]["sampling_sensitive"] is True
    assert out["scope"]["split"] == "development"
    assert out["thresholds_applied"] == []
