"""특징 판정 파일 — {video_id: {feature_id: 0 | 1 | "U"}}.

이 파일이 분석의 유일한 판정 입력이다. 팀원이 자기 판정으로 바꾸면 나머지 코드는 그대로 돈다.
U(자료 부족)는 로딩할 때 그대로 보존한다. frozen 실험은 U 대조군 옵션을 금지한다.
"""
import json
import re

VALID = (0, 1, "U")


def load_registry(path):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    if "registry" not in data:
        return data
    from feature_discovery.registry import validate_registry
    validate_registry(data["registry"])
    freeze = data.get("freeze_metadata", {})
    features = data["registry"]["features"]
    if (freeze.get("definitions_frozen_before_development") is not True
            or freeze.get("freeze_status") != "frozen"
            or not freeze.get("registry_version")
            or not freeze.get("dataset")
            or freeze.get("testing_feature_count") != len(features)):
        raise ValueError("Invalid frozen registry metadata")
    if any(f["value_type"] != "categorical" or f.get("categories") != ["0", "1", "U"]
           for f in features):
        raise ValueError("Frozen registry requires categorical string 0/1/U")
    # A new in-memory projection; retain the entire envelope for provenance.
    return {**data["registry"], "_envelope": data}


def validate_labels(labels, registry):
    ids = {f["feature_id"] for f in registry["features"]}
    errs = []
    for vid, fs in labels.items():
        for fid, val in fs.items():
            if fid not in ids:
                errs.append(f"{vid}: 레지스트리에 없는 특징 {fid}")
            elif not ((type(val) is int and val in (0, 1))
                      or (type(val) is str and val in ("0", "1", "U"))):
                errs.append(f'{vid}/{fid}: 값 {val!r} — 0, 1, "U"만 허용')
    return errs


def load_labels(path, registry, video_ids=None):
    with open(path, encoding="utf-8") as stream:
        d = json.load(stream)
    labels = d["labels"] if "labels" in d else d
    if video_ids is not None:
        labels = {vid: fs for vid, fs in labels.items() if vid in video_ids}
    errs = validate_labels(labels, registry)
    if errs:
        raise ValueError("\n".join(errs[:20]))
    return {vid: {fid: int(value) if value in ("0", "1") else value
                  for fid, value in fs.items()} for vid, fs in labels.items()}


def label_by_title_regex(videos, config):
    """제목 정규식 판정 — **자리표시자**. 사람·LLM 판정 파일이 오면 이 함수는 쓰지 않는다.

    kind=content: 제목에 있으면 1, 없으면 U (없음을 증명할 수 없다)
    kind=form:    제목 자체가 근거. 있으면 1, 없으면 0
    kind=duration: duration_sec > gt_seconds
    """
    out = {}
    for v in videos:
        row = {}
        for fid, spec in config["features"].items():
            kind = spec["kind"]
            if kind == "duration":
                row[fid] = int(v["duration_sec"] > spec["gt_seconds"])
            else:
                hit = bool(re.search(spec["regex"], v.get("title") or "", re.I))
                row[fid] = 1 if hit else ("U" if kind == "content" else 0)
        out[v["video_id"]] = row
    return out
