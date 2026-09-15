#!/usr/bin/env python3
"""
Stage 2 evidence collector for guest_present.

Scope:
- Only Stage-1 U cases.
- Fetch subtitles if available.
- Temporarily download a low-resolution copy.
- Sample visual frames across the video.
- Build evidence_packet.json per video.
- Never uses views/likes/comments/performance.

This script DOES NOT reveal or use Human gold labels.
"""

from __future__ import annotations
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


SHORT_RATIOS = [0.10, 0.30, 0.50, 0.70, 0.90]
LONG_RATIOS = [0.05, 0.20, 0.40, 0.60, 0.80, 0.95]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", check=check
    )


def require(exe: str):
    if shutil.which(exe) is None:
        raise SystemExit(f"[ERROR] Missing dependency: {exe}")


def yt_base(cookie_browser: str | None) -> list[str]:
    # Use the Python module instead of relying on yt-dlp.exe being on PATH.
    cmd = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-warnings", "--no-playlist"]
    if cookie_browser:
        cmd += ["--cookies-from-browser", cookie_browser]
    return cmd


def parse_duration(video_path: Path) -> float:
    cp = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ])
    return float(cp.stdout.strip())


def clean_vtt(text: str) -> str:
    lines = []
    seen = set()
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s == "WEBVTT" or s.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in s or re.fullmatch(r"\d+", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        s = html.unescape(s).strip()
        # Auto captions frequently repeat the same line.
        if not s or s in seen:
            continue
        seen.add(s)
        lines.append(s)
    return "\n".join(lines)


def fetch_subtitles(url: str, vdir: Path, cookie_browser: str | None) -> dict:
    subs_dir = vdir / "subs"
    subs_dir.mkdir(exist_ok=True)
    outtmpl = str(subs_dir / "%(id)s.%(ext)s")

    cmd = yt_base(cookie_browser) + [
        "--skip-download",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", "ko.*,ko,en.*",
        "--sub-format", "vtt",
        "-o", outtmpl,
        url,
    ]
    cp = run(cmd, check=False)

    candidates = sorted(subs_dir.glob("*.vtt"))
    preferred = sorted(
        candidates,
        key=lambda p: (
            0 if ".ko" in p.name else 1,
            0 if "orig" not in p.name else 1,
            len(p.name)
        )
    )
    if not preferred:
        return {
            "available": False,
            "text": None,
            "files": [],
            "stderr_tail": cp.stderr[-1200:]
        }

    texts = []
    for p in preferred[:2]:
        cleaned = clean_vtt(p.read_text(encoding="utf-8", errors="replace"))
        if cleaned:
            texts.append(cleaned)

    combined = "\n".join(texts).strip() or None
    return {
        "available": bool(combined),
        "text": combined,
        "files": [p.name for p in preferred],
        "stderr_tail": cp.stderr[-1200:]
    }


def download_lowres(url: str, vdir: Path, cookie_browser: str | None) -> Path:
    media_dir = vdir / "temp_media"
    media_dir.mkdir(exist_ok=True)
    outtmpl = str(media_dir / "%(id)s.%(ext)s")
    cmd = yt_base(cookie_browser) + [
        "-f", "bv*[height<=480]+ba/b[height<=480]/best[height<=480]",
        "--merge-output-format", "mp4",
        "-o", outtmpl,
        url,
    ]
    cp = run(cmd, check=False)
    if cp.returncode != 0:
        raise RuntimeError("yt-dlp video download failed:\n" + cp.stderr[-2000:])

    files = [p for p in media_dir.iterdir() if p.is_file() and not p.name.endswith(".part")]
    videos = [p for p in files if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
    if not videos:
        raise RuntimeError("yt-dlp completed but no downloaded video file was found.")
    return max(videos, key=lambda p: p.stat().st_size)


def extract_frames(video_path: Path, vdir: Path, length_axis: str) -> list[dict]:
    frames_dir = vdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    duration = parse_duration(video_path)
    ratios = SHORT_RATIOS if length_axis == "shorts" else LONG_RATIOS
    frames = []

    for i, ratio in enumerate(ratios, start=1):
        ts = max(0.0, min(duration - 0.05, duration * ratio))
        out = frames_dir / f"frame_{i:02d}_{ts:.2f}s.jpg"
        cp = run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{ts:.3f}", "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale='min(960,iw)':-2",
            "-q:v", "3",
            str(out)
        ], check=False)
        if cp.returncode == 0 and out.exists():
            frames.append({
                "timestamp_sec": round(ts, 3),
                "ratio": ratio,
                "path": str(out.resolve())
            })
    return frames


def collect_one(item: dict, outroot: Path, cookie_browser: str | None, keep_media: bool,
                feature_definition: str | None = None) -> dict:
    vid = item["video_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise ValueError("Invalid video ID")
    if item.get("stage1_label", "U") != "U":
        raise ValueError("Only Stage 1 U may be collected")
    if item["youtube_url"] != f"https://www.youtube.com/watch?v={vid}":
        raise ValueError("Expected canonical video URL")
    vdir = outroot / vid
    vdir.mkdir(parents=True, exist_ok=True)

    packet = {
        "version": "chim-stage2-evidence-packet-v0.1",
        "video_id": vid,
        "youtube_url": item["youtube_url"],
        "title": item.get("title"),
        "length_axis": item.get("length_axis"),
        "stage1_label": "U",
        "stage1_reason": item.get("stage_1_reason"),
        "feature": "guest_present",
        "feature_definition": feature_definition or (
            "A non-Chim person participates in the content. "
            "Exclude staff/delivery/background people and people only appearing inside external media."
        ),
        "forbidden_evidence": [
            "views", "likes", "comments", "relative performance", "audience behavior"
        ],
        "caption": None,
        "frames": [],
        "status": "started",
        "errors": []
    }

    try:
        packet["caption"] = fetch_subtitles(item["youtube_url"], vdir, cookie_browser)
    except Exception as e:
        packet["caption"] = {"available": False, "text": None, "files": []}
        packet["errors"].append(f"caption: {e}")

    media = None
    try:
        media = download_lowres(item["youtube_url"], vdir, cookie_browser)
        packet["frames"] = extract_frames(media, vdir, item.get("length_axis", "shorts"))
    except Exception as e:
        packet["errors"].append(f"visual: {e}")
    finally:
        if media and media.exists() and not keep_media:
            media.unlink(missing_ok=True)
            try:
                media.parent.rmdir()
            except OSError:
                pass

    if packet["frames"] or (packet["caption"] and packet["caption"].get("available")):
        packet["status"] = "evidence_ready"
    else:
        packet["status"] = "evidence_failed"

    (vdir / "evidence_packet.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return packet


def build_judge_jsonl(packets: list[dict], outroot: Path):
    path = outroot / "judge_input.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for p in packets:
            compact = {
                "video_id": p["video_id"],
                "title": p["title"],
                "length_axis": p["length_axis"],
                "feature": p["feature"],
                "feature_definition": p["feature_definition"],
                "caption": {
                    "available": bool(p.get("caption", {}).get("available")),
                    "text": p.get("caption", {}).get("text")
                },
                "frames": p["frames"],
                "requested_output": {
                    "label": "0|1|U",
                    "confidence": "low|medium|high",
                    "evidence": [
                        {"type": "caption|visual|metadata", "detail": "string", "timestamp_sec": "number|null"}
                    ]
                }
            }
            f.write(json.dumps(compact, ensure_ascii=False) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="stage2_escalation_15.json")
    ap.add_argument("--out", default="stage2_output")
    ap.add_argument("--cookies-from-browser", choices=["chrome", "edge", "firefox"], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--keep-media", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    require("ffmpeg")
    require("ffprobe")

    queue = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    if args.limit:
        queue = queue[:args.limit]

    print(f"[INFO] queue: {len(queue)} videos")
    print("[INFO] performance/audience data are not used.")

    if args.dry_run:
        for x in queue:
            print(x["video_id"], x["length_axis"], x["title"])
        return 0

    outroot = Path(args.out)
    outroot.mkdir(parents=True, exist_ok=True)
    packets = []
    for i, item in enumerate(queue, start=1):
        print(f"[{i}/{len(queue)}] {item['video_id']} - {item['title']}")
        p = collect_one(item, outroot, args.cookies_from_browser, args.keep_media)
        packets.append(p)
        print(f"  -> {p['status']}, frames={len(p['frames'])}, caption={p.get('caption',{}).get('available')}")

    judge_path = build_judge_jsonl(packets, outroot)
    summary = {
        "videos": len(packets),
        "evidence_ready": sum(p["status"] == "evidence_ready" for p in packets),
        "evidence_failed": sum(p["status"] == "evidence_failed" for p in packets),
        "with_caption": sum(bool(p.get("caption", {}).get("available")) for p in packets),
        "with_frames": sum(bool(p.get("frames")) for p in packets),
        "judge_input": str(judge_path.resolve())
    }
    (outroot / "collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
