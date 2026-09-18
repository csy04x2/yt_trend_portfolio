# -*- coding: utf-8 -*-
"""자막만 받는다 (영상 내려받기 없음). youtube-transcript-api 로 자동 자막을 읽어 <video_id>.txt 로 저장.

  python -m tools.stage2_evidence.fetch_captions --content docs/prototype/chim-evidence.json --out backend/data/captions/chim \
      [--split split.csv --scope development] [--limit N]

산출: <out>/<video_id>.txt (자막 본문), <out>/_census.json (영상별 있음/없음·글자 수·언어).
성과값은 읽지 않는다. 이미 받은 파일은 건너뛴다. 유튜브 자막 endpoint 접근의 약관 판단은 팀 결정 사항이다.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--content", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--split")
    p.add_argument("--scope", default="development")
    p.add_argument("--limit", type=int)
    p.add_argument("--langs", default="ko,ko-KR")
    a = p.parse_args(argv)
    from youtube_transcript_api import YouTubeTranscriptApi
    d = json.load(open(a.content, encoding="utf-8-sig"))
    videos = d["videos"] if isinstance(d, dict) else d
    if a.split:
        split = {r["video_id"]: r["split"] for r in csv.DictReader(open(a.split, encoding="utf-8-sig", newline=""))}
        videos = [v for v in videos if split.get(v["video_id"]) == a.scope]
    if a.limit:
        videos = videos[:a.limit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    api = YouTubeTranscriptApi()
    census, t0 = [], time.time()
    for i, v in enumerate(videos, 1):
        vid = v["video_id"]
        dst = out / f"{vid}.txt"
        row = {"video_id": vid, "length_axis": v.get("length_axis"), "available": False, "chars": 0, "lang": None, "generated": None, "error": None}
        if dst.is_file():
            row.update(available=True, chars=len(dst.read_text(encoding="utf-8")), cached=True)
        else:
            try:
                tl = api.list(vid)
                tr = tl.find_transcript(a.langs.split(","))
                text = "\n".join(s.text.strip() for s in tr.fetch() if s.text and s.text.strip())
                if text:
                    dst.write_text(text, encoding="utf-8")
                    row.update(available=True, chars=len(text), lang=tr.language_code, generated=tr.is_generated)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            time.sleep(3.0)
        census.append(row)
        print(f"[{i}/{len(videos)}] {vid} {row['length_axis'] or '':8} {'OK' if row['available'] else '--'} {row['chars']:>6} {row['error'] or ''} ({time.time()-t0:.0f}s)", file=sys.stderr)
    json.dump(census, open(out / "_census.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(r["available"] for r in census)
    by = {}
    for r in census:
        b = by.setdefault(r["length_axis"], [0, 0]); b[1] += 1; b[0] += r["available"]
    print(f"자막 {ok}/{len(census)} · " + " · ".join(f"{k} {v[0]}/{v[1]}" for k, v in by.items()) + f" · 총 {sum(r['chars'] for r in census):,}자")
    return 0


if __name__ == "__main__":
    sys.exit(main())
