import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from feature_outcome.finding import build_findings


def frozen_registry():
    feature = {
        "feature_id": "f", "name": "Synthetic", "version": "A-v0.1", "scope": "video",
        "value_type": "categorical", "categories": ["0", "1", "U"], "definition": "x",
        "inclusion_examples": ["x"], "exclusion_examples": ["x"], "required_evidence": ["content"],
        "source": "human", "status": "testing",
    }
    envelope = {
        "registry": {"schema_version": "0.1", "features": [feature]},
        "freeze_metadata": {"registry_version": "A-v0.1", "dataset": "synthetic", "freeze_status": "frozen",
                            "definitions_frozen_before_development": True, "testing_feature_count": 1},
    }
    return {**envelope["registry"], "_envelope": envelope}


def data():
    # 1 group has higher behavior/performance; U rows are extreme to prove exclusion.
    videos = []
    labels = {}
    for i in range(10):
        lab = 1 if i < 4 else 0 if i < 8 else "U"
        like = (0.20 + i * 0.01) if lab == 1 else (0.05 + (i - 4) * 0.01) if lab == 0 else 99.0
        perf = (2.0 + i * 0.1) if lab == 1 else (0.8 + (i - 4) * 0.1) if lab == 0 else 99.0
        videos.append({"video_id": f"v{i}", "view_multiple": perf, "like_rate": like, "comment_rate": None})
        labels[f"v{i}"] = {"f": lab}
    return videos, labels


def test_builds_all_three_associations_and_chain_without_thresholds():
    videos, labels = data()
    out = build_findings(videos, labels, frozen_registry())
    assert out["version"] == "finding-engine-v0.1"
    assert out["scope"]["split"] == "development"
    assert out["scope"]["u_policy"] == "exclude; never control"
    assert out["thresholds_applied"] == []
    assert out["observable_audience_metrics"] == ["like_rate"]
    assert len(out["calculations"]["feature_to_performance"]) == 1
    assert len(out["calculations"]["feature_to_behavior"]) == 1
    assert len(out["calculations"]["behavior_to_performance"]) == 1
    assert len(out["candidates"]) == 1
    c = out["candidates"][0]
    assert c["n"] == 4 and c["comparison_n"] == 4
    assert c["missingness"]["u_n"] == 2
    assert c["coverage"] == pytest.approx(0.8)
    assert c["effect"]["feature_to_performance"]["estimate"] > 0
    assert c["effect"]["feature_to_behavior"]["estimate"] > 0
    assert c["effect"]["behavior_to_performance"]["estimate"] > 0
    assert c["direction_consistency"]["chain_consistent"] is True
    assert c["candidate_evidence"]["causal_claim"] is False
    assert "threshold" in c["candidate_evidence"]["basis"]
    assert set(c["outlier_loo_stability"]) == {
        "feature_to_performance", "feature_to_behavior", "behavior_to_performance"
    }


def test_u_is_not_control_and_is_absent_from_leg_ids():
    videos, labels = data()
    out = build_findings(videos, labels, frozen_registry())
    leg = out["calculations"]["feature_to_behavior"][0]
    assert leg["n"] == 4 and leg["comparison_n"] == 4
    assert leg["missingness"]["u_n"] == 2
    assert "v8" not in leg["target_ids"] + leg["comparison_ids"]
    assert "v9" not in leg["target_ids"] + leg["comparison_ids"]


def test_nondevelopment_and_plain_registry_are_rejected():
    videos, labels = data()
    with pytest.raises(ValueError, match="Development"):
        build_findings(videos, labels, frozen_registry(), split_name="holdout")
    with pytest.raises(ValueError, match="frozen registry"):
        build_findings(videos, labels, {"features": frozen_registry()["features"]})


def test_uncalculable_leg_stays_in_calculations_but_not_candidate():
    videos, labels = data()
    for v in videos:
        if labels[v["video_id"]]["f"] == 0:
            v["like_rate"] = None
    out = build_findings(videos, labels, frozen_registry())
    fb = out["calculations"]["feature_to_behavior"][0]
    assert fb["status"] == "insufficient_observed_groups"
    assert fb["effect"]["estimate"] is None
    assert out["candidates"] == []


def test_quality_metrics_never_enter_associations_or_chains_and_inputs_survive():
    import copy
    from feature_outcome.finding import AUDIENCE_METRICS, OBSERVATION_QUALITY_METRICS

    videos, labels = data()
    for i, video in enumerate(videos):
        for metric in AUDIENCE_METRICS:
            video[metric] = i + 1
    baseline = build_findings(videos, labels, frozen_registry())
    for i, video in enumerate(videos):
        for metric in OBSERVATION_QUALITY_METRICS:
            video[metric] = i + 100  # Valid, varying numbers must still be excluded.
    before = copy.deepcopy(videos)
    out = build_findings(videos, labels, frozen_registry())
    assert out == baseline
    assert videos == before
    assert set(out["observable_audience_metrics"]) == set(AUDIENCE_METRICS)
    assert {x["metric"] for x in out["calculations"]["feature_to_behavior"]} == set(AUDIENCE_METRICS)
    assert {x["behavior_metric"] for x in out["calculations"]["behavior_to_performance"]} == set(AUDIENCE_METRICS)
    assert {x["behavior_metric"] for x in out["candidates"]} == set(AUDIENCE_METRICS)
    for video in videos:
        for metric in AUDIENCE_METRICS:
            video.pop(metric)
    quality_only = build_findings(videos, labels, frozen_registry())
    assert quality_only["observable_audience_metrics"] == []
    assert quality_only["calculations"]["feature_to_behavior"] == []
    assert quality_only["calculations"]["behavior_to_performance"] == []
    assert quality_only["candidates"] == []


def test_serialized_metric_contract_tracks_sampling_and_expected_provenance():
    from feature_outcome.finding import OBSERVATION_QUALITY_METRICS, SAMPLING_SENSITIVE_METRICS

    videos, labels = data()
    out = json.loads(json.dumps(build_findings(videos, labels, frozen_registry())))
    contract = out["input_contract"]
    assert set(SAMPLING_SENSITIVE_METRICS) == {
        "unique_commenters", "participant_breadth", "threads", "replies_collected", "max_thread_size"
    }
    for metric in SAMPLING_SENSITIVE_METRICS:
        assert contract["metrics"][metric] == {
            "category": "audience_signal", "expected_source": "app.pipeline.observable.build",
            "association_eligible": True, "sampling_sensitive": True,
        }
    for metric in OBSERVATION_QUALITY_METRICS:
        assert contract["metrics"][metric]["category"] == "observation_quality"
        assert contract["metrics"][metric]["association_eligible"] is False
    assert contract["relative_performance"]["expected_source"] == "app.pipeline.observable.compare"
    assert contract["relative_performance"]["provenance_verified"] is False
    assert contract["metrics"]["like_rate"]["sampling_sensitive"] is None


def test_zero_feature_effect_still_emits_chain_without_magnitude_cutoff():
    videos = [dict(video_id=str(i), like_rate=x, view_multiple=x) for i, x in enumerate([1, 3, 1, 3])]
    labels = {str(i): {"f": int(i < 2)} for i in range(4)}
    out = build_findings(videos, labels, frozen_registry())
    assert out["thresholds_applied"] == []
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["effect"]["feature_to_behavior"]["estimate"] == 0
    assert out["candidates"][0]["effect"]["feature_to_performance"]["estimate"] == 0
