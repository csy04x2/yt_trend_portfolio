"""Development-only guest_present cascade. Never reads Human reference labels."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from tools.stage2_evidence import stage2_collect
from .core import VERSION, FEATURE, inputs, stage1, result, evidence_packet, adjudicate, sha
from .judge import judge, PROMPT


def write(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)


def extract(metadata, split, registry, out, evidence_root=None, collect=False, model=None,
            judge_fn=judge, collector=stage2_collect.collect_one):
    rows, feature = inputs(metadata, split, registry)
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError("New output directory required")
    sources = [Path(p).resolve() for p in (metadata, split, registry)]
    if any(p.is_relative_to(out) for p in sources):
        raise ValueError("Output must not contain inputs")
    if out.is_relative_to(sources[0].parent) or out.is_relative_to(sources[2].parent):
        raise ValueError("Do not write inside metadata/registry artifact directories")
    if evidence_root and out.is_relative_to(Path(evidence_root).resolve()):
        raise ValueError("Existing evidence roots are read-only")
    # Explicit opt-in only. Credentials are never put in packets or logs.
    if model and judge_fn is judge and not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY missing")
    if collect:
        stage2_collect.require("ffmpeg")
        stage2_collect.require("ffprobe")
    hashes = {str(p): sha(p) for p in sources}
    stage_one = [stage1(r) for r in rows]
    queue = [{"video_id": r["video_id"], "youtube_url": f"https://www.youtube.com/watch?v={r['video_id']}",
              "title": r.get("title"), "length_axis": r.get("length_axis"),
              "stage1_label": "U", "stage_1_reason": s["reason"]}
             for r, s in zip(rows, stage_one) if s["label"] == "U"]
    out.mkdir(parents=True)
    write(out / "stage1.json", stage_one)
    write(out / "stage2_queue.json", queue)
    finals = []
    for row, initial in zip(rows, stage_one):
        final = dict(initial)
        if initial["label"] == "U":
            path = Path(evidence_root).resolve() / row["video_id"] / "evidence_packet.json" if evidence_root else None
            if path and not path.resolve().is_relative_to(Path(evidence_root).resolve()):
                raise ValueError("Evidence path escaped root")
            if (not path or not path.exists()) and collect:
                item = next(q for q in queue if q["video_id"] == row["video_id"])
                try:
                    collector(item, out / "evidence", None, False,
                              feature_definition=feature["definition"])
                    path = out / "evidence" / row["video_id"] / "evidence_packet.json"
                except Exception as exc:
                    final = result(row, "U", "stage2", "collection_failed:" + type(exc).__name__)
            if path and path.is_file():
                try:
                    packet = evidence_packet(path, row)
                    packet_hash = packet["packet_sha256"]
                    if not packet["frames"]:
                        final = result(row, "U", "stage2", "visual_evidence_missing")
                    elif not model:
                        final = result(row, "U", "stage2", "judge_not_configured")
                    else:
                        response, provenance = judge_fn(packet, feature, model)
                        final = adjudicate(row, packet, response)
                        final["provenance"].update(provenance)
                        if sha(path) != packet_hash or any(sha(f["path"]) != f["sha256"] for f in packet["frames"]):
                            raise ValueError("Evidence changed during judgment")
                        # Response remains inspectable when rejected/downgraded.
                        write(out / (row["video_id"] + "-judge.json"), {"response": response, "provenance": provenance})
                    final["provenance"].update(packet_sha256=packet["packet_sha256"],
                        caption_truncated=packet["caption_truncated"],
                        frame_sha256={f["frame_id"]: f["sha256"] for f in packet["frames"]})
                except Exception as exc:
                    final = result(row, "U", "stage2", "evidence_or_judge_failed:" + type(exc).__name__)
            elif final["stage"] == "stage1":
                final = result(row, "U", "stage2", "evidence_missing")
        final["provenance"] = {**final["provenance"], "registry_sha256": sha(registry),
                               "split_sha256": sha(split), "metadata_sha256": sha(metadata),
                               "stage1_label": initial["label"], "stage1_reason": initial["reason"]}
        finals.append(final)
    if any(sha(p) != h for p, h in hashes.items()):
        raise ValueError("Input changed during extraction; incomplete run")
    with (out / "predictions.jsonl").open("x", encoding="utf-8") as stream:
        for f in finals:
            stream.write(json.dumps(f, ensure_ascii=False) + "\n")
    # Partial feature interface only: never fill the other eleven features.
    write(out / "labels.json", {"feature_scope": [FEATURE], "complete_registry_matrix": False,
        "registry_sha256": sha(registry), "labels": {r["video_id"]: {FEATURE: r["label"]} for r in finals}})
    manifest = {"extractor_version": VERSION, "feature_id": FEATURE, "split": "development",
        "input_sha256": hashes, "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "source_sha256": {p.name: sha(p) for p in Path(__file__).parent.glob("*.py")},
        "collector_sha256": sha(stage2_collect.__file__), "cookies_from_browser": None,
        "requested_model": model, "rows": len(rows), "stage2_queue_count": len(queue),
        "label_counts": {v: sum(f["label"] == v for f in finals) for v in ("0", "1", "U")},
        "empirically_validated": False, "validation_note": "Contract-tested software; held-out accuracy is not established by tests.",
        "outputs_sha256": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    write(out / "manifest.json", manifest)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metadata", required=True, help="Content-only Development JSONL")
    p.add_argument("--split", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--out", required=True, help="New directory, never an existing artifact")
    p.add_argument("--evidence-root", help="Existing stage2_collect output; read-only")
    p.add_argument("--collect", action="store_true", help="Opt in to caption/frame collection for U only, no cookies")
    p.add_argument("--model", help="Explicit Anthropic vision model ID; opt in to API judgment")
    a = p.parse_args()
    print(json.dumps(extract(a.metadata, a.split, a.registry, a.out, a.evidence_root, a.collect, a.model), indent=2))


if __name__ == "__main__":
    main()
