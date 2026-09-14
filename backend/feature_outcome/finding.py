"""Finding Engine v0.1: exploratory associations on frozen Development data only.

The engine links three observable association legs without making causal claims:
Content Feature -> Relative Performance, Content Feature -> Audience Behavior,
and Audience Behavior -> Relative Performance.  It applies no effect-size or
significance threshold; a chain candidate exists when all three leg estimates
are calculable from the Development split.
"""
from __future__ import annotations

import math
import statistics as st

VERSION = "finding-engine-v0.1"
OUTCOME = "view_multiple"

# Scalar, video-level audience observations already produced by observable.py.
# Collection/status strings and nested timestamp bins are intentionally not new
# metrics and are therefore not analyzed here.
AUDIENCE_METRICS = (
    "like_rate",
    "comment_rate",
    "unique_commenters",
    "author_missing_rate",
    "observed_repeat_share",
    "participant_breadth",
    "collection_to_api_ratio",
    "threads",
    "replies_collected",
    "api_replies_sampled_threads",
    "reply_rate",
    "reply_incomplete_threads",
    "reply_fetch_coverage",
    "max_thread_size",
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _direction(value):
    if value is None:
        return None
    return "positive" if value > 0 else "negative" if value < 0 else "zero"


def _median_diff(a, b):
    if not a or not b:
        return None
    return st.median(a) - st.median(b)


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for pos in order[i:j]:
            ranks[pos] = rank
        i = j
    return ranks


def _pearson(a, b):
    if len(a) < 2 or len(a) != len(b):
        return None
    ma, mb = st.mean(a), st.mean(b)
    da, db = [x - ma for x in a], [x - mb for x in b]
    va, vb = sum(x * x for x in da), sum(x * x for x in db)
    if va == 0 or vb == 0:
        return None
    return sum(x * y for x, y in zip(da, db)) / math.sqrt(va * vb)


def _spearman(a, b):
    return _pearson(_ranks(a), _ranks(b))


def _loo_summary(estimates, estimate):
    vals = [x for x in estimates if x is not None and math.isfinite(x)]
    if not vals:
        return {
            "loo_n": 0,
            "loo_range": None,
            "same_direction_share": None,
            "crosses_zero": None,
            "max_abs_shift": None,
        }
    direction = _direction(estimate)
    same = sum(_direction(x) == direction for x in vals) / len(vals) if direction else None
    lo, hi = min(vals), max(vals)
    return {
        "loo_n": len(vals),
        "loo_range": [lo, hi],
        "same_direction_share": same,
        "crosses_zero": lo <= 0 <= hi,
        "max_abs_shift": max(abs(x - estimate) for x in vals) if estimate is not None else None,
    }


def _binary_leg(videos, labels, feature_id, metric, relation):
    total = len(videos)
    target, comparison = [], []
    target_ids, comparison_ids = [], []
    n_u = n_missing_label = n_missing_metric = 0
    for video in videos:
        vid = video["video_id"]
        lab = labels.get(vid, {}).get(feature_id)
        if lab == "U":
            n_u += 1
            continue
        if lab not in (0, 1):
            n_missing_label += 1
            continue
        value = video.get(metric)
        if not _number(value):
            n_missing_metric += 1
            continue
        if lab == 1:
            target.append(value); target_ids.append(vid)
        else:
            comparison.append(value); comparison_ids.append(vid)
    estimate = _median_diff(target, comparison)
    loo = []
    if estimate is not None:
        for i in range(len(target)):
            loo.append(_median_diff(target[:i] + target[i + 1:], comparison))
        for i in range(len(comparison)):
            loo.append(_median_diff(target, comparison[:i] + comparison[i + 1:]))
    analyzed = len(target) + len(comparison)
    return {
        "relation": relation,
        "feature_id": feature_id,
        "metric": metric,
        "n": len(target),
        "comparison_n": len(comparison),
        "effect": {"estimate": estimate, "measure": "median_difference", "direction": _direction(estimate)},
        "coverage": analyzed / total if total else None,
        "missingness": {
            "eligible_n": total,
            "analyzed_n": analyzed,
            "u_n": n_u,
            "missing_label_n": n_missing_label,
            "missing_metric_n": n_missing_metric,
            "missing_total_n": total - analyzed,
        },
        "direction_consistency": _loo_summary(loo, estimate)["same_direction_share"],
        "outlier_loo_stability": _loo_summary(loo, estimate),
        "target_ids": target_ids,
        "comparison_ids": comparison_ids,
        "status": "calculable" if estimate is not None else "insufficient_observed_groups",
    }


def _continuous_leg(videos, behavior):
    total = len(videos)
    xs, ys, ids = [], [], []
    missing_behavior = missing_outcome = 0
    for video in videos:
        x, y = video.get(behavior), video.get(OUTCOME)
        if not _number(x):
            missing_behavior += 1
            continue
        if not _number(y):
            missing_outcome += 1
            continue
        xs.append(x); ys.append(y); ids.append(video["video_id"])
    estimate = _spearman(xs, ys)
    loo = []
    if estimate is not None:
        for i in range(len(xs)):
            loo.append(_spearman(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:]))
    return {
        "relation": "behavior_to_performance",
        "behavior_metric": behavior,
        "outcome": OUTCOME,
        "n": len(xs),
        "comparison_n": None,
        "effect": {"estimate": estimate, "measure": "spearman_rho", "direction": _direction(estimate)},
        "coverage": len(xs) / total if total else None,
        "missingness": {
            "eligible_n": total,
            "analyzed_n": len(xs),
            "missing_behavior_n": missing_behavior,
            "missing_outcome_n": missing_outcome,
            "missing_total_n": total - len(xs),
        },
        "direction_consistency": _loo_summary(loo, estimate)["same_direction_share"],
        "outlier_loo_stability": _loo_summary(loo, estimate),
        "video_ids": ids,
        "status": "calculable" if estimate is not None else "insufficient_variation_or_pairs",
    }


def _chain_candidate(videos, labels, feature_id, behavior, fp, fb, bp):
    rows1, rows0 = [], []
    total = len(videos)
    n_u = n_missing_label = n_missing_pair = 0
    for video in videos:
        lab = labels.get(video["video_id"], {}).get(feature_id)
        if lab == "U":
            n_u += 1
            continue
        if lab not in (0, 1):
            n_missing_label += 1
            continue
        if not (_number(video.get(behavior)) and _number(video.get(OUTCOME))):
            n_missing_pair += 1
            continue
        (rows1 if lab == 1 else rows0).append(video["video_id"])
    n, comparison_n = len(rows1), len(rows0)
    analyzed = n + comparison_n
    fpd = fp["effect"]["direction"]
    fbd = fb["effect"]["direction"]
    bpd = bp["effect"]["direction"]
    composed = None
    if fbd in ("positive", "negative") and bpd in ("positive", "negative"):
        composed = "positive" if fbd == bpd else "negative"
    consistent = fpd == composed if fpd in ("positive", "negative") and composed else None
    leg_loo = {
        "feature_to_performance": fp["outlier_loo_stability"],
        "feature_to_behavior": fb["outlier_loo_stability"],
        "behavior_to_performance": bp["outlier_loo_stability"],
    }
    same = [x["same_direction_share"] for x in leg_loo.values() if x["same_direction_share"] is not None]
    return {
        "candidate_id": f"{feature_id}::{behavior}::{OUTCOME}",
        "feature_id": feature_id,
        "behavior_metric": behavior,
        "outcome": OUTCOME,
        "n": n,
        "comparison_n": comparison_n,
        "effect": {
            "feature_to_performance": fp["effect"],
            "feature_to_behavior": fb["effect"],
            "behavior_to_performance": bp["effect"],
        },
        "coverage": analyzed / total if total else None,
        "missingness": {
            "eligible_n": total,
            "analyzed_n": analyzed,
            "u_n": n_u,
            "missing_label_n": n_missing_label,
            "missing_behavior_or_outcome_n": n_missing_pair,
            "missing_total_n": total - analyzed,
        },
        "direction_consistency": {
            "feature_to_performance": fpd,
            "feature_to_behavior": fbd,
            "behavior_to_performance": bpd,
            "composed_feature_behavior_performance": composed,
            "chain_consistent": consistent,
            "loo_same_direction_share_min": min(same) if same else None,
        },
        "outlier_loo_stability": leg_loo,
        "candidate_evidence": {
            "feature_to_performance_calculable": fp["status"] == "calculable",
            "feature_to_behavior_calculable": fb["status"] == "calculable",
            "behavior_to_performance_calculable": bp["status"] == "calculable",
            "basis": "all three association estimates are calculable; no effect-size or significance threshold applied",
            "causal_claim": False,
        },
        "allowed_claim": "exploratory association only; not a causal conclusion or performance guarantee",
    }


def build_findings(videos, labels, registry, split_name="development"):
    """Return calculations and chain candidates for a frozen Development split.

    ``videos`` must already be projected by frozen.prepare; this function has no
    file/DB access and never accepts discovery or holdout analysis.
    """
    if split_name != "development":
        raise ValueError("Finding Engine v0.1 only analyzes the Development split")
    if "_envelope" not in registry:
        raise ValueError("Finding Engine v0.1 requires a validated frozen registry envelope")
    feature_ids = [f["feature_id"] for f in registry["features"]]
    for video in videos:
        vid = video["video_id"]
        if set(labels.get(vid, {})) != set(feature_ids):
            raise ValueError("Every Development video needs every frozen feature label")

    available_behaviors = [m for m in AUDIENCE_METRICS if any(_number(v.get(m)) for v in videos)]
    fp = [_binary_leg(videos, labels, fid, OUTCOME, "feature_to_performance") for fid in feature_ids]
    fb = [_binary_leg(videos, labels, fid, metric, "feature_to_behavior")
          for fid in feature_ids for metric in available_behaviors]
    bp = [_continuous_leg(videos, metric) for metric in available_behaviors]

    fp_by = {x["feature_id"]: x for x in fp}
    fb_by = {(x["feature_id"], x["metric"]): x for x in fb}
    bp_by = {x["behavior_metric"]: x for x in bp}
    candidates = []
    for fid in feature_ids:
        for metric in available_behaviors:
            legs = fp_by[fid], fb_by[(fid, metric)], bp_by[metric]
            if all(x["status"] == "calculable" for x in legs):
                candidates.append(_chain_candidate(videos, labels, fid, metric, *legs))

    freeze = registry["_envelope"].get("freeze_metadata", {})
    return {
        "version": VERSION,
        "scope": {"split": "development", "feature_registry_version": freeze.get("registry_version"),
                  "u_policy": "exclude; never control", "outcome": OUTCOME},
        "association_only": True,
        "thresholds_applied": [],
        "candidate_rule": "emit when all three association estimates are calculable; no magnitude/significance cutoff",
        "observable_audience_metrics": available_behaviors,
        "calculations": {
            "feature_to_performance": fp,
            "feature_to_behavior": fb,
            "behavior_to_performance": bp,
        },
        "candidates": candidates,
    }
