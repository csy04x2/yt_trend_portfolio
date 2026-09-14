"""CLI.

  python -m feature_outcome run    --evidence E.json --split split.csv --registry R.json --labels L.json \
                                   [--events events.json] [--split-name development] [--u-as-control] \
                                   [--unseal-holdout] --out DIR
  python -m feature_outcome labels --evidence E.json --config title-regex-config.json --out L.json   (자리표시자 판정 생성)
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

from .breakout import breakouts_in_split, flag_breakouts, recompute_multiples
from .labels import label_by_title_regex, load_labels, load_registry
from .outcome import HoldoutSealed, feature_outcome
from .report import render
from .trend import monthly_cohorts


def _videos(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["videos"] if isinstance(d, dict) else d, (d.get("channel", "") if isinstance(d, dict) else "")


def cmd_labels(a):
    videos, _ = _videos(a.evidence)
    cfg = json.load(open(a.config, encoding="utf-8"))
    labels = label_by_title_regex(videos, cfg)
    json.dump({"judged_by": "title-regex placeholder", "config": str(a.config), "note": "자리표시자. 사람·LLM 판정으로 교체할 것. U는 0이 아니다.", "labels": labels},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"labels: {len(labels)}편 × {len(cfg['features'])}특징 → {a.out}")


def cmd_run(a):
    videos, channel = _videos(a.evidence)
    split = {r["video_id"]: r["split"] for r in csv.DictReader(open(a.split, encoding="utf-8"))}
    registry = load_registry(a.registry)
    labels = load_labels(a.labels, registry)
    events = json.load(open(a.events, encoding="utf-8")) if a.events else None
    flags = flag_breakouts(videos, k_iqr=a.k_iqr, multiple_min=a.multiple_min, events=events)
    new_mult = recompute_multiples(videos, flags)
    old_mult = {v["video_id"]: v.get("view_multiple") for v in videos}
    trend_rows = monthly_cohorts(videos, flags)
    try:
        rows = feature_outcome(videos, labels, flags, split, a.split_name, min_cell=a.min_cell,
                               unseal_holdout=a.unseal_holdout, u_as_control=a.u_as_control)
        for axis in sorted({v["length_axis"] for v in videos}):
            rows += feature_outcome(videos, labels, flags, split, a.split_name, min_cell=a.min_cell,
                                    unseal_holdout=a.unseal_holdout, u_as_control=a.u_as_control, axis=axis)
    except HoldoutSealed as e:
        print(f"거부: {e}", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "breakout.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["video_id", "title", "axis", "published_at", "view_count", "view_multiple", "view_multiple_ex", "rule_iqr", "rule_multiple", "rule_event", "breakout", "split"])
        for v in videos:
            f = flags[v["video_id"]]
            w.writerow([v["video_id"], v["title"], v["length_axis"], v["published_at"][:10], v["view_count"], v.get("view_multiple"),
                        new_mult[v["video_id"]], f["rule_iqr"], f["rule_multiple"], f["rule_event"], f["breakout"], split.get(v["video_id"], "")])
    json.dump({"trend": trend_rows, "outcome": rows}, open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meta = {"channel": channel, "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "inputs": {"evidence": Path(a.evidence).name, "split": Path(a.split).name, "registry": Path(a.registry).name,
                       "labels": Path(a.labels).name, "events": Path(a.events).name if a.events else "-"},
            "k_iqr": a.k_iqr, "multiple_min": a.multiple_min, "split_name": a.split_name, "outcome": "view_multiple", "min_cell": a.min_cell}
    (out / "report.md").write_text(render(meta, videos, flags, breakouts_in_split(flags, split), trend_rows, old_mult, new_mult, rows), encoding="utf-8")
    if a.evidence_out:
        byid = {v["video_id"]: v for v in videos}
        shifts = sorted(
            ({"video_id": vid, "title": byid[vid]["title"], "axis": byid[vid]["length_axis"], "old": old_mult[vid], "new": new_mult[vid]}
             for vid in flags if not flags[vid]["breakout"] and old_mult.get(vid) and new_mult.get(vid) is not None),
            key=lambda s: -abs(s["new"] - s["old"]) / s["old"])[:10]
        payload = {
            "generated": meta["generated"], "video_n": len(videos), "split_name": a.split_name,
            "rules": {"k_iqr": a.k_iqr, "multiple_min": a.multiple_min, "events": meta["inputs"]["events"]},
            "labels_source": Path(a.labels).name, "registry": Path(a.registry).name, "u_as_control": a.u_as_control,
            "feature_names": {f["feature_id"]: f["name"] for f in registry["features"]},
            "labels": labels,
            "split_hits": breakouts_in_split(flags, split),
            "breakouts": [dict(video_id=vid, title=byid[vid]["title"], axis=byid[vid]["length_axis"], published_at=byid[vid]["published_at"][:10],
                               view_count=byid[vid]["view_count"], view_multiple=byid[vid].get("view_multiple"), **flags[vid])
                          for vid in sorted(flags, key=lambda x: -byid[x]["view_count"]) if flags[vid]["breakout"]],
            "trend": trend_rows, "outcome": rows, "multiple_shifts": shifts,
        }
        d = json.load(open(a.evidence, encoding="utf-8"))
        d["feature_outcome"] = payload
        json.dump(d, open(a.evidence_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, allow_nan=False)
        print(f"evidence + feature_outcome → {a.evidence_out}")
    print(f"급등 영상 {sum(f['breakout'] for f in flags.values())}/{len(flags)}편, 특징 행 {len(rows)} → {out}/report.md")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="feature_outcome", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--evidence", required=True)
    r.add_argument("--split", required=True)
    r.add_argument("--registry", required=True)
    r.add_argument("--labels", required=True)
    r.add_argument("--events")
    r.add_argument("--out", required=True)
    r.add_argument("--split-name", default="development", choices=["discovery", "development", "holdout"])
    r.add_argument("--k-iqr", type=float, default=3.0)
    r.add_argument("--multiple-min", type=float, default=3.0)
    r.add_argument("--min-cell", type=int, default=4)
    r.add_argument("--u-as-control", action="store_true", help="U를 대조군으로(자리표시자 판정 전용)")
    r.add_argument("--unseal-holdout", action="store_true", help="holdout 봉인 해제. 정의 동결 후 한 번만")
    r.add_argument("--evidence-out", help="evidence JSON에 feature_outcome 키를 붙여 저장 (대시보드용)")
    r.set_defaults(fn=cmd_run)
    l = sub.add_parser("labels")
    l.add_argument("--evidence", required=True)
    l.add_argument("--config", required=True)
    l.add_argument("--out", required=True)
    l.set_defaults(fn=cmd_labels)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
