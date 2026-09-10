"""Export only discovery content, validating the entire source before writing."""
import argparse
import csv
import json
from pathlib import Path

from .blind import CONTENT_FIELDS, validate_fields, validate_rows
from .data import load_content
from .split_dataset import read_split


def export(rows, split_path, output_dir, fields=CONTENT_FIELDS):
    validate_fields(fields)
    validate_rows(rows)
    split = read_split(split_path, rows)
    packet = [{f: r.get(f) for f in fields} for r in rows
              if split[r["video_id"]] == "discovery"]
    packet.sort(key=lambda r: r["video_id"])
    validate_rows(packet)
    output_dir = Path(output_dir)
    paths = [output_dir / ("blind_discovery." + ext) for ext in ("jsonl", "csv")]
    if any(p.exists() for p in paths):
        raise FileExistsError("Blind export already exists; use a new output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    with paths[0].open("x", encoding="utf-8", newline="\n") as stream:
        for row in packet:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with paths[1].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(packet)
    return packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--split", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    a = p.parse_args()
    export(load_content(a.input), a.split, a.output_dir)


if __name__ == "__main__":
    main()
