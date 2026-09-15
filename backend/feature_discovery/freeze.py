"""Seal an explicit human approval as a NEW Development registry envelope.

No labels, statistics, split, content, DB or outcome inputs are accepted.
The approval attests to human review; this command cannot authenticate a human
or prove that Development has not already been inspected.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .labeling import _json
from .registry import validate_registry


def freeze_registry(registry_path, approval_path, output_path):
    source, decision, out = [Path(p).resolve() for p in (registry_path, approval_path, output_path)]
    if out.exists():
        raise FileExistsError("Frozen output already exists; use a new artifact")
    if out in (source, decision):
        raise ValueError("Output must be separate from freeze inputs")
    # Hash the exact bytes parsed, binding selection to the reviewed definitions.
    source_bytes, decision_bytes = source.read_bytes(), decision.read_bytes()
    registry = _json(source_bytes.decode("utf-8-sig"))
    validate_registry(registry)  # Plain, fully schema-valid source only.
    approval = _json(decision_bytes.decode("utf-8-sig"))
    fields = {"selected_feature_ids", "approved_by", "registry_version", "dataset",
              "definitions_frozen_before_development", "source_registry_sha256"}
    if not isinstance(approval, dict) or set(approval) != fields:
        raise ValueError("Approval must contain exactly the explicit human freeze fields")
    for key in ("approved_by", "registry_version", "dataset", "source_registry_sha256"):
        if not isinstance(approval[key], str) or not approval[key].strip():
            raise ValueError("Approval requires nonempty " + key)
    if approval["definitions_frozen_before_development"] is not True:
        raise ValueError("Human must attest definitions are frozen before Development")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if approval["source_registry_sha256"] != source_hash:
        raise ValueError("Source registry SHA-256 differs from human approval")
    selected = approval["selected_feature_ids"]
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(fid, str) or not fid.strip() for fid in selected)):
        raise ValueError("Explicit nonempty feature ID list required")
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate selected feature IDs")
    by_id = {f["feature_id"]: f for f in registry["features"]}
    if len(by_id) != len(registry["features"]):
        raise ValueError("Source feature IDs must be unique across versions")
    if set(selected) - by_id.keys():
        raise ValueError("Unknown selected feature IDs")
    features = []
    for fid in selected:
        feature = by_id[fid]
        if feature["scope"] != "video" or not (
                feature["value_type"] == "binary" or
                (feature["value_type"] == "categorical" and feature.get("categories") == ["0", "1", "U"])):
            raise ValueError("Selected features must be video-level binary or categorical 0/1/U")
        # Human selection, not Discovery statistics, authorizes testing status.
        # Only schema fields change; definitions/evidence/examples stay intact.
        features.append({**feature, "status": "testing", "value_type": "categorical",
                         "categories": ["0", "1", "U"]})
    frozen_registry = {**registry, "features": features}
    validate_registry(frozen_registry)
    envelope = {
        "registry": frozen_registry,
        "freeze_metadata": {
            "registry_version": approval["registry_version"], "dataset": approval["dataset"],
            "freeze_status": "frozen", "definitions_frozen_before_development": True,
            "testing_feature_count": len(features),
        },
        "freeze_provenance": {
            "selection_basis": "explicit human approval", "approved_by": approval["approved_by"],
            "selected_feature_ids": selected,
            "input_sha256": {str(source): source_hash,
                             str(decision): hashlib.sha256(decision_bytes).hexdigest()},
        },
    }
    payload = json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against a concurrent writer after preflight.
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("registry", "approval", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        out = freeze_registry(args.registry, args.approval, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Freeze refused: {error}\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
