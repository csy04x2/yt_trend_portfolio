"""Preflight boundaries for frozen experiments; no labeling or DB access.

Registry A envelopes opt in automatically; plain registries can use
--frozen-experiment. Use a new --out run directory below OUTPUT_ROOT.
Shared JSON inputs are decoded, but only selected video IDs are projected for
analysis. No aggregate, cached summary or peer list from another split is used.
The supplied view_multiple remains the input metric; this adapter does not
redefine its upstream calculation. Frozen reports are JSON, not prototype UI.
"""
import csv
import hashlib
import json
from pathlib import Path

from .labels import load_labels
from .outcome import HoldoutSealed
from .finding import AUDIENCE_METRICS

OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "feature_discovery/outputs/experiment-analysis"
ANALYSIS_FIELDS = ("video_id", "title", "length_axis", "duration_sec", "published_at",
                   "view_count", "view_multiple", "age_days", *AUDIENCE_METRICS)


def prepare(a, registry):
    # This check must precede opening evidence/labels/events and all aggregates.
    if a.split_name == "holdout" and not a.unseal_holdout:
        raise HoldoutSealed("Frozen holdout requires explicit --unseal-holdout")
    if a.u_as_control:
        raise ValueError("Frozen experiments never use --u-as-control")
    with open(a.split, encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    split = {}
    for r in records:
        vid = r.get("video_id")
        if not vid or vid in split or r.get("split") not in ("discovery", "development", "holdout"):
            raise ValueError("Invalid or duplicate split membership")
        split[vid] = r["split"]
    selected = {vid for vid, part in split.items() if part == a.split_name}
    if not selected:
        raise ValueError("Empty selected split")
    out = Path(a.out).resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out == OUTPUT_ROOT.resolve():
        raise ValueError("Frozen --out must be a new run directory under " + str(OUTPUT_ROOT))
    if out.exists():
        raise FileExistsError("Frozen analysis output already exists: " + str(out))
    evidence_out = Path(a.evidence_out).resolve() if a.evidence_out else None
    if evidence_out and (evidence_out.parent != out or evidence_out.suffix.lower() != ".json" or evidence_out.name in
                         {"breakout.csv", "results.json", "manifest.json", "report.md"}):
        raise ValueError("Frozen --evidence-out must be a distinct JSON file inside --out")
    inputs = [Path(p).resolve() for p in (a.evidence, a.labels, a.registry, a.split, a.events) if p]
    if any(p == out or p.is_relative_to(out) for p in inputs):
        raise ValueError("Frozen inputs and output must be separate")
    with open(a.evidence, encoding="utf-8") as stream:
        raw = json.load(stream)
    videos = raw["videos"] if isinstance(raw, dict) else raw
    channel = raw.get("channel", "") if isinstance(raw, dict) else ""
    # Only IDs are inspected before selection; no held-out content or outcomes
    # are accessed by the analysis. Do not carry cached summaries into exports.
    seen = set()
    scoped = []
    for v in videos:
        vid = v["video_id"]
        if vid in seen or vid not in split:
            raise ValueError("Duplicate or out-of-population evidence ID")
        seen.add(vid)
        if vid in selected:
            scoped.append({key: v[key] for key in ANALYSIS_FIELDS if key in v})
    if {v["video_id"] for v in scoped} != selected:
        raise ValueError("Selected split evidence is incomplete")
    labels = load_labels(a.labels, registry, video_ids=selected)
    fids = {f["feature_id"] for f in registry["features"]}
    if set(labels) != selected or any(set(fs) != fids for fs in labels.values()):
        raise ValueError("Every selected video needs every frozen feature label (0/1/U)")
    provenance = {
        "mode": "frozen-experiment", "split_name": a.split_name,
        "unseal_holdout": a.unseal_holdout, "u_policy": "exclude; never control",
        "registry_metadata": registry.get("_envelope", {}).get("freeze_metadata"),
        "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "n_u_definition": "Explicit U labels, including missing outcomes; reported before and after breakout exclusion",
    }
    return scoped, channel, split, labels, provenance
