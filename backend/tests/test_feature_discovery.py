"""Independent harness contracts, including leakage and DB preservation."""
import copy
import csv
import json
import pathlib
import sqlite3
import sys
from collections import Counter

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from feature_discovery.blind import CONTENT_FIELDS, validate_fields, validate_rows
from feature_discovery.data import load_content
from feature_discovery.export_blind_discovery import export
from feature_discovery.registry import validate_registry, validate_value
from feature_discovery.split_dataset import assignments, read_split, write_split


def videos(n=100):
    return [{"video_id": f"v{i:03}", "title": f"Example {i}",
             "length_axis": "shorts" if i < n // 2 else "long",
             "duration_sec": 60 if i < n // 2 else 1300} for i in range(n)]


def registry():
    return json.loads((ROOT / "feature_discovery/feature_registry/examples.json")
                      .read_text(encoding="utf-8"))


def test_split_reproducible_complete_and_seed_sensitive():
    rows = videos()
    result = assignments(rows)
    assert result == assignments(list(reversed(rows)))
    assert result != assignments(rows, seed=43)
    assert set(result) == {r["video_id"] for r in rows}
    assert Counter(result.values()) == {"discovery": 30, "development": 30, "holdout": 40}


def test_stratification_and_tiny_strata():
    rows = videos()
    result = assignments(rows)
    for axis in ("shorts", "long"):
        assert Counter(result[r["video_id"]] for r in rows if r["length_axis"] == axis) == {
            "discovery": 15, "development": 15, "holdout": 20}
    for r in rows:
        r["length_axis"] = r["video_id"]
    assert Counter(assignments(rows).values()) == {"discovery": 30, "development": 30, "holdout": 40}
    assert assignments(rows, stratify=False) == assignments(
        [{"video_id": r["video_id"]} for r in rows])


@pytest.mark.parametrize("size", [1, 2, 3, 7, 11, 31])
def test_small_global_rounding(size):
    result = assignments(videos(size))
    assert len(result) == size
    for name, ratio in [("discovery", .3), ("development", .3), ("holdout", .4)]:
        assert abs(list(result.values()).count(name) - size * ratio) < 1


def test_split_freeze_and_force(tmp_path):
    path = tmp_path / "split.csv"
    write_split(videos(), path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_split(videos(), path, seed=7)
    assert path.read_bytes() == before
    write_split(videos(), path, seed=7, force=True)
    assert read_split(path, videos()) == assignments(videos(), seed=7)


def test_invalid_and_drifted_membership(tmp_path):
    with pytest.raises(ValueError):
        assignments([{"video_id": "x"}, {"video_id": "x"}])
    with pytest.raises(ValueError):
        assignments([])
    path = tmp_path / "split.csv"
    write_split(videos(), path)
    with pytest.raises(ValueError):
        read_split(path, videos(99))
    path.write_text(path.read_text().replace("discovery", "invalid"), encoding="utf-8")
    with pytest.raises(ValueError):
        read_split(path, videos())


def test_export_both_formats_discovery_only(tmp_path):
    rows = videos(10)
    rows[0]["description"] = 'Korean 한글, "quote"\nnewline'
    split = tmp_path / "split.csv"
    write_split(rows, split)
    packet = export(rows, split, tmp_path / "packet")
    assert {r["video_id"] for r in packet} == {
        v for v, s in assignments(rows).items() if s == "discovery"}
    js = [json.loads(line) for line in (tmp_path / "packet/blind_discovery.jsonl")
          .read_text(encoding="utf-8").splitlines()]
    with (tmp_path / "packet/blind_discovery.csv").open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert js == packet
    assert [r["video_id"] for r in csv_rows] == [r["video_id"] for r in packet]
    assert all(set(r) == set(CONTENT_FIELDS) for r in csv_rows)
    with pytest.raises(FileExistsError):
        export(rows, split, tmp_path / "packet")


@pytest.mark.parametrize("field", [
    "view_count", "like_count", "comment_count", "views_per_day", "view_multiple_basis",
    "excess_views", "like_rate_multiple", "comment_rate_multiple", "baseline_median",
    "comparison_group", "unique_commenters", "participant_breadth", "repeat_share",
    "reply_count", "thread_depth", "timestamp_aggregation", "sentiment", "Reaction",
    "approval", "contention", "positive_ratio", "topic_counts_json", "labeled_ratio",
    "unknown_future_outcome",
])
def test_source_and_schema_leak_fail_closed(tmp_path, field):
    rows = videos(10)
    split = tmp_path / "split.csv"
    write_split(rows, split)
    # Reject even if the contaminated row is outside discovery.
    rows[0][field] = 123
    with pytest.raises(ValueError):
        export(rows, split, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    with pytest.raises(ValueError):
        export(videos(10), split, tmp_path / "bad", fields=CONTENT_FIELDS + (field,))


def test_nested_payload_and_json_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        validate_rows([{"video_id": "v", "playlist": {"view_count": 2}}])
    source = tmp_path / "source.json"
    source.write_text('[{"video_id":"v","view_count":123}]')
    with pytest.raises(ValueError):
        load_content(source)
    with pytest.raises(ValueError):
        validate_fields(["title"])


def test_sqlite_projection_and_no_mutation(tmp_path):
    path = tmp_path / "production.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
          CREATE TABLE videos(video_id TEXT PRIMARY KEY, title TEXT, duration_sec INTEGER,
                              comments_disabled INTEGER, comments_complete INTEGER);
          CREATE TABLE video_metrics(video_id TEXT, view_count INTEGER);
          INSERT INTO videos VALUES ('v','Example',60,0,1);
          INSERT INTO video_metrics VALUES ('v',999);
        """)
    before = path.read_bytes()
    assert load_content(path) == [{"video_id": "v", "title": "Example", "duration_sec": 60}]
    assert path.read_bytes() == before
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        load_content(missing)
    assert not missing.exists()


@pytest.mark.parametrize("source", ["human", "llm", "both", "comment-derived"])
def test_registry_valid_source(source):
    reg = registry()
    reg["features"][0]["source"] = source
    validate_registry(reg)


def test_valid_registry_and_value_contract():
    reg = registry()
    validate_registry(reg)
    feature = reg["features"][0]
    for val in (0, 1, "U"):
        validate_value(feature, val)
    for val in (True, 2, None, "1"):
        with pytest.raises(ValueError):
            validate_value(feature, val)
    feature["value_type"] = "numeric"
    validate_registry(reg)
    validate_value(feature, 1.5)
    feature["value_type"] = "categorical"
    with pytest.raises(ValueError):
        validate_registry(reg)
    feature["categories"] = ["interview", "solo"]
    validate_registry(reg)
    validate_value(feature, "solo")


@pytest.mark.parametrize("field", ["feature_id", "name", "version", "scope", "value_type",
    "definition", "inclusion_examples", "exclusion_examples", "required_evidence", "source", "status"])
def test_registry_missing_required(field):
    reg = registry()
    del reg["features"][0][field]
    with pytest.raises(ValueError):
        validate_registry(reg)


@pytest.mark.parametrize("field,value", [("source", "robot"), ("status", "approved"),
    ("value_type", "boolean"), ("inclusion_examples", "text"), ("required_evidence", []),
    ("version", 1), ("definition", " ")])
def test_registry_invalid_fields(field, value):
    reg = registry()
    reg["features"][0][field] = value
    with pytest.raises(ValueError):
        validate_registry(reg)


@pytest.mark.parametrize("bad", [[], {}, {"schema_version": "0.1", "notice": "x", "features": {}}])
def test_registry_invalid_shape(bad):
    with pytest.raises(ValueError):
        validate_registry(bad)


def test_registry_duplicate_and_extra_fields():
    reg = registry()
    reg["features"].append(copy.deepcopy(reg["features"][0]))
    with pytest.raises(ValueError):
        validate_registry(reg)
    reg = registry()
    reg["features"][0]["view_multiple"] = 4
    with pytest.raises(ValueError):
        validate_registry(reg)
