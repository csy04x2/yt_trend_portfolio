"""Pure descriptive Feature → Performance evaluation; no I/O or integrations."""
import math
import random
from collections import Counter
from statistics import median


BOOTSTRAP_RESAMPLES = 5000


def _percentile(ordered, probability):
    """Linearly interpolate at (n - 1) * probability."""
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap(group1, group0, seed):
    rng = random.Random(seed)
    differences = sorted(
        median(rng.choices(group1, k=len(group1)))
        - median(rng.choices(group0, k=len(group0)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return _percentile(differences, .025), _percentile(differences, .975)


def _loo_stable(group1, group0, effect):
    if effect == 0:
        return False
    for group, other, positive in ((group1, group0, True), (group0, group1, False)):
        if len(group) <= 1:
            continue  # Removing this row leaves an undefined comparison.
        for index in range(len(group)):
            remaining = group[:index] + group[index + 1:]
            difference = median(remaining) - median(other)
            if not positive:
                difference = -difference
            if (effect > 0 and difference <= 0) or (effect < 0 and difference >= 0):
                return False
    return True


def evaluate_findings(rows, *, seed=42):
    """Evaluate one feature's rows without changing them.

    Invalid labels, non-finite metrics and malformed row identities fail closed.
    Missing groups yield None statistics and neutral direction. Reasons list
    failed FINDING gates, even when the weaker CANDIDATE gates pass.
    """
    rows = list(rows)
    groups = {"1": [], "0": []}
    axes = {"1": Counter(), "0": Counter()}
    n_u = 0
    seen = set()
    for row in rows:
        label = row["feature_label"]
        if not isinstance(label, str) or label not in ("0", "1", "U"):
            raise ValueError("Invalid feature_label; expected string 0, 1 or U")
        vid, axis, value = row["video_id"], row["length_axis"], row["view_multiple"]
        if not isinstance(vid, str) or not vid.strip() or vid in seen:
            raise ValueError("Expected unique non-empty video_id")
        seen.add(vid)
        if not isinstance(axis, str) or not axis.strip():
            raise ValueError("Expected non-empty length_axis")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("Expected finite view_multiple or None")
        if label == "U":
            n_u += 1
            continue
        if value is not None:
            groups[label].append(value)
            axes[label][axis] += 1
    # Sorting makes results invariant to input order as well as repeatable.
    group1, group0 = sorted(groups["1"]), sorted(groups["0"])
    n1, n0, n_total = len(group1), len(group0), len(rows)
    coverage = (n1 + n0) / n_total if n_total else 0.0
    median_1 = median(group1) if n1 else None
    median_0 = median(group0) if n0 else None
    effect = median_1 - median_0 if n1 and n0 else None
    low, high = _bootstrap(group1, group0, seed) if effect is not None else (None, None)
    stable = _loo_stable(group1, group0, effect) if effect is not None else False
    all_axes = sorted(set(axes["1"]) | set(axes["0"]))
    concentrated = len(axes["1"]) == 1 and len(all_axes) > 1
    reasons = []
    if n1 < 10: reasons.append("n1_below_10")
    if n0 < 10: reasons.append("n0_below_10")
    if coverage < .40: reasons.append("coverage_below_0.40")
    if effect is None or abs(effect) < .10: reasons.append("effect_below_0.10_or_unavailable")
    if low is None or not (low > 0 or high < 0): reasons.append("bootstrap_ci_includes_zero_or_unavailable")
    if not stable: reasons.append("loo_direction_unstable")
    if concentrated: reasons.append("axis_concentrated")
    candidate = n1 >= 5 and n0 >= 5 and effect is not None and abs(effect) >= .10
    return {
        "status": "FINDING" if not reasons else "CANDIDATE" if candidate else "INSUFFICIENT",
        "direction": "positive" if effect is not None and effect > 0 else "negative" if effect is not None and effect < 0 else "neutral",
        "n_total": n_total, "n1": n1, "n0": n0, "n_u": n_u, "coverage": coverage,
        "median_1": median_1, "median_0": median_0, "effect": effect,
        "bootstrap_ci_low": low, "bootstrap_ci_high": high,
        "loo_direction_stable": stable, "reasons": reasons,
        "axis_diagnostics": {
            "positive_counts": dict(sorted(axes["1"].items())),
            "control_counts": dict(sorted(axes["0"].items())),
            "evaluable_axes": all_axes, "axis_concentrated": concentrated,
        },
        "bootstrap_seed": seed, "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    }
