"""Isolated, injectable single-video cascade. No implicit provider or I/O calls."""
from copy import deepcopy
import math

from .core import FEATURE_ROUTING, TEXT_THEN_VISUAL, FIELDS, validate_text_judgment, can_escalate_visual


def definitions_by_id(features, *, all_features=True):
    if not isinstance(features, list) or not features:
        raise ValueError("Expected feature definitions")
    result = {}
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("Invalid feature definition")
        fid = feature.get("feature_id")
        if not isinstance(fid, str) or fid not in FEATURE_ROUTING or fid in result:
            raise ValueError("Unknown or duplicate feature definition")
        if not isinstance(feature.get("definition"), str) or not feature["definition"].strip():
            raise ValueError("Frozen definition required")
        if not isinstance(feature.get("exclusion_examples"), list) or any(not isinstance(x,str) or not x.strip() for x in feature["exclusion_examples"]):
            raise ValueError("Frozen exclusion examples required")
        if not all_features and FEATURE_ROUTING[fid] != TEXT_THEN_VISUAL:
            raise ValueError("Not a visual feature")
        result[fid] = deepcopy(feature)
    if all_features and set(result) != set(FEATURE_ROUTING):
        raise ValueError("Expected exactly all 12 frozen features")
    return result


def validate_evidence(metadata, caption):
    if not isinstance(metadata, dict) or set(metadata) - FIELDS:
        raise ValueError("Content metadata only")
    if not isinstance(metadata.get("video_id"),str) or not metadata["video_id"].strip():
        raise ValueError("video_id required")
    for key,value in metadata.items():
        if key == "duration_sec":
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value < 0):
                raise ValueError("Invalid duration")
        elif value is not None and not isinstance(value,str):
            raise ValueError("Metadata must be scalar content")
    if caption is not None and not isinstance(caption,str):
        raise ValueError("Full caption must be text or None")


def validate_packet(packet, metadata, caption):
    if not isinstance(packet,dict) or set(packet) != {"metadata","caption","frames"}:
        raise ValueError("Expected content-only visual packet")
    validate_evidence(packet["metadata"],packet["caption"])
    if packet["metadata"] != metadata or packet["caption"] != caption:
        raise ValueError("Evidence does not match this video/text input")
    if not isinstance(packet["frames"],list) or not packet["frames"]:
        raise ValueError("Sampled frames required")
    seen=set()
    for frame in packet["frames"]:
        if not isinstance(frame,dict) or set(frame) != {"frame_id","timestamp_sec","image_base64"}:
            raise ValueError("Expected in-memory sampled image")
        fid=frame["frame_id"]
        if not isinstance(fid,str) or not fid.strip() or fid in seen:
            raise ValueError("Duplicate/invalid frame ID")
        seen.add(fid)
        if type(frame["timestamp_sec"]) not in (int,float) or not math.isfinite(frame["timestamp_sec"]) or frame["timestamp_sec"] < 0:
            raise ValueError("Invalid timestamp")
        if not isinstance(frame["image_base64"],str) or not frame["image_base64"]:
            raise ValueError("Image required")


def validate_judgments(judgments, features, *, visual=False, caption=None):
    """Exact coverage. Visual zero needs a positively evidenced frozen exclusion.

    Exclusion citations are structurally grounded, not independently semantically
    verified. A model assertion cannot be proven true by schema validation.
    """
    if not isinstance(judgments,list):
        raise ValueError("Expected judgment list")
    result={}
    for judgment in judgments:
        if not isinstance(judgment,dict):
            raise ValueError("Invalid judgment")
        base={k:v for k,v in judgment.items() if k != "positive_exclusion"}
        checked=validate_text_judgment(base)
        fid=checked["feature_id"]
        if fid not in features or fid in result:
            raise ValueError("Unknown, unrequested or duplicate judgment")
        if not visual and "positive_exclusion" in judgment:
            raise ValueError("Unexpected text judgment field")
        if visual:
            exclusion=judgment.get("positive_exclusion")
            if exclusion is not None:
                if (not isinstance(exclusion,dict) or set(exclusion) != {"exclusion","caption_quote","explanation"}
                    or any(not isinstance(v,str) or not v.strip() for v in exclusion.values())
                    or exclusion["exclusion"] not in features[fid]["exclusion_examples"]
                    or exclusion["caption_quote"] not in (caption or "")):
                    raise ValueError("Ungrounded positive exclusion")
            checked["positive_exclusion"]=deepcopy(exclusion)
        result[fid]=checked
    if set(result) != set(features):
        raise ValueError("Missing feature judgments")
    return result


def extract_video(metadata, full_caption, features, *, model=None, text_judge=None,
                  text_judgments=None, visual_judge=None, visual_packet=None):
    """One text batch, at most one visual batch. Providers must be injected.

    No visual provider/evidence leaves eligible U unresolved; never fabricates
    missing judgments. Frozen definitions are supplied by the caller unchanged.
    """
    definitions=definitions_by_id(features)
    validate_evidence(metadata,full_caption)
    if visual_packet is not None:
        validate_packet(visual_packet,metadata,full_caption)
    if (text_judge is None) == (text_judgments is None):
        raise ValueError("Supply exactly one text judge or completed text batch")
    if text_judge is not None:
        text_judgments=text_judge(deepcopy(metadata),full_caption,deepcopy(list(definitions.values())),model)
    text=validate_judgments(text_judgments,definitions)
    eligible=[fid for fid in definitions if can_escalate_visual(text[fid])]
    visual={}
    if eligible and visual_judge is not None and visual_packet is not None:
        subset={fid:definitions[fid] for fid in eligible}
        response=visual_judge(deepcopy(visual_packet),deepcopy(list(subset.values())),model)
        visual=validate_judgments(response,subset,visual=True,caption=full_caption)
    labels, provenance={},{}
    for fid in definitions:
        final=text[fid]["label"]
        rejection=None
        if fid in visual:
            final=visual[fid]["label"]
            if final == "0" and visual[fid]["positive_exclusion"] is None:
                final="U"
                rejection="sampled_absence_is_not_positive_exclusion"
        labels[fid]=final
        provenance[fid]={"text":text[fid],"visual_eligible":fid in eligible,
            "visual_escalated":fid in visual,"visual":visual.get(fid),
            "final_label":final,"visual_rejection":rejection}
    return {"video_id":metadata["video_id"],"labels":labels,"provenance":provenance}
