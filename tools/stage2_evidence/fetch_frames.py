# -*- coding: utf-8 -*-
"""장면 이미지만 받는다 (영상 내려받기 없음). 유튜브 공개 썸네일 서버의 25%·50%·75% 지점 장면(hq1~hq3, 480×360).

  python -m tools.stage2_evidence.fetch_frames --content docs/prototype/chim-evidence.json --out backend/data/frames/chim \
      [--split split.csv --scope development] [--limit N]

산출: <out>/<video_id>/frame_1.jpg … frame_3.jpg 와 evidence_packet.json (channel.py --evidence-root 가 그대로 읽는 형식).
길이를 알면 timestamp_sec = duration × 0.25/0.5/0.75. 대표 썸네일(제작자가 고른 이미지)은 장면이 아니므로 넣지 않는다.
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

RATIOS = ((1, 0.25), (2, 0.5), (3, 0.75))


def fetch(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    dst.write_bytes(data)
    return len(data)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--content", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--split")
    p.add_argument("--scope", default="development")
    p.add_argument("--limit", type=int)
    a = p.parse_args(argv)
    d = json.load(open(a.content, encoding="utf-8-sig"))
    videos = d["videos"] if isinstance(d, dict) else d
    if a.split:
        split = {r["video_id"]: r["split"] for r in csv.DictReader(open(a.split, encoding="utf-8-sig", newline=""))}
        videos = [v for v in videos if split.get(v["video_id"]) == a.scope]
    if a.limit:
        videos = videos[:a.limit]
    out = Path(a.out)
    ok = 0
    for i, v in enumerate(videos, 1):
        vid = v["video_id"]
        vdir = out / vid
        vdir.mkdir(parents=True, exist_ok=True)
        pk = vdir / "evidence_packet.json"
        if pk.is_file():
            ok += 1
            continue
        frames, errors = [], []
        dur = v.get("duration_sec") or 0
        for n, ratio in RATIOS:
            dst = vdir / f"frame_{n}.jpg"
            try:
                fetch(f"https://i.ytimg.com/vi/{vid}/hq{n}.jpg", dst)
                frames.append({"path": dst.name, "timestamp_sec": round(dur * ratio, 2), "ratio": ratio})
            except Exception as exc:
                errors.append(f"hq{n}: {type(exc).__name__}")
        packet = {"version": "ytimg-scene-frames-v0.1", "video_id": vid, "youtube_url": f"https://www.youtube.com/watch?v={vid}",
                  "title": v.get("title"), "length_axis": v.get("length_axis"), "stage1_label": "U", "stage1_reason": "frames only",
                  "feature": None, "feature_definition": None, "forbidden_evidence": ["views", "likes", "comments", "performance"],
                  "caption": {"available": False, "text": None, "files": []}, "frames": frames,
                  "status": "evidence_ready" if frames else "evidence_failed", "errors": errors}
        pk.write_text(json.dumps(packet, ensure_ascii=False, indent=1), encoding="utf-8")
        ok += bool(frames)
        print(f"[{i}/{len(videos)}] {vid} {len(frames)} frames {errors or ''}", file=sys.stderr)
        time.sleep(0.2)
    print(f"장면 확보 {ok}/{len(videos)} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
