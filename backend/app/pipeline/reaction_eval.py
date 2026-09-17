"""Reaction Phase 3 — 두 라벨 파일의 일치도 평가.

입력은 comment_id 를 키로 하는 라벨 파일 두 개다 (`label_reactions.label_file`
모양, 또는 사람 판정 시트가 내보낸 JSON). 조합은 무엇이든 된다.

    A = 기준 (예: 사람)      B = 비교 대상 (예: AI)
    A = AI 모델 1            B = AI 모델 2 (재현성·모델 비교)

정밀도·재현율은 **A 를 기준으로 본 B** 의 값이다. kappa·정확 일치율·Jaccard 는
대칭이라 순서와 무관하다.

## 무엇을 내는가

- 라벨별 (R1–R10, Reaction UNKNOWN, T1–T5, Target UNKNOWN) 존재 여부를 이진으로 본
  TP/FP/FN/TN, precision / recall / F1, Cohen's kappa
- Reaction=None (`reactions == []`) 의 2×2 혼동표와 kappa
- Reaction 집합·Target 집합·둘 다의 정확 일치율, Jaccard 평균
- 어긋난 comment_id 목록

## 무엇을 내지 않는가

**댓글 원문과 rationale 은 보고서에 한 글자도 들어가지 않는다.** ID 와 숫자만
나간다. 그래서 보고서는 저장소에 둘 수 있지만, 입력 라벨 파일(rationale 포함)과
원문은 backend/data/ 에 둔다.

값을 계산할 수 없으면(분모 0, 기대 일치 1) None 을 내고 지어내지 않는다.
희귀 라벨이 표본에 한 번도 없으면 그 라벨의 F1·kappa 는 None 이다 — 0 이 아니다.

## 결과의 지위

Phase 2 200개로 잰 값은 개발·보정용이다. 독립 검증은 새로 수집한, 누구도 본 적
없는 fresh 표본의 사람 판정과 대조한 값만 인정한다
(`docs/design/reaction-classifier-phase3.md`).
"""

from __future__ import annotations

import json
import pathlib

from app.pipeline.label_reactions import (
    REACTIONS,
    TARGETS,
    UNKNOWN,
    ValidationError,
    check_label,
)

REACTION_LABELS = REACTIONS + (UNKNOWN,)
TARGET_LABELS = TARGETS + (UNKNOWN,)


# --------------------------------------------------------------------------
# 입력
# --------------------------------------------------------------------------

def parse_labels(data, source: str = "") -> dict[str, dict]:
    """라벨 파일 내용 → comment_id → 정규화된 판정. 규칙 위반은 모아서 거부한다.

    평가 입력이 규칙을 어기면(없는 코드, UNKNOWN 섞임 등) 숫자를 내지 않는다.
    틀린 입력으로 낸 일치도는 없는 일치도보다 나쁘다.
    """
    rows = data.get("labels") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValidationError(f"{source}: labels 배열을 찾지 못했다")
    out: dict[str, dict] = {}
    problems: list[str] = []
    for i, r in enumerate(rows):
        cid = r.get("comment_id") if isinstance(r, dict) else None
        if not isinstance(cid, str) or not cid:
            problems.append(f"[{i}] comment_id 가 없다")
            continue
        if cid in out:
            problems.append(f"{cid}: 같은 comment_id 가 두 번 있다")
            continue
        label, bad = check_label(r, where=cid, strict=False)
        problems += bad
        out[cid] = label
    if problems:
        raise ValidationError("\n  - ".join([f"{source}: 라벨 파일이 규칙에 맞지 않는다:"]
                                            + problems))
    return out


def load_labels(path) -> tuple[dict[str, dict], dict]:
    """(판정, 메타). 메타는 labeler·prompt_version·model 같은 파일 머리."""
    p = pathlib.Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = {k: data.get(k) for k in ("format", "labeler", "prompt_version", "model")} \
        if isinstance(data, dict) else {}
    return parse_labels(data, p.name), meta


# --------------------------------------------------------------------------
# 지표
# --------------------------------------------------------------------------

def _div(a: float, b: float):
    return a / b if b else None


def cohen_kappa(tp: int, fp: int, fn: int, tn: int):
    """이진 Cohen's kappa. 기대 일치가 1 이면(두 쪽 모두 한 값만 씀) 정의되지 않아 None."""
    n = tp + fp + fn + tn
    if not n:
        return None
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    if pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def binary(a: list[bool], b: list[bool]) -> dict:
    """a 를 기준으로 본 b 의 이진 지표."""
    tp = sum(1 for x, y in zip(a, b) if x and y)
    fp = sum(1 for x, y in zip(a, b) if not x and y)
    fn = sum(1 for x, y in zip(a, b) if x and not y)
    tn = sum(1 for x, y in zip(a, b) if not x and not y)
    precision = _div(tp, tp + fp)
    recall = _div(tp, tp + fn)
    # F1 = 2TP / (2TP+FP+FN). 한쪽만 그 라벨을 썼으면 precision 이나 recall 이
    # 정의되지 않아도 F1 은 0 이다 — None 으로 두면 macro F1 이 놓친 라벨을 빼고
    # 부풀려진다. 두 쪽 모두 한 번도 안 쓴 라벨만 None.
    f1 = _div(2 * tp, 2 * tp + fp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "support_a": tp + fn, "support_b": tp + fp,
            "precision": precision, "recall": recall, "f1": f1,
            "kappa": cohen_kappa(tp, fp, fn, tn)}


def jaccard(x: list[str], y: list[str]) -> float:
    sx, sy = set(x), set(y)
    if not sx and not sy:
        return 1.0      # 둘 다 비었다 = 같은 판정 (예: 둘 다 Reaction=None)
    return len(sx & sy) / len(sx | sy)


def _axis(a: dict[str, dict], b: dict[str, dict], ids: list[str],
          key: str, labels: tuple) -> dict:
    per = {lab: binary([lab in a[i][key] for i in ids], [lab in b[i][key] for i in ids])
           for lab in labels}
    f1s = [v["f1"] for v in per.values() if v["f1"] is not None]
    exact = [i for i in ids if set(a[i][key]) == set(b[i][key])]
    return {
        "per_label": per,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "macro_f1_labels": [k for k, v in per.items() if v["f1"] is not None],
        "exact_match_rate": _div(len(exact), len(ids)),
        "jaccard_mean": _div(sum(jaccard(a[i][key], b[i][key]) for i in ids), len(ids)),
        "disagreeing_ids": [i for i in ids if set(a[i][key]) != set(b[i][key])],
    }


def evaluate(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """두 판정 묶음의 일치도. 공통 comment_id 만 비교하고 나머지는 ID 로 알린다."""
    ids = sorted(set(a) & set(b))
    reactions = _axis(a, b, ids, "reactions", REACTION_LABELS)
    targets = _axis(a, b, ids, "targets", TARGET_LABELS)

    none_a = [not a[i]["reactions"] for i in ids]
    none_b = [not b[i]["reactions"] for i in ids]
    none = binary(none_a, none_b)
    none["confusion"] = {
        "a_none_b_none": none["tp"], "a_none_b_some": none["fn"],
        "a_some_b_none": none["fp"], "a_some_b_some": none["tn"],
    }
    none["disagreeing_ids"] = [i for i, x, y in zip(ids, none_a, none_b) if x != y]

    both = [i for i in ids
            if set(a[i]["reactions"]) == set(b[i]["reactions"])
            and set(a[i]["targets"]) == set(b[i]["targets"])]
    return {
        "n_compared": len(ids),
        "n_a": len(a), "n_b": len(b),
        "only_in_a_ids": sorted(set(a) - set(b)),
        "only_in_b_ids": sorted(set(b) - set(a)),
        "reactions": reactions,
        "reaction_none": none,
        "targets": targets,
        "both_exact_match_rate": _div(len(both), len(ids)),
        "review_flag_counts": {"a": sum(1 for i in ids if a[i]["review_flag"]),
                               "b": sum(1 for i in ids if b[i]["review_flag"])},
    }


# --------------------------------------------------------------------------
# 보고서 — 숫자와 ID 만
# --------------------------------------------------------------------------

def _f(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def render(report: dict, meta_a: dict | None = None, meta_b: dict | None = None,
           max_ids: int = 50) -> str:
    """사람이 읽는 요약 (마크다운). 원문·rationale 은 들어갈 자리가 없다."""
    def who(m):
        if not m:
            return "(메타 없음)"
        return " · ".join(str(m[k]) for k in ("labeler", "prompt_version", "model") if m.get(k))

    lines = [
        "# Reaction 판정 일치도",
        "",
        f"- A (기준): {who(meta_a)}",
        f"- B (비교): {who(meta_b)}",
        f"- 비교한 댓글: {report['n_compared']} (A {report['n_a']} · B {report['n_b']} · "
        f"A 에만 {len(report['only_in_a_ids'])} · B 에만 {len(report['only_in_b_ids'])})",
        "- 지위: 이 수치가 fresh 표본의 사람 판정 대조가 아니면 검증 증거가 아니다.",
        "",
        "## 집합 일치",
        "",
        "| 축 | 정확 일치율 | Jaccard 평균 | macro F1 |",
        "|---|---:|---:|---:|",
        f"| Reaction | {_f(report['reactions']['exact_match_rate'])} | "
        f"{_f(report['reactions']['jaccard_mean'])} | {_f(report['reactions']['macro_f1'])} |",
        f"| Target | {_f(report['targets']['exact_match_rate'])} | "
        f"{_f(report['targets']['jaccard_mean'])} | {_f(report['targets']['macro_f1'])} |",
        f"| 둘 다 | {_f(report['both_exact_match_rate'])} | | |",
        "",
    ]
    n = report["reaction_none"]
    c = n["confusion"]
    lines += [
        "## Reaction=None",
        "",
        "| | B None | B 반응 있음 |",
        "|---|---:|---:|",
        f"| A None | {c['a_none_b_none']} | {c['a_none_b_some']} |",
        f"| A 반응 있음 | {c['a_some_b_none']} | {c['a_some_b_some']} |",
        "",
        f"precision {_f(n['precision'])} · recall {_f(n['recall'])} · "
        f"F1 {_f(n['f1'])} · kappa {_f(n['kappa'])}",
        "",
    ]
    for axis, title in (("reactions", "Reaction 라벨별"), ("targets", "Target 라벨별")):
        lines += [f"## {title}", "",
                  "| 라벨 | A | B | TP | FP | FN | precision | recall | F1 | kappa |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for lab, v in report[axis]["per_label"].items():
            lines.append(f"| {lab} | {v['support_a']} | {v['support_b']} | {v['tp']} | "
                         f"{v['fp']} | {v['fn']} | {_f(v['precision'])} | "
                         f"{_f(v['recall'])} | {_f(v['f1'])} | {_f(v['kappa'])} |")
        lines.append("")
    lines += ["## 어긋난 comment_id", ""]
    for label, ids in (("Reaction", report["reactions"]["disagreeing_ids"]),
                       ("Reaction=None", n["disagreeing_ids"]),
                       ("Target", report["targets"]["disagreeing_ids"])):
        shown = ", ".join(ids[:max_ids]) or "(없음)"
        more = f" 외 {len(ids) - max_ids}건" if len(ids) > max_ids else ""
        lines.append(f"- {label} {len(ids)}건: {shown}{more}")
    lines.append("")
    lines.append("값이 — 인 칸은 분모가 0 이거나 kappa 가 정의되지 않는 경우다 "
                 "(표본에 그 라벨이 없음). 0 으로 읽지 않는다.")
    return "\n".join(lines)
