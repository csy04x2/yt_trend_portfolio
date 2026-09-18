# -*- coding: utf-8 -*-
"""채널 단위 특징 추출기 — 싼 단서부터 보고, 판정이 끝난 특징은 더 보지 않는다.

한 영상에 한 번 물어 레지스트리의 모든 특징을 0/1/U로 받는다(텍스트 단계: 제목·설명·자막).
텍스트로 U가 남은 특징 중 화면이 답할 수 있는 것만 장면 몇 장으로 다시 묻는다(시각 단계).
그래도 모르면 U로 남긴다. U를 0으로 바꾸는 일은 어디서도 없다.

  python -m tools.feature_extractor.channel run --content E.json --registry R.json --out DIR
        [--split split.csv --scope development|discovery|all] [--unseal-holdout]
        [--captions DIR] [--evidence-root DIR] [--routing routing.json]
        [--judge offline | --judge api --model ID] [--cache DIR] [--limit N] [--review-share 0.1]
  python -m tools.feature_extractor.channel import --run DIR --answers DIR
  python -m tools.feature_extractor.channel evaluate --run DIR --reference H.json --out eval.json

판정기는 tools.feature_extractor.judge(팀원 구현)를 그대로 쓴다. 성과값은 어디서도 읽지 않는다.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from backend.feature_discovery.blind import validate_rows
from .core import FEATURE_ROUTING, TEXT_ONLY, TEXT_THEN_VISUAL, set_feature_routing, sha
from .multi import extract_video, validate_judgments, definitions_by_id

VERSION = "channel-extractor-v0.1"
FIELDS = ("video_id", "title", "description", "duration_sec", "published_at", "length_axis")
CHUNK_CHARS = 120_000          # 자막이 이보다 길면 나눠 묻고 합친다
DEFAULT_MAX_FRAMES = 8


# ---------- 입력 ----------

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_content(path):
    """evidence JSON(dict, videos 키) 또는 JSONL 행 → 허용 필드만 남긴 행 목록."""
    p = Path(path)
    if p.suffix == ".jsonl":
        raw = [json.loads(l) for l in p.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    else:
        d = read_json(p)
        raw = d["videos"] if isinstance(d, dict) else d
    rows = []
    for v in raw:
        row = {k: v.get(k) for k in FIELDS if k in v}
        if row.get("duration_sec") is not None:
            row["duration_sec"] = int(row["duration_sec"])
        rows.append(row)
    validate_rows(rows)
    return rows


def load_split(path):
    return {r["video_id"]: r["split"] for r in csv.DictReader(open(path, encoding="utf-8-sig", newline=""))}


def select_scope(rows, split, scope, unseal_holdout=False):
    if split is None:
        return rows
    if scope == "all":
        if not unseal_holdout:
            raise ValueError("분할 파일이 있으면 --scope all 은 holdout 내용을 읽는다. 정의를 동결한 뒤 --unseal-holdout 으로만 연다.")
        return [r for r in rows if r["video_id"] in split]
    if scope == "holdout" and not unseal_holdout:
        raise ValueError("holdout은 봉인되어 있다.")
    return [r for r in rows if split.get(r["video_id"]) == scope]


def load_registry_any(path):
    d = read_json(path)
    if "registry" in d:
        meta = d.get("freeze_metadata", {})
        return d["registry"]["features"], {"frozen": meta.get("freeze_status") == "frozen", "envelope": True,
                                            "registry_version": meta.get("registry_version")}
    return d["features"], {"frozen": False, "envelope": False, "registry_version": d.get("schema_version")}


def routing_for(features, routing_path=None):
    ids = [f["feature_id"] for f in features]
    if routing_path:
        r = read_json(routing_path)
        missing = set(ids) - set(r)
        if missing:
            raise ValueError(f"routing.json에 없는 특징: {sorted(missing)}")
        return {fid: r[fid] for fid in ids}, "file"
    if set(ids) == set(FEATURE_ROUTING):
        return dict(FEATURE_ROUTING), "default"
    # 모르는 레지스트리: 전부 시각 단계까지 허용한다. 시각은 텍스트 U일 때만 쓰이므로 안전하고 비용만 든다.
    return {fid: TEXT_THEN_VISUAL for fid in ids}, "all_visual_fallback"


# ---------- 증거 ----------

def caption_for(vid, captions_dir=None, evidence_root=None):
    if captions_dir:
        p = Path(captions_dir) / f"{vid}.txt"
        if p.is_file():
            return p.read_text(encoding="utf-8-sig"), "file"
    if evidence_root:
        p = Path(evidence_root) / vid / "evidence_packet.json"
        if p.is_file():
            c = read_json(p).get("caption") or {}
            if c.get("available") and isinstance(c.get("text"), str):
                return c["text"], "packet"
    return None, None


def packet_for(vid, evidence_root, metadata, caption, max_frames=DEFAULT_MAX_FRAMES):
    """팀원 수집기의 evidence_packet.json → 판정기용 메모리 패킷. 프레임이 없으면 None."""
    if not evidence_root:
        return None
    p = Path(evidence_root) / vid / "evidence_packet.json"
    if not p.is_file():
        return None
    frames = []
    for i, f in enumerate((read_json(p).get("frames") or [])[:max_frames]):
        fp = Path(f["path"])
        fp = fp if fp.is_absolute() else p.parent / fp
        if fp.suffix.lower() != ".jpg" or not fp.is_file():
            continue
        frames.append({"frame_id": f"frame_{i + 1}", "timestamp_sec": f["timestamp_sec"],
                       "image_base64": base64.b64encode(fp.read_bytes()).decode("ascii")})
    if not frames:
        return None
    return {"metadata": metadata, "caption": caption, "frames": frames}


def chunk_caption(text, size=CHUNK_CHARS):
    if text is None or len(text) <= size:
        return [text]
    return [text[i:i + size] for i in range(0, len(text), size)]


def merge_chunk_judgments(batches, fids):
    """여러 자막 조각의 판정 합치기: 하나라도 1이면 1, 전부 0이면 0, 그 밖에는 U."""
    out = []
    for fid in fids:
        js = [j for b in batches for j in b if j["feature_id"] == fid]
        ones = [j for j in js if j["label"] == "1"]
        if ones:
            best = max(ones, key=lambda j: ("low", "medium", "high").index(j["confidence"]))
            out.append(dict(best))
        elif js and all(j["label"] == "0" for j in js):
            worst = min(js, key=lambda j: ("low", "medium", "high").index(j["confidence"]))
            out.append(dict(worst))
        else:
            reasons = "; ".join(f"조각{i + 1}:{j['label']}" for i, j in enumerate(js)) or "no chunks"
            out.append({"feature_id": fid, "label": "U", "confidence": "low", "reason": f"조각별 판정 불일치 ({reasons})"})
    return out


# ---------- 캐시 ----------

class Cache:
    def __init__(self, root):
        self.root = Path(root) if root else None
        self.hits = 0
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    def key(self, **parts):
        return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def get(self, key):
        if not self.root:
            return None
        p = self.root / f"{key}.json"
        if p.is_file():
            self.hits += 1
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def put(self, key, data):
        if self.root:
            (self.root / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------- 실행 ----------

def run_one(row, definitions, routing, *, caption, packet, model, text_judge, visual_judge, cache, prompt_sha, registry_sha):
    """영상 하나: 텍스트 판정(조각 합치기·캐시) → 필요 시 시각 판정."""
    fids = list(definitions)
    feats = list(definitions.values())
    metadata = {k: v for k, v in row.items() if k in FIELDS}
    calls = 0
    batches = []
    for i, piece in enumerate(chunk_caption(caption)):
        key = cache.key(video_id=row["video_id"], registry=registry_sha, prompt=prompt_sha, model=model,
                        mode="text", chunk=i, caption=hashlib.sha256((piece or "").encode()).hexdigest(),
                        metadata=metadata)
        hit = cache.get(key)
        if hit is None:
            judgments = text_judge(dict(metadata), piece, [dict(f) for f in feats], model)
            calls += 1
            judgments = [dict(j) for j in validate_judgments(judgments, definitions).values()]
            cache.put(key, {"judgments": judgments})
        else:
            judgments = hit["judgments"]
        batches.append(judgments)
    text_judgments = batches[0] if len(batches) == 1 else merge_chunk_judgments(batches, fids)
    vj = None
    if packet is not None and visual_judge is not None:
        def vj(pkt, subset, mdl):
            nonlocal calls
            key = cache.key(video_id=row["video_id"], registry=registry_sha, prompt=prompt_sha, model=mdl, mode="visual",
                            features=sorted(f["feature_id"] for f in subset),
                            frames=[hashlib.sha256(f["image_base64"].encode()).hexdigest() for f in pkt["frames"]])
            hit = cache.get(key)
            if hit is not None:
                return hit["judgments"]
            out = visual_judge(pkt, subset, mdl)
            calls += 1
            cache.put(key, {"judgments": [dict(j) for j in out]})
            return out
    result = extract_video(metadata, caption, feats, model=model, text_judgments=text_judgments,
                           visual_judge=vj, visual_packet=packet if vj else None)
    result["chunks"] = len(batches)
    result["api_calls"] = calls
    return result


def review_sample(results, rows, share=0.1, seed=42):
    """사람 검토 대상: 자신 없는(low) 0·1 판정, 시각 단계까지 간 영상, 그리고 무작위 표본."""
    byid = {r["video_id"]: r for r in rows}
    picked = {}
    for res in results:
        why = []
        for fid, prov in res["provenance"].items():
            if prov["final_label"] in ("0", "1"):
                src = prov["visual"] if prov["visual_escalated"] and prov["visual"] else prov["text"]
                if src.get("confidence") == "low":
                    why.append(f"{fid}: 자신 없음(low)")
            if prov["visual_escalated"]:
                why.append(f"{fid}: 시각 단계")
        if why:
            picked[res["video_id"]] = sorted(set(why))
    rng = random.Random(seed)
    rest = [r["video_id"] for r in results if r["video_id"] not in picked]
    for vid in rng.sample(rest, min(len(rest), round(len(results) * share))):
        picked[vid] = ["무작위 표본"]
    queue = []
    for res in results:
        if res["video_id"] in picked:
            queue.append({"video_id": res["video_id"], "title": byid[res["video_id"]].get("title"),
                          "why": picked[res["video_id"]],
                          "labels": {fid: {"label": p["final_label"],
                                           "confidence": (p["visual"] or p["text"]).get("confidence"),
                                           "reason": (p["visual"] or p["text"]).get("reason")}
                                     for fid, p in res["provenance"].items()}})
    return queue


def summarize(results, rows, definitions, caption_src, packet_ok, meta):
    byid = {r["video_id"]: r for r in rows}
    names = {fid: f.get("name", fid) for fid, f in definitions.items()}
    L = [f"# 채널 특징 추출 요약 — {meta['generated']}", "",
         f"영상 {len(results)}편 · 특징 {len(definitions)}개 · 판정 {meta['judge']} · 모델 {meta.get('model') or '-'} · "
         f"레지스트리 {'동결' if meta['registry_frozen'] else '후보(미동결)'} · 경로 표 {meta['routing_source']}", "",
         "## 증거 확보", "",
         f"- 자막 있음: {sum(1 for v in caption_src.values() if v)} / {len(results)} (파일 {sum(1 for v in caption_src.values() if v == 'file')}, 패킷 {sum(1 for v in caption_src.values() if v == 'packet')})",
         f"- 장면 프레임 있음: {sum(packet_ok.values())} / {len(results)}",
         f"- 자막을 나눠 물은 영상: {sum(1 for r in results if r['chunks'] > 1)}",
         f"- 판정기 호출 {sum(r['api_calls'] for r in results)}회 · 캐시 적중 {meta['cache_hits']}회", "",
         "## 특징별 판정 (0 / 1 / U)", "",
         "| 특징 | 0 | 1 | U | U 비율 | 시각 단계로 해결 | 쇼츠 U | 롱폼 U |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for fid in definitions:
        c = Counter(r["labels"][fid] for r in results)
        vis = sum(1 for r in results if r["provenance"][fid]["visual_escalated"] and r["labels"][fid] != "U")
        ax = defaultdict(Counter)
        for r in results:
            ax[byid[r["video_id"]].get("length_axis")][r["labels"][fid]] += 1
        n = len(results) or 1
        L.append(f"| {names[fid]} | {c['0']} | {c['1']} | {c['U']} | {c['U'] / n * 100:.0f}% | {vis} | "
                 f"{ax['shorts']['U']}/{sum(ax['shorts'].values())} | {ax['long']['U'] + ax['standard']['U']}/{sum(ax['long'].values()) + sum(ax['standard'].values())} |")
    L += ["", "읽는 법: U 비율이 높은 특징은 지금 증거(자막·장면)로는 자동 판정이 안 되는 특징이다. "
          "쇼츠 U가 특히 높으면 자막이 없어서이고, 장면 프레임을 붙이면 줄어든다.", "",
          "## 한계", "",
          "- 판정기의 confidence는 주관적 표시이며 정확도가 아니다. 사람 정답과 대조한 정확도는 `evaluate`로 따로 잰다.",
          "- 자막·장면 안의 성과 언급까지 지운 것은 아니다. 판정기에는 성과를 근거로 쓰지 말라고 지시한다.",
          "- 시각 단계의 0은 자막 인용으로 배제 근거가 있을 때만 인정된다. 프레임에 안 보인다는 이유로 0이 되지 않는다."]
    return "\n".join(L)


def write_outputs(out, results, rows, definitions, meta, caption_src, packet_ok, registry_sha, review_share):
    out = Path(out)
    labels = {r["video_id"]: dict(r["labels"]) for r in results}
    (out / "labels.json").write_text(json.dumps({
        "extractor_version": VERSION, "complete_registry_matrix": True, "registry_sha256": registry_sha,
        "feature_scope": list(definitions), "scope": meta["scope"], "judge": meta["judge"], "model": meta.get("model"),
        "registry_frozen": meta["registry_frozen"], "empirically_validated": False,
        "note": "AI 판정(검증 전). U는 자료 부족이며 0이 아니다. 사람 정답 대조는 evaluate 결과를 본다.",
        "labels": labels}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "predictions.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    queue = review_sample(results, rows, review_share)
    with (out / "review_queue.jsonl").open("w", encoding="utf-8") as fh:
        for q in queue:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    (out / "summary.md").write_text(summarize(results, rows, definitions, caption_src, packet_ok, meta), encoding="utf-8")
    meta = {**meta, "rows": len(results), "review_queue": len(queue),
            "label_counts": {v: sum(r["labels"][f] == v for r in results for f in definitions) for v in ("0", "1", "U")}}
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def prepare(a):
    rows = load_content(a.content)
    split = load_split(a.split) if a.split else None
    rows = select_scope(rows, split, a.scope, a.unseal_holdout)
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        raise ValueError("대상 영상이 없다")
    features, rmeta = load_registry_any(a.registry)
    routing, routing_source = routing_for(features, a.routing)
    set_feature_routing(routing)
    definitions = definitions_by_id(features)
    out = Path(a.out)
    if out.exists():
        raise FileExistsError(f"새 출력 폴더가 필요하다: {out}")
    out.mkdir(parents=True)
    meta = {"extractor_version": VERSION, "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "content": str(a.content), "registry": str(a.registry), "registry_sha256": sha(a.registry),
            "registry_frozen": rmeta["frozen"], "registry_version": rmeta.get("registry_version"),
            "routing_source": routing_source, "routing": routing,
            "split": str(a.split) if a.split else None, "scope": a.scope if a.split else "all",
            "captions": str(a.captions) if a.captions else None, "evidence_root": str(a.evidence_root) if a.evidence_root else None,
            "judge": a.judge, "model": getattr(a, "model", None), "cache_hits": 0}
    return rows, definitions, routing, out, meta


def cmd_run(a):
    rows, definitions, routing, out, meta = prepare(a)
    from .judge import MULTI_PROMPT
    prompt_sha = hashlib.sha256(MULTI_PROMPT.encode()).hexdigest()
    caption_src, packet_ok = {}, {}
    if a.judge == "offline":
        jdir = out / "judge_input"
        jdir.mkdir()
        for r in rows:
            cap, src = caption_for(r["video_id"], a.captions, a.evidence_root)
            caption_src[r["video_id"]] = src
            packet_ok[r["video_id"]] = False
            (jdir / f"{r['video_id']}.json").write_text(json.dumps({
                "video_id": r["video_id"], "mode": "text", "instructions": MULTI_PROMPT,
                "definitions": list(definitions.values()),
                "metadata": {k: v for k, v in r.items() if k in FIELDS}, "caption": cap,
                "answer_format": {"judgments": [{"feature_id": fid, "label": "0|1|U", "confidence": "low|medium|high", "reason": "근거 문장"} for fid in definitions]},
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        (jdir / "README.md").write_text(
            "# 오프라인 판정 입력\n\n영상마다 JSON 하나. instructions·definitions·metadata·caption을 읽고 "
            "answer_format대로 `{\"judgments\":[...]}`를 같은 파일 이름으로 답안 폴더에 쓴다. "
            "모든 특징에 하나씩, 값은 \"0\"/\"1\"/\"U\", reason은 근거 문장. 성과값은 쓰지 않는다.\n\n"
            "답안을 넣은 뒤: `python -m tools.feature_extractor.channel import --run <이 실행 폴더> --answers <답안 폴더>`\n",
            encoding="utf-8")
        meta.update(rows=len(rows), judge_inputs=len(rows), captions_found=sum(1 for v in caption_src.values() if v))
        (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "_pending.json").write_text(json.dumps({"rows": rows, "caption_src": caption_src}, ensure_ascii=False), encoding="utf-8")
        print(f"오프라인 입력 {len(rows)}건 → {jdir} (자막 {meta['captions_found']}건). 답안 후 import.")
        return 0
    from .judge import text_judge, visual_judge
    import os
    if not a.model or not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("--judge api 는 --model 과 ANTHROPIC_API_KEY 가 필요하다")
    cache = Cache(a.cache)
    results = []
    for i, r in enumerate(rows, 1):
        cap, src = caption_for(r["video_id"], a.captions, a.evidence_root)
        caption_src[r["video_id"]] = src
        metadata = {k: v for k, v in r.items() if k in FIELDS}
        packet = packet_for(r["video_id"], a.evidence_root, metadata, cap, a.max_frames)
        packet_ok[r["video_id"]] = packet is not None
        try:
            res = run_one(r, definitions, routing, caption=cap, packet=packet, model=a.model,
                          text_judge=text_judge, visual_judge=visual_judge, cache=cache,
                          prompt_sha=prompt_sha, registry_sha=meta["registry_sha256"])
        except Exception as exc:  # 실패한 영상은 U로 남기고 계속 간다
            res = {"video_id": r["video_id"], "labels": {fid: "U" for fid in definitions},
                   "provenance": {fid: {"text": {"feature_id": fid, "label": "U", "confidence": "low", "reason": f"failed:{type(exc).__name__}"},
                                        "visual_eligible": False, "visual_escalated": False, "visual": None,
                                        "final_label": "U", "visual_rejection": None} for fid in definitions},
                   "chunks": 0, "api_calls": 0, "error": f"{type(exc).__name__}: {exc}"[:300]}
        results.append(res)
        print(f"[{i}/{len(rows)}] {r['video_id']} 자막={src or '-'} 프레임={'Y' if packet else '-'} "
              f"U={sum(1 for v in res['labels'].values() if v == 'U')}/{len(definitions)}", file=sys.stderr)
    meta["cache_hits"] = cache.hits
    m = write_outputs(out, results, rows, definitions, meta, caption_src, packet_ok, meta["registry_sha256"], a.review_share)
    print(f"완료: {m['rows']}편 · 판정 {m['label_counts']} · 검토 대기 {m['review_queue']}편 → {out}/summary.md")
    return 0


def cmd_import(a):
    out = Path(a.run)
    meta = read_json(out / "manifest.json")
    pend = read_json(out / "_pending.json")
    rows, caption_src = pend["rows"], pend["caption_src"]
    features, _ = load_registry_any(meta["registry"])
    set_feature_routing(meta["routing"])
    definitions = definitions_by_id(features)
    results, missing = [], []
    for r in rows:
        p = Path(a.answers) / f"{r['video_id']}.json"
        if not p.is_file():
            missing.append(r["video_id"])
            continue
        ans = read_json(p)
        metadata = {k: v for k, v in r.items() if k in FIELDS}
        cap = read_json(out / "judge_input" / f"{r['video_id']}.json").get("caption")
        res = extract_video(metadata, cap, list(definitions.values()), text_judgments=ans["judgments"])
        res["chunks"], res["api_calls"] = 1, 0
        results.append(res)
    if missing:
        print(f"답안 없음 {len(missing)}건 (예: {missing[:3]}) — 그 영상은 제외했다", file=sys.stderr)
    if not results:
        raise ValueError("가져올 답안이 없다")
    done = {r["video_id"] for r in results}
    m = write_outputs(out, results, [r for r in rows if r["video_id"] in done], definitions, meta,
                      {k: v for k, v in caption_src.items() if k in done}, {k: False for k in done},
                      meta["registry_sha256"], a.review_share)
    print(f"가져오기 완료: {m['rows']}편 · 판정 {m['label_counts']} → {out}/labels.json")
    return 0


def evaluate(pred_labels, ref_labels, axes=None):
    """사람 정답 대조. U는 정답으로 바뀌지 않는다. 특징별·축별로 덮은 비율과 맞은 비율을 따로 낸다."""
    def norm(v):
        return "U" if v == "U" else str(int(v))
    fids = sorted({f for fs in ref_labels.values() for f in fs})
    rep = {}
    for fid in fids:
        row = {"n_ref": 0, "ref_nonU": 0, "pred_nonU_on_ref_nonU": 0, "agree": 0, "false_1": 0, "false_0": 0, "by_axis": {}}
        for vid, fs in ref_labels.items():
            if fid not in fs or vid not in pred_labels or fid not in pred_labels[vid]:
                continue
            rv, pv = norm(fs[fid]), norm(pred_labels[vid][fid])
            row["n_ref"] += 1
            ax = (axes or {}).get(vid, "all")
            b = row["by_axis"].setdefault(ax, {"ref_nonU": 0, "covered": 0, "agree": 0})
            if rv == "U":
                continue
            row["ref_nonU"] += 1
            b["ref_nonU"] += 1
            if pv == "U":
                continue
            row["pred_nonU_on_ref_nonU"] += 1
            b["covered"] += 1
            if pv == rv:
                row["agree"] += 1
                b["agree"] += 1
            elif pv == "1":
                row["false_1"] += 1
            else:
                row["false_0"] += 1
        row["coverage"] = row["pred_nonU_on_ref_nonU"] / row["ref_nonU"] if row["ref_nonU"] else None
        row["accuracy_on_covered"] = row["agree"] / row["pred_nonU_on_ref_nonU"] if row["pred_nonU_on_ref_nonU"] else None
        rep[fid] = row
    return rep


def cmd_evaluate(a):
    out = Path(a.run)
    pred = read_json(out / "labels.json")["labels"]
    ref = read_json(a.reference)
    ref = ref["labels"] if "labels" in ref else ref
    axes = {}
    pend = out / "_pending.json"
    if pend.is_file():
        axes = {r["video_id"]: r.get("length_axis") for r in read_json(pend)["rows"]}
    rep = evaluate(pred, ref, axes)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["| 특징 | 정답 있는 영상 | 덮은 비율 | 맞은 비율 | 1로 잘못 | 0으로 잘못 |", "|---|---:|---:|---:|---:|---:|"]
    for fid, r in rep.items():
        cov = "-" if r["coverage"] is None else "%.0f%%" % (r["coverage"] * 100)
        acc = "-" if r["accuracy_on_covered"] is None else "%.0f%%" % (r["accuracy_on_covered"] * 100)
        L.append(f"| {fid} | {r['ref_nonU']} | {cov} | {acc} | {r['false_1']} | {r['false_0']} |")
    print("\n".join(L))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="channel", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--content", required=True)
    r.add_argument("--registry", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--split")
    r.add_argument("--scope", default="development", choices=["development", "discovery", "holdout", "all"])
    r.add_argument("--unseal-holdout", action="store_true")
    r.add_argument("--captions")
    r.add_argument("--evidence-root")
    r.add_argument("--routing")
    r.add_argument("--judge", default="offline", choices=["offline", "api"])
    r.add_argument("--model")
    r.add_argument("--cache")
    r.add_argument("--limit", type=int)
    r.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES)
    r.add_argument("--review-share", type=float, default=0.1)
    r.set_defaults(fn=cmd_run)
    i = sub.add_parser("import")
    i.add_argument("--run", required=True)
    i.add_argument("--answers", required=True)
    i.add_argument("--review-share", type=float, default=0.1)
    i.set_defaults(fn=cmd_import)
    e = sub.add_parser("evaluate")
    e.add_argument("--run", required=True)
    e.add_argument("--reference", required=True)
    e.add_argument("--out", required=True)
    e.set_defaults(fn=cmd_evaluate)
    a = p.parse_args(argv)
    try:
        return a.fn(a) or 0
    except (ValueError, FileExistsError) as exc:
        print(f"거부: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
