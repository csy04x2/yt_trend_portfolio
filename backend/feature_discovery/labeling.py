"""Discovery-only manual/external labeling worksheet; no automatic judgment."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from .blind import CONTENT_FIELDS, validate_fields, validate_rows
from .registry import validate_registry
from feature_outcome.labels import load_registry, validate_labels

COLUMNS = ("video_id", "title", "evidence_json", "feature_id", "feature_json", "label", "notes")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _json(text):
    return json.loads(text, object_pairs_hook=_unique)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _contracts(split_path, registry_path):
    with Path(split_path).open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    membership = {}
    for row in records:
        vid, part = row.get("video_id"), row.get("split")
        if not vid or vid in membership or part not in ("discovery", "development", "holdout"):
            raise ValueError("Invalid split membership")
        membership[vid] = part
    selected = {vid for vid, part in membership.items() if part == "discovery"}
    if not selected:
        raise ValueError("Empty Discovery split")
    # Reject duplicate JSON keys before reusing the downstream envelope loader.
    _json(Path(registry_path).read_text(encoding="utf-8"))
    registry = load_registry(registry_path)
    plain = {k: v for k, v in registry.items() if k != "_envelope"}
    validate_registry(plain)
    features = {}
    for feature in registry["features"]:
        fid = feature["feature_id"]
        if fid in features or feature["scope"] != "video":
            raise ValueError("Unique video-level features required")
        if not (feature["value_type"] == "binary" or
                (feature["value_type"] == "categorical" and feature.get("categories") == ["0", "1", "U"])):
            raise ValueError("Worksheet supports only video 0/1/U features")
        features[fid] = feature
    return membership, selected, registry, features


def _new_directory(output_dir, inputs):
    out = Path(output_dir).resolve()
    if out.exists():
        raise FileExistsError("Use a new output directory")
    if any(Path(p).resolve().is_relative_to(out) for p in inputs):
        raise ValueError("Output must not contain input files")
    out.mkdir(parents=True)
    return out


def export_worksheet(content_path, split_path, registry_path, output_dir):
    membership, selected, registry, features = _contracts(split_path, registry_path)
    # Only a supplied blind JSON list is supported: no DB or outcome adapters.
    raw = _json(Path(content_path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list):
        raise ValueError("Expected a blind content JSON array")
    scoped, seen = [], set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Invalid content row")
        validate_fields(row.keys())  # Reject forbidden field names, never project metrics.
        vid = row.get("video_id")
        if not isinstance(vid, str) or vid in seen or vid not in membership:
            raise ValueError("Invalid/duplicate/out-of-population content ID")
        seen.add(vid)
        if vid in selected:
            scoped.append(row)
        # No non-Discovery content values are used after membership selection.
    if {r["video_id"] for r in scoped} != selected:
        raise ValueError("Incomplete Discovery content")
    validate_rows(scoped)
    records = []
    for row in sorted(scoped, key=lambda r: r["video_id"]):
        evidence = {key: row.get(key) for key in CONTENT_FIELDS}
        for fid, feature in sorted(features.items()):
            records.append(dict(video_id=row["video_id"], title=row.get("title") or "",
                evidence_json=json.dumps(evidence, ensure_ascii=False), feature_id=fid,
                feature_json=json.dumps(feature, ensure_ascii=False), label="", notes=""))
    out = _new_directory(output_dir, (content_path, split_path, registry_path))
    with (out / "worksheet.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return {"videos": len(selected), "features": len(features), "rows": len(records)}


def compile_worksheet(worksheet_path, split_path, registry_path, output_dir):
    _, selected, registry, features = _contracts(split_path, registry_path)
    with Path(worksheet_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("Unexpected worksheet columns")
        records = list(reader)
    labels, notes, evidence_by_video = {}, {}, {}
    for row in records:
        if set(row) != set(COLUMNS) or any(value is None for value in row.values()):
            raise ValueError("Malformed CSV row")
        vid, fid, value = row["video_id"], row["feature_id"], row["label"]
        if vid not in selected or fid not in features:
            raise ValueError("Non-Discovery ID or unknown feature")
        if fid in labels.get(vid, {}):
            raise ValueError("Duplicate video-feature judgment")
        errors = validate_labels({vid: {fid: value}}, registry)
        if errors:
            raise ValueError("; ".join(errors))
        evidence = _json(row["evidence_json"])
        validate_rows([evidence])
        if evidence["video_id"] != vid or (evidence.get("title") or "") != row["title"]:
            raise ValueError("Evidence identity/title mismatch")
        if vid in evidence_by_video and evidence_by_video[vid] != evidence:
            raise ValueError("Inconsistent evidence across feature rows")
        evidence_by_video[vid] = evidence
        if _json(row["feature_json"]) != features[fid]:
            raise ValueError("Worksheet definition differs from supplied registry")
        labels.setdefault(vid, {})[fid] = int(value) if value in ("0", "1") else value
        notes.setdefault(vid, {})[fid] = row["notes"]
    if set(labels) != selected or any(set(fs) != set(features) for fs in labels.values()):
        raise ValueError("Every Discovery video requires every feature judgment")
    summary = {"split": "discovery", "features": {},
        "input_sha256": {str(Path(p)): _hash(p) for p in (worksheet_path, split_path, registry_path)},
        "notice": "Descriptive coverage only; no threshold, status change or freeze decision."}
    for fid in sorted(features):
        values = [labels[vid][fid] for vid in sorted(selected)]
        n0, n1, nu = values.count(0), values.count(1), values.count("U")
        total = len(values)
        summary["features"][fid] = dict(n_total=total, n_0=n0, n_1=n1, n_u=nu,
            judged_n=n0+n1, coverage=(n0+n1)/total, u_rate=nu/total)
    out = _new_directory(output_dir, (worksheet_path, split_path, registry_path))
    for name, data in (("labels.json", labels), ("summary.json", summary), ("notes.json", notes)):
        with (out / name).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, field in (("export", "content"), ("compile", "worksheet")):
        command = commands.add_parser(name)
        command.add_argument("--" + field, required=True, type=Path)
        for flag in ("split", "registry", "output-dir"):
            command.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args()
    if args.command == "export":
        result = export_worksheet(args.content, args.split, args.registry, args.output_dir)
    else:
        result = compile_worksheet(args.worksheet, args.split, args.registry, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
