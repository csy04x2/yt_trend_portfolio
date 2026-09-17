"""Human freeze tests use synthetic registries only; no experiment inputs."""
import copy
import hashlib
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from feature_discovery.freeze import freeze_registry, main
from feature_discovery.registry import SCHEMA
from feature_outcome.labels import load_registry


@pytest.fixture
def case(tmp_path):
    feature = dict(feature_id="f", name="Synthetic", version="0.1", scope="video",
        value_type="binary", definition="Content property", inclusion_examples=["present"],
        exclusion_examples=["absent"], required_evidence=["transcript"],
        source="comment-derived", status="candidate")
    registry = {"schema_version": "0.1", "notice": "Synthetic",
                "features": [feature, dict(feature, feature_id="g", status="testing")]}
    source, approval, out = [tmp_path / n for n in ("source.json", "approval.json", "frozen.json")]
    source.write_text(json.dumps(registry), encoding="utf-8")
    decision = dict(selected_feature_ids=["f"], approved_by="Synthetic reviewer",
        registry_version="human-v1", dataset="synthetic",
        definitions_frozen_before_development=True,
        source_registry_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    approval.write_text(json.dumps(decision), encoding="utf-8")
    return source, approval, out, registry, decision


def write_approval(case, decision):
    case[1].write_text(json.dumps(decision), encoding="utf-8")


def test_cli_freeze_accepted_by_existing_loader_and_preserves_source(case):
    source, approval, out, registry, decision = case
    before = {p: p.read_bytes() for p in (source, approval)}
    assert main(["--registry", str(source), "--approval", str(approval), "--output", str(out)]) == 0
    loaded = load_registry(out)
    assert loaded["features"] == [{**registry["features"][0], "status": "testing",
                                 "value_type": "categorical", "categories": ["0", "1", "U"]}]
    # g is already testing but is NOT implicitly included.
    envelope = loaded["_envelope"]
    assert envelope["freeze_metadata"] == dict(registry_version="human-v1", dataset="synthetic",
        freeze_status="frozen", definitions_frozen_before_development=True, testing_feature_count=1)
    assert envelope["freeze_provenance"]["approved_by"] == decision["approved_by"]
    assert envelope["freeze_provenance"]["selected_feature_ids"] == ["f"]
    assert envelope["freeze_provenance"]["input_sha256"] == {
        str(p.resolve()): hashlib.sha256(content).hexdigest() for p, content in before.items()}
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("selection", [[], ["unknown"], ["f", "f"], "f", [None], [1], [" "]])
def test_invalid_selection_leaves_no_output(case, selection):
    decision = dict(case[4], selected_feature_ids=selection)
    write_approval(case, decision)
    with pytest.raises(ValueError):
        freeze_registry(*case[:3])
    assert not case[2].exists()


@pytest.mark.parametrize("key,value", [
    ("definitions_frozen_before_development", False), ("definitions_frozen_before_development", 1),
    ("registry_version", " "), ("dataset", None), ("approved_by", ""),
    ("source_registry_sha256", "0" * 64), ("selection_rule", "coverage > 0.8"),
    ("labels", "discovery-labels.json"), ("summary", "summary.json"),
])
def test_invalid_or_automatic_approval_rejected(case, key, value):
    write_approval(case, {**case[4], key: value})
    with pytest.raises(ValueError):
        freeze_registry(*case[:3])
    assert not case[2].exists()


@pytest.mark.parametrize("bad", ["extra", "status", "missing", "duplicate_id", "numeric", "categories", "scope", "json"])
def test_malformed_or_incompatible_source_rejected(case, bad):
    registry = copy.deepcopy(case[3])
    feature = registry["features"][0]
    if bad == "extra": feature["provenance"] = "unsupported"
    elif bad == "status": feature["status"] = "preserve"
    elif bad == "missing": del feature["definition"]
    elif bad == "duplicate_id": registry["features"].append(dict(feature, version="another"))
    elif bad == "numeric": feature["value_type"] = "numeric"
    elif bad == "categories": feature.update(value_type="categorical", categories=["a", "b"])
    elif bad == "scope": feature["scope"] = "channel"
    case[0].write_text("{" if bad == "json" else json.dumps(registry), encoding="utf-8")
    write_approval(case, {**case[4], "source_registry_sha256": hashlib.sha256(case[0].read_bytes()).hexdigest()})
    with pytest.raises(ValueError):
        freeze_registry(*case[:3])
    assert not case[2].exists()


@pytest.mark.parametrize("input_index", [0, 1])
def test_duplicate_json_keys_rejected(case, input_index):
    p = case[input_index]
    text = p.read_text(encoding="utf-8")
    key = "notice" if input_index == 0 else "approved_by"
    p.write_text('{"' + key + '": "duplicate",' + text[1:], encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        freeze_registry(*case[:3])
    assert not case[2].exists()


def test_no_overwrite_or_input_mutation(case):
    freeze_registry(*case[:3])
    before = case[2].read_bytes()
    with pytest.raises(FileExistsError):
        freeze_registry(*case[:3])
    assert case[2].read_bytes() == before
    source_before = case[0].read_bytes()
    with pytest.raises(FileExistsError):
        freeze_registry(case[0], case[1], case[0])
    assert case[0].read_bytes() == source_before


def test_reads_only_registry_approval_and_schema_no_labels_or_holdout(case, monkeypatch):
    # No labels, statistics, split, content or outcome files even exist here.
    allowed = {case[0].resolve(), case[1].resolve(), SCHEMA.resolve(), case[2].resolve()}
    original = pathlib.Path.open
    seen = set()

    def guarded(path, *args, **kwargs):
        assert path.resolve() in allowed, "Unexpected data access: " + str(path)
        seen.add(path.resolve())
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", guarded)
    freeze_registry(*case[:3])
    assert seen == allowed


@pytest.mark.parametrize("flag", ["--labels", "--summary", "--auto-select", "--unseal-holdout"])
def test_cli_refuses_statistics_and_holdout_options(case, flag):
    with pytest.raises(SystemExit) as error:
        main(["--registry", str(case[0]), "--approval", str(case[1]), "--output", str(case[2]), flag])
    assert error.value.code == 2
    assert not case[2].exists()


def test_categorical_source_and_explicit_selection_order(case):
    registry = case[3]
    registry["features"][0].update(value_type="categorical", categories=["0", "1", "U"])
    case[0].write_text(json.dumps(registry), encoding="utf-8")
    write_approval(case, {**case[4], "selected_feature_ids": ["g", "f"],
        "source_registry_sha256": hashlib.sha256(case[0].read_bytes()).hexdigest()})
    freeze_registry(*case[:3])
    loaded = load_registry(case[2])
    assert [f["feature_id"] for f in loaded["features"]] == ["g", "f"]
    assert loaded["_envelope"]["freeze_metadata"]["testing_feature_count"] == 2
