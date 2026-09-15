import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from backend.feature_discovery.finding_engine import evaluate_findings


def population(positive, control, unknown=()):
    return [dict(video_id=str(i), feature_label=label, length_axis="long", view_multiple=value)
            for i, (label, value) in enumerate(
                [("1", v) for v in positive] + [("0", v) for v in control] + [("U", v) for v in unknown])]


def test_u_and_missing_are_excluded_not_control():
    result = evaluate_findings(population([3]*10+[None], [1]*10+[None], [100, -100, None]))
    assert (result["n_total"], result["n1"], result["n0"], result["n_u"]) == (25,10,10,3)
    assert result["coverage"] == .8
    assert (result["median_1"], result["median_0"], result["effect"]) == (3,1,2)
    assert result["status"] == "FINDING"


def test_seven_positives_only_candidate():
    result = evaluate_findings(population([3]*7, [1]*12))
    assert result["status"] == "CANDIDATE"
    assert "n1_below_10" in result["reasons"]


def test_bootstrap_crossing_zero_blocks_finding():
    result = evaluate_findings(population([0]*5+[4]*5, [1]*10))
    assert result["effect"] == 1
    assert result["bootstrap_ci_low"] < 0 < result["bootstrap_ci_high"]
    assert "bootstrap_ci_includes_zero_or_unavailable" in result["reasons"]
    assert result["status"] == "CANDIDATE"


def test_axis_concentration():
    rows = population([3]*10, [1]*10)
    rows[-1]["length_axis"] = "shorts"
    result = evaluate_findings(rows)
    assert result["status"] == "CANDIDATE"
    assert result["reasons"] == ["axis_concentrated"]
    assert result["axis_diagnostics"]["positive_counts"] == {"long":10}
    assert result["axis_diagnostics"]["evaluable_axes"] == ["long","shorts"]


def test_loo_sign_flip_blocks_finding():
    result = evaluate_findings(population([0]*5+[2]*5, [.5]*10))
    # Removing a positive value 2 changes median difference from .5 to -.5.
    assert result["effect"] == .5
    assert not result["loo_direction_stable"]
    assert "loo_direction_unstable" in result["reasons"]
    assert result["status"] != "FINDING"


@pytest.mark.parametrize("positive,control,direction", [(3,1,"positive"),(1,3,"negative")])
def test_strong_finding(positive,control,direction):
    result = evaluate_findings(population([positive]*12,[control]*12))
    assert result["status"] == "FINDING" and result["reasons"] == []
    assert result["direction"] == direction
    assert result["loo_direction_stable"]


@pytest.mark.parametrize("positive,control", [([3]*4,[1]*20),([1]*10,[1]*10),([],[]),([1]*10,[])])
def test_insufficient(positive,control):
    assert evaluate_findings(population(positive,control))["status"] == "INSUFFICIENT"


@pytest.mark.parametrize("label", [0,1,None,True,"u","unknown",[]])
def test_invalid_label_fails_closed(label):
    rows = population([3], [1]); rows[0]["feature_label"] = label
    with pytest.raises(ValueError): evaluate_findings(rows)


def test_bootstrap_determinism_and_no_mutation():
    rows = population(list(range(10,22)),list(range(12)))
    before = [dict(row) for row in rows]
    first = evaluate_findings(rows)
    assert first == evaluate_findings(rows,seed=42) == evaluate_findings(reversed(rows))
    assert first["bootstrap_seed"] == 42 and first["bootstrap_resamples"] == 5000
    assert rows == before


def test_low_coverage_blocks_finding_and_u_axes_do_not_count():
    rows = population([3]*10,[1]*10,[100]*31)
    rows[-1]["length_axis"] = "shorts"
    result = evaluate_findings(rows)
    assert result["status"] == "CANDIDATE"
    assert result["reasons"] == ["coverage_below_0.40"]
    assert result["axis_diagnostics"]["evaluable_axes"] == ["long"]
