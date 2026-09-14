"""특징 판정 파일 — {video_id: {feature_id: 0 | 1 | "U"}}.

이 파일이 분석의 유일한 판정 입력이다. 팀원이 자기 판정으로 바꾸면 나머지 코드는 그대로 돈다.
U(자료 부족)는 0이 아니다. 어디서도 0으로 바꾸지 않는다.
"""
import json
import re

VALID = (0, 1, "U")


def load_registry(path):
    return json.load(open(path, encoding="utf-8"))


def validate_labels(labels, registry):
    ids = {f["feature_id"] for f in registry["features"]}
    errs = []
    for vid, fs in labels.items():
        for fid, val in fs.items():
            if fid not in ids:
                errs.append(f"{vid}: 레지스트리에 없는 특징 {fid}")
            elif val not in VALID or isinstance(val, bool):
                errs.append(f'{vid}/{fid}: 값 {val!r} — 0, 1, "U"만 허용')
    return errs


def load_labels(path, registry):
    d = json.load(open(path, encoding="utf-8"))
    labels = d["labels"] if "labels" in d else d
    errs = validate_labels(labels, registry)
    if errs:
        raise ValueError("\n".join(errs[:20]))
    return labels


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
