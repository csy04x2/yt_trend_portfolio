"""Separate, read-only benchmark after predictions are frozen; no extractor calls."""
import argparse
import json
from pathlib import Path
from .core import read_json, development_ids, sha, FEATURE


def evaluate(run, reference, split):
    run = Path(run)
    manifest = read_json(run / "manifest.json")
    if manifest["outputs_sha256"]["predictions.jsonl"] != sha(run / "predictions.jsonl"):
        raise ValueError("Predictions changed after freeze")
    if sha(split) not in manifest["input_sha256"].values():
        raise ValueError("Split mismatch")
    allowed = development_ids(split)
    pred = {}
    for line in (run / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["video_id"] not in allowed or r["video_id"] in pred or r["feature_id"] != FEATURE or r["label"] not in ("0", "1", "U"):
            raise ValueError("Invalid or non-Development predictions")
        pred[r["video_id"]] = r["label"]
    ref = read_json(reference)
    gold = ref["labels"]
    if not gold or set(gold) - allowed or set(gold) - pred.keys():
        raise ValueError("Reference must be a covered Development subset")
    pairs = []
    for vid, fs in gold.items():
        value = fs[FEATURE]
        if type(value) not in (int, str) or str(value) not in ("0", "1", "U"):
            raise ValueError("Invalid reference label")
        pairs.append((str(value), pred[vid]))
    known = [(g,p) for g,p in pairs if g != "U"]
    called = [(g,p) for g,p in known if p != "U"]
    ratio = lambda a,b: a/b if b else None
    return {"reference_sha256": sha(reference), "predictions_sha256": sha(run / "predictions.jsonl"),
        "reference_rows": len(pairs), "reference_u": sum(g=="U" for g,p in pairs),
        "known_reference_rows": len(known), "coverage": ratio(len(called),len(known)),
        "accuracy_non_u": ratio(sum(g==p for g,p in called),len(called)),
        "precision_positive": ratio(sum(g==p=="1" for g,p in known),sum(p=="1" for g,p in known)),
        "recall_all_positives": ratio(sum(g==p=="1" for g,p in known),sum(g=="1" for g,p in known)),
        "n_u": sum(p=="U" for g,p in known), "note": "Reference used only here, never for extraction. No automatic validation claim."}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "reference", "split", "out"):
        p.add_argument("--"+name, required=True)
    a = p.parse_args()
    report = evaluate(a.run, a.reference, a.split)
    with Path(a.out).open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
