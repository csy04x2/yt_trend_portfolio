"""Conservative evidence contracts. No reference labels, network or DB access."""
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from types import MappingProxyType

from backend.feature_discovery.blind import validate_rows
from backend.feature_discovery.registry import validate_registry

VERSION = "guest-present-cascade-v0.1"
FEATURE = "guest_present"
FIELDS = {"video_id", "title", "description", "duration_sec", "published_at", "length_axis"}


TEXT_ONLY = "TEXT_ONLY"
TEXT_THEN_VISUAL = "TEXT_THEN_VISUAL"
# Frozen A-v0.1 evidence routing only; this table never assigns a label.
FEATURE_ROUTING = MappingProxyType({
    "guest_present": TEXT_THEN_VISUAL,
    "guest_conversation": TEXT_THEN_VISUAL,
    "browse_and_comment": TEXT_THEN_VISUAL,
    "tournament_format": TEXT_ONLY,
    "eating_content": TEXT_THEN_VISUAL,
    "experiential_activity": TEXT_ONLY,
    "food_evaluation": TEXT_ONLY,
    "external_content_reaction": TEXT_THEN_VISUAL,
    "cooking_content": TEXT_THEN_VISUAL,
    "work_or_character_focus": TEXT_ONLY,
    "on_location": TEXT_THEN_VISUAL,
    "challenge_activity": TEXT_ONLY,
})


def validate_text_judgment(judgment):
    """Validate a future metadata + full-caption judgment, without executing it.

    Reason is a non-empty grounded explanation supplied by the caller; this
    structural contract cannot establish its semantic truth. No label coercion.
    Sampled-frame absence alone must never automatically become label 0.
    """
    if not isinstance(judgment, dict) or set(judgment) != {"feature_id", "label", "confidence", "reason"}:
        raise ValueError("Expected feature_id, label, confidence and reason")
    if not isinstance(judgment["feature_id"], str) or judgment["feature_id"] not in FEATURE_ROUTING:
        raise ValueError("Unknown frozen feature")
    if not isinstance(judgment["label"], str) or judgment["label"] not in ("0", "1", "U"):
        raise ValueError("Invalid text label")
    if not isinstance(judgment["confidence"], str) or judgment["confidence"] not in ("low", "medium", "high"):
        raise ValueError("Invalid text confidence")
    if not isinstance(judgment["reason"], str) or not judgment["reason"].strip():
        raise ValueError("Grounded explanation required")
    return dict(judgment)


def can_escalate_visual(judgment):
    """Only validated text U with visual-relevant routing is eligible, not required."""
    checked = validate_text_judgment(judgment)
    return checked["label"] == "U" and FEATURE_ROUTING[checked["feature_id"]] == TEXT_THEN_VISUAL


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate JSON key")
        out[key] = value
    return out


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def development_ids(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = set()
    development = set()
    for r in rows:
        vid = r.get("video_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or vid in ids or r.get("split") not in {"discovery", "development", "holdout"}:
            raise ValueError("Invalid split")
        ids.add(vid)
        if r["split"] == "development":
            development.add(vid)
    return development


def inputs(metadata, split, registry):
    allowed = development_ids(split)
    rows = []
    for line in Path(metadata).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line, object_pairs_hook=unique_object)
        if set(row) - FIELDS or row.get("video_id") not in allowed:
            raise ValueError("Only allowlisted Development metadata is accepted")
        rows.append(row)
    validate_rows(rows)
    if not rows:
        raise ValueError("Empty metadata")
    envelope = read_json(registry)
    validate_registry(envelope["registry"])
    freeze = envelope["freeze_metadata"]
    if (freeze.get("registry_version") != "A-v0.1" or freeze.get("definitions_frozen_before_development") is not True
            or freeze.get("freeze_status") != "frozen"):
        raise ValueError("Expected frozen Registry A-v0.1")
    fs = [f for f in envelope["registry"]["features"] if f["feature_id"] == FEATURE]
    if len(fs) != 1 or fs[0]["categories"] != ["0", "1", "U"]:
        raise ValueError("Expected guest_present 0/1/U")
    return rows, fs[0]


def result(row, label, stage, reason, evidence=None, confidence="low"):
    return {"video_id": row["video_id"], "feature_id": FEATURE, "label": label,
            "stage": stage, "confidence": confidence, "reason": reason,
            "evidence": evidence or [], "provenance": {"extractor_version": VERSION}}


def stage1(row):
    """Legacy placeholder; metadata classification is retired.

    This is not a completed text judgment and must not authorize visual routing.
    Future orchestration must judge metadata + full caption, then call
    can_escalate_visual. The legacy CLI has not yet been migrated.
    """
    return result(row, "U", "stage1", "text_judgment_required")


def evidence_packet(path, row):
    """Project collector output; never feed logs, URLs or arbitrary fields to judge."""
    path = Path(path).resolve()
    packet = read_json(path)
    expected = {"version", "video_id", "youtube_url", "title", "length_axis", "stage1_label",
                "stage1_reason", "feature", "feature_definition", "forbidden_evidence", "caption",
                "frames", "status", "errors"}
    if set(packet) - expected or packet.get("video_id") != row["video_id"] or packet.get("feature") != FEATURE or packet.get("stage1_label") != "U":
        raise ValueError("Wrong or contaminated evidence packet")
    caption = packet.get("caption") or {}
    if set(caption) - {"available", "text", "files", "stderr_tail"}:
        raise ValueError("Unexpected caption fields")
    text = caption.get("text") if caption.get("available") else None
    if text is not None and not isinstance(text, str):
        raise ValueError("Invalid caption")
    frames = []
    if len(packet.get("frames", [])) > 6:
        raise ValueError("Too many sampled frames")
    for i, f in enumerate(packet.get("frames", [])):
        if set(f) != {"path", "timestamp_sec", "ratio"}:
            raise ValueError("Unexpected frame fields")
        p = Path(f["path"])
        p = (p if p.is_absolute() else path.parent / p).resolve()
        t = f["timestamp_sec"]
        ratio = f["ratio"]
        if (not p.is_relative_to(path.parent) or p.suffix.lower() != ".jpg" or not p.is_file()
                or type(t) not in (float, int) or not math.isfinite(t) or t < 0
                or type(ratio) not in (float, int) or not math.isfinite(ratio) or not 0 <= ratio <= 1
                or (row.get("duration_sec") and t > row["duration_sec"])):
            raise ValueError("Invalid frame provenance")
        frames.append({"frame_id": f"frame_{i+1}", "path": str(p), "timestamp_sec": t, "sha256": sha(p)})
    return {"metadata": dict(row), "caption": text, "frames": frames,
            "packet_sha256": sha(path), "caption_truncated": bool(text and len(text) > 80000)}


def adjudicate(row, packet, response):
    """Validate evidence pointers; model confidence is not calibrated accuracy."""
    if set(response) != {"label", "confidence", "role", "participation", "evidence"}:
        raise ValueError("Unexpected judge response")
    label, confidence = response["label"], response["confidence"]
    if label not in ("0", "1", "U") or confidence not in ("low", "medium", "high"):
        raise ValueError("Invalid judge label/confidence")
    if response["role"] not in ("active_content_participant", "excluded_person", "unclear") or not isinstance(response["participation"], str):
        raise ValueError("Invalid role/participation")
    if not isinstance(response["evidence"], list):
        raise ValueError("Invalid citations")
    frames = {f["frame_id"]: f for f in packet["frames"]}
    grounded = []
    for e in response["evidence"]:
        if not isinstance(e, dict) or set(e) != {"type", "ref", "detail"} or not isinstance(e["ref"], str) or not isinstance(e["detail"], str) or not e["detail"].strip():
            raise ValueError("Invalid citation")
        if e["type"] == "visual" and e["ref"] in frames:
            f = frames[e["ref"]]
            grounded.append({**e, "timestamp_sec": f["timestamp_sec"], "sha256": f["sha256"]})
        elif e["type"] == "caption" and e["detail"] in (packet["caption"] or "")[:80000]:
            grounded.append(e)
        else:
            raise ValueError("Ungrounded citation")
    if label == "0":
        return result(row, "U", "stage2", "sampled_evidence_cannot_establish_absence", grounded)
    if label == "1" and (response["role"] != "active_content_participant"
                         or not isinstance(response["participation"], str) or not response["participation"].strip()
                         or confidence == "low" or not any(e["type"] == "visual" for e in grounded)):
        return result(row, "U", "stage2", "insufficient_active_participant_evidence", grounded)
    return result(row, label, "stage2", "grounded_judge" if label == "1" else "judge_uncertain", grounded, confidence)
