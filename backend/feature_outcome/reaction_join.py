"""Reaction × Content Feature × 상대 성과 — 탐색용 결합 분석 (opt-in, 사실만).

설계: `docs/design/reaction-feature-join.md`. 재개 결정 범위 4.

    python -m feature_outcome.reaction_join --registry R.json --labels L.json \\
        --split split.csv --evidence E.json --db D.db \\
        --prompt-version reaction-v1 --model <모델> \\
        --out feature_discovery/outputs/reaction-feature-join/RUN_ID \\
        [--reference-manifest M.json] [--sampling-run-id RUN] [--min-labeled 30] \\
        [--include-replies] [--split-name holdout --unseal-holdout]

## 무엇을 내는가

Stage 08 모양의 사실 두 갈래. 임계값·유의성 판정·인과 주장은 없다.

- Content Feature → Reaction 비율 (median difference, Finding Engine `_binary_leg`)
- Reaction 비율 → 상대 성과 (Spearman rho, Finding Engine `_continuous_leg`)

## 가드

1. **Holdout 봉인.** 기본은 Development 만. holdout 은 `--unseal-holdout` 없이는 입력
   파일을 하나도 열기 전에 `HoldoutSealed` 로 거부한다 (`frozen.prepare` 와 같은 순서).
   Discovery 는 거부한다.
2. **동결 특징만.** registry 는 `freeze_metadata` envelope 가 있는 동결본만 받고, 판정은
   `labels.load_labels` 경로로만 읽는다. 선택 split 의 모든 영상에 모든 특징 판정이 있어야 한다.
3. **상대 성과 표시.** `--reference-manifest` 가 있으면 canonical 값, 없으면 공급된
   `view_multiple` 을 쓰되 모든 행에 `canonical: false`, `provisional_legacy` 를 찍는다.
4. **MVP 격리.** 모든 행·갈래·보고서에 `validation_status: "검증 전 AI 판정"`,
   `mvp_input_eligible: false`. 출력은 MVP Finding 실행 디렉터리(`frozen.OUTPUT_ROOT`)
   밖의 별도 루트에만 쓴다. Reaction 필드가 든 영상 행은 `finding.build_findings` 가
   거부한다.
5. **원문 없음.** 댓글 원문·rationale 을 읽지도 쓰지도 않는다. 영상 제목도 싣지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

from . import frozen
from .finding import (
    OUTCOME,
    RELATIVE_PERFORMANCE_CONTRACT,
    _binary_leg,
    _canonical_outcomes,
    _continuous_leg,
)
from .labels import load_labels, load_registry
from .outcome import HoldoutSealed
from .reaction_profile import (
    AVAILABLE,
    MIN_LABELED_PER_VIDEO,
    REACTION_SHARE_KEYS,
    SHARE_KEYS,
    TARGET_SHARE_KEYS,
    VALIDATION_STATUS,
    build_profiles,
    label_versions,
    load_comment_reactions,
    load_sampling,
    open_readonly,
)
from .reaction_profile import VERSION as PROFILE_VERSION

VERSION = "reaction-feature-join-v0.1"
REPORT_KIND = "reaction-feature-join"
# MVP Finding 실행 루트(frozen.OUTPUT_ROOT = experiment-analysis)와 형제인 별도 루트.
# feature_discovery/.gitignore 의 /outputs/ 아래라 커밋되지 않는다.
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "feature_discovery/outputs/reaction-feature-join"
ALLOWED_SPLITS = ("development", "holdout")
ALLOWED_CLAIM = ("exploratory association only; 검증 전 AI 판정 기반이며 MVP Finding 입력이 아니다; "
                 "not a causal conclusion or performance guarantee")
GUARD = {"validation_status": VALIDATION_STATUS, "mvp_input_eligible": False}


# --------------------------------------------------------------------------
# 사전 점검 — 봉인 확인이 모든 입력 접근보다 먼저다
# --------------------------------------------------------------------------

def check_scope(split_name: str, unseal_holdout: bool) -> None:
    if split_name == "holdout" and not unseal_holdout:
        raise HoldoutSealed("holdout 은 봉인되어 있다. Reaction 결합 분석도 --unseal-holdout 없이 열지 않는다")
    if split_name not in ALLOWED_SPLITS:
        raise ValueError(f"Reaction 결합 분석은 {ALLOWED_SPLITS} 만 받는다 (받은 값 {split_name!r})")


def check_out(out, inputs) -> Path:
    out = Path(out).resolve()
    root = OUTPUT_ROOT.resolve()
    mvp_root = frozen.OUTPUT_ROOT.resolve()
    if out == mvp_root or out.is_relative_to(mvp_root):
        raise ValueError("Reaction 결합 결과는 MVP Finding 실행 디렉터리에 쓰지 않는다: " + str(mvp_root))
    if not out.is_relative_to(root) or out == root:
        raise ValueError("--out 은 다음 아래의 새 실행 디렉터리여야 한다: " + str(root))
    if out.exists():
        raise FileExistsError("출력 디렉터리가 이미 있다: " + str(out))
    for p in inputs:
        p = Path(p).resolve()
        if p == out or p.is_relative_to(out):
            raise ValueError("입력과 출력은 분리되어야 한다")
    return out


def read_split(path, split_name: str) -> tuple[dict, set]:
    with open(path, encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    split = {}
    for r in records:
        vid = r.get("video_id")
        if not vid or vid in split or r.get("split") not in ("discovery", "development", "holdout"):
            raise ValueError("split 파일에 잘못되었거나 중복된 행이 있다")
        split[vid] = r["split"]
    selected = {vid for vid, part in split.items() if part == split_name}
    if not selected:
        raise ValueError("선택한 split 이 비었다")
    return split, selected


def load_frozen_inputs(registry_path, labels_path, evidence_path, split, selected):
    """동결 registry·판정·evidence 를 선택 split 으로만 투영한다 (frozen.prepare 와 같은 규칙)."""
    with open(registry_path, encoding="utf-8") as stream:
        if "registry" not in json.load(stream):
            raise ValueError("동결 registry envelope(freeze_metadata) 만 받는다")
    registry = load_registry(registry_path)
    with open(evidence_path, encoding="utf-8") as stream:
        raw = json.load(stream)
    videos = raw["videos"] if isinstance(raw, dict) else raw
    seen, scoped = set(), []
    for v in videos:
        vid = v["video_id"]
        if vid in seen or vid not in split:
            raise ValueError("evidence 에 중복되었거나 split 밖인 영상 ID 가 있다")
        seen.add(vid)
        if vid in selected:
            scoped.append({key: v[key] for key in frozen.ANALYSIS_FIELDS if key in v})
    if {v["video_id"] for v in scoped} != selected:
        raise ValueError("선택 split 의 evidence 가 빠져 있다")
    labels = load_labels(labels_path, registry, video_ids=selected)
    fids = {f["feature_id"] for f in registry["features"]}
    if set(labels) != selected or any(set(fs) != fids for fs in labels.values()):
        raise ValueError("선택 split 의 모든 영상에 모든 동결 특징 판정(0/1/U)이 있어야 한다")
    return registry, sorted(scoped, key=lambda v: v["video_id"]), labels


# --------------------------------------------------------------------------
# 결합 — 순수 함수
# --------------------------------------------------------------------------

def join_rows(videos, labels, registry, split, profiles, reference_manifest=None):
    """video_id 키 결합 행과 상대 성과 계약. 입력을 바꾸지 않는다."""
    feature_ids = [f["feature_id"] for f in registry["features"]]
    contract = dict(RELATIVE_PERFORMANCE_CONTRACT)
    per_video = {}
    if reference_manifest is not None:
        videos, contract = _canonical_outcomes(videos, reference_manifest)
        per_video = contract["per_video"]
    rows = []
    for v in sorted(videos, key=lambda x: x["video_id"]):
        vid = v["video_id"]
        if vid not in profiles:
            raise ValueError(f"{vid}: Reaction 프로필이 없다")
        if reference_manifest is not None:
            rp = {"canonical": True, "status": "canonical_reference",
                  "canonical_value_status": per_video[vid]["status"],
                  "final_eligible": contract["final_eligible"]}
        else:
            rp = {"canonical": False, "status": "provisional_legacy",
                  "canonical_value_status": None, "final_eligible": False}
        rows.append({
            "video_id": vid,
            "split": split[vid],
            "length_axis": v.get("length_axis"),
            "features": {fid: labels[vid][fid] for fid in feature_ids},
            "reaction_profile": profiles[vid],
            OUTCOME: v.get(OUTCOME),
            "relative_performance": rp,
            **GUARD,
        })
    return rows, contract


def _flat(rows):
    """Finding Engine 통계 함수에 넣을 평평한 행. Reaction 키는 전부 reaction_ 접두다."""
    return [{"video_id": r["video_id"], OUTCOME: r[OUTCOME], **r["reaction_profile"]["shares"],
             **GUARD} for r in rows]


def _stamp(leg, relation=None):
    if relation:
        leg["relation"] = relation
    return {**leg, **GUARD, "allowed_claim": ALLOWED_CLAIM}


def associations(rows, labels, feature_ids):
    """두 갈래의 사실. 비율이 null(최소 n 미달 등)인 영상은 missing 으로 센다."""
    flat = _flat(rows)
    scoped_labels = {r["video_id"]: labels[r["video_id"]] for r in rows}
    fr = [_stamp(_binary_leg(flat, scoped_labels, fid, metric, "feature_to_reaction"))
          for fid in feature_ids for metric in SHARE_KEYS]
    rp = [_stamp(_continuous_leg(flat, metric), "reaction_to_performance") for metric in SHARE_KEYS]
    return {"feature_to_reaction": fr, "reaction_to_performance": rp}


def build_report(rows, labels, registry, *, split_name, unseal_holdout, contract,
                 prompt_version, model, min_labeled, include_replies, versions_in_db=None):
    feature_ids = [f["feature_id"] for f in registry["features"]]
    freeze = registry["_envelope"].get("freeze_metadata", {})
    status_counts, sampling_counts = {}, {}
    for r in rows:
        p = r["reaction_profile"]
        status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1
        s = p["sampling"].get("completeness") or p["sampling"].get("status")
        sampling_counts[s] = sampling_counts.get(s, 0) + 1
    probs = {r["reaction_profile"]["sampling"].get("inclusion_prob") for r in rows}
    return {
        "report_kind": REPORT_KIND,
        "version": VERSION,
        **GUARD,
        "mvp_isolation": "이 보고서의 어떤 행도 MVP Finding(findings.json·results.json) 입력이 아니다. "
                         "독립 fresh 표본 검증 통과 전까지 유지 (reaction-track-closeout 재개 결정).",
        "association_only": True,
        "causal_claim": False,
        "thresholds_applied": [],
        "scope": {
            "split": split_name, "unseal_holdout": unseal_holdout,
            "feature_registry_version": freeze.get("registry_version"),
            "u_policy": "exclude; never control", "outcome": OUTCOME, "video_n": len(rows),
        },
        "reaction_contract": {
            "profile_version": PROFILE_VERSION,
            "prompt_version": prompt_version,
            "model": model,
            "label_versions_in_db": versions_in_db,
            "eligibility": "analysis_eligible = 1 만",
            "label_unit": "all_comments" if include_replies else "top_level",
            "min_labeled_per_video": min_labeled,
            "min_labeled_status": "proposal",
            "reaction_share_denominator": "판정된 분석 대상 댓글 수 (None·UNKNOWN 포함). 다중 코드라 합이 1이 아니다",
            "target_share_denominator": "반응이 있는 댓글 수 (Reaction 이 None·UNKNOWN 이 아닌 것)",
            "profile_status_counts": dict(sorted(status_counts.items())),
            "sampling_completeness_counts": dict(sorted(sampling_counts.items(), key=lambda kv: str(kv[0]))),
            "unweighted": True,
            "inclusion_prob_values": sorted((p for p in probs if p is not None)),
            "sampling_note": "포함 확률 가중을 하지 않았다. inclusion_prob 이 1.0 이 아닌 영상이 섞이면 "
                             "층별 선정 확률이 달라 비가중 연관은 편향될 수 있다.",
            "reaction_metrics": list(REACTION_SHARE_KEYS),
            "target_metrics": list(TARGET_SHARE_KEYS),
        },
        "input_contract": {"relative_performance": contract},
        "multiple_comparisons_note": f"특징 {len(feature_ids)}개 × 비율 {len(SHARE_KEYS)}개를 한꺼번에 본다. "
                                     "보정하지 않았으므로 개별 값은 탐색 단서일 뿐이다.",
        "rows": rows,
        "calculations": associations(rows, labels, feature_ids),
    }


# --------------------------------------------------------------------------
# 실행
# --------------------------------------------------------------------------

def run(*, registry, labels, split, evidence, db, prompt_version, model, out,
        split_name="development", unseal_holdout=False, reference_manifest=None,
        sampling_run_id=None, min_labeled=MIN_LABELED_PER_VIDEO, include_replies=False):
    check_scope(split_name, unseal_holdout)
    if not prompt_version or not model:
        raise ValueError("prompt_version 과 model 을 둘 다 정해야 한다 (판정 버전을 섞어 집계하지 않는다)")
    inputs = [p for p in (registry, labels, split, evidence, db, reference_manifest) if p]
    destination = check_out(out, inputs)
    split_map, selected = read_split(split, split_name)
    loaded, videos, scoped_labels = load_frozen_inputs(registry, labels, evidence, split_map, selected)
    reference = None
    if reference_manifest is not None:
        reference_bytes = Path(reference_manifest).read_bytes()
        reference = json.loads(reference_bytes.decode("utf-8"))

    conn = open_readonly(db)
    try:
        comments = load_comment_reactions(conn, selected, prompt_version=prompt_version, model=model)
        sampling = load_sampling(conn, selected, sampling_run_id)
        versions = label_versions(conn)
    finally:
        conn.close()
    profiles = build_profiles(selected, comments, prompt_version=prompt_version, model=model,
                              min_labeled=min_labeled, include_replies=include_replies, sampling=sampling)
    rows, contract = join_rows(videos, scoped_labels, loaded, split_map, profiles, reference)
    report = build_report(rows, scoped_labels, loaded, split_name=split_name, unseal_holdout=unseal_holdout,
                          contract=contract, prompt_version=prompt_version, model=model,
                          min_labeled=min_labeled, include_replies=include_replies, versions_in_db=versions)
    manifest = {
        "report_kind": REPORT_KIND, "version": VERSION, **GUARD,
        "split": split_name, "unseal_holdout": unseal_holdout,
        "registry_version": loaded["_envelope"]["freeze_metadata"]["registry_version"],
        "prompt_version": prompt_version, "model": model, "sampling_run_id": sampling_run_id,
        "min_labeled": min_labeled, "include_replies": include_replies,
        "input_sha256": {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                         for p in inputs},
        "relative_performance_mode": "canonical_reference" if reference is not None else "provisional_legacy",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if reference is not None:
        manifest["reference_manifest_sha256"] = reference["manifest_sha256"]
    serialized = {name: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                  for name, value in (("manifest.json", manifest), ("reaction_join.json", report))}
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in serialized.items():
        with (destination / name).open("x", encoding="utf-8") as stream:
            stream.write(content)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(prog="feature_outcome.reaction_join", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("registry", "labels", "split", "evidence", "db", "prompt-version", "model", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--split-name", default="development", choices=list(ALLOWED_SPLITS))
    parser.add_argument("--unseal-holdout", action="store_true", help="holdout 봉인 해제. 정의 동결 후 한 번만")
    parser.add_argument("--reference-manifest", default=None,
                        help="opt-in: 동결 reference population manifest (canonical view_multiple)")
    parser.add_argument("--sampling-run-id", default=None, help="observation_sampling 의 run_id")
    parser.add_argument("--min-labeled", type=int, default=MIN_LABELED_PER_VIDEO,
                        help=f"영상당 최소 판정 댓글 수 [제안 기본값 {MIN_LABELED_PER_VIDEO}]")
    parser.add_argument("--include-replies", action="store_true", help="답글도 분모·판정에 넣는다")
    args = parser.parse_args(argv)
    kwargs = {k: v for k, v in vars(args).items()}
    try:
        destination = run(**kwargs)
    except (HoldoutSealed, ValueError, OSError) as error:
        parser.exit(2, f"Reaction 결합 분석 거부: {error}\n")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
