"""Fixed 30/30/40 split with globally balanced deterministic stratification."""
import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .blind import validate_rows
from .data import load_content

SPLITS = ("discovery", "development", "holdout")
WEIGHTS = (3, 3, 4)
SPLIT_FIELDS = ("video_id", "split", "seed", "created_at")


def assignments(rows, seed=42, stratify=True):
    validate_rows(rows)
    if not rows:
        raise ValueError("Cannot split an empty dataset")
    n = len(rows)
    targets = [n * w // 10 for w in WEIGHTS]
    order = sorted(range(3), key=lambda j: (-(n * WEIGHTS[j] % 10), j))
    for j in order[:n - sum(targets)]:
        targets[j] += 1
    groups = {}
    for row in rows:
        axis = (row.get("length_axis") or "") if stratify else ""
        groups.setdefault(axis, []).append(row["video_id"])
    counts = {k: [len(v) * w // 10 for w in WEIGHTS] for k, v in groups.items()}
    remaining = [targets[j] - sum(c[j] for c in counts.values()) for j in range(3)]
    # Largest stratum deficit first, constrained by exact global target capacity.
    while sum(remaining):
        choices = [(len(groups[k]) * WEIGHTS[j] - 10 * counts[k][j], k, j)
                   for k in sorted(groups) if sum(counts[k]) < len(groups[k])
                   for j in range(3) if remaining[j]]
        _, k, j = min(choices, key=lambda x: (-x[0], x[1], x[2]))
        counts[k][j] += 1
        remaining[j] -= 1
    out = {}
    for k in sorted(groups):
        ids = sorted(groups[k], key=lambda vid: (
            hashlib.sha256(f"{seed}\0{vid}".encode()).digest(), vid))
        start = 0
        for j, split in enumerate(SPLITS):
            for vid in ids[start:start + counts[k][j]]:
                out[vid] = split
            start += counts[k][j]
    return dict(sorted(out.items()))


def write_split(rows, output, seed=42, stratify=True, force=False):
    output = Path(output)
    if output.exists() and not force:
        raise FileExistsError(f"Split frozen: {output}; use --force explicitly")
    result = assignments(rows, seed, stratify)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if force else "x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SPLIT_FIELDS)
        writer.writeheader()
        writer.writerows(dict(video_id=v, split=s, seed=seed, created_at=now)
                         for v, s in result.items())
    return result


def read_split(path, rows):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != SPLIT_FIELDS:
            raise ValueError("Invalid split schema")
        records = list(reader)
    result = {}
    seeds, dates = set(), set()
    for r in records:
        if None in r or any(v is None for v in r.values()):
            raise ValueError("Malformed split row")
        if r["video_id"] in result or r["split"] not in SPLITS:
            raise ValueError("Duplicate video_id or invalid split")
        seeds.add(int(r["seed"]))
        dates.add(r["created_at"])
        if datetime.fromisoformat(r["created_at"]).tzinfo is None:
            raise ValueError("Split timestamp must have timezone")
        result[r["video_id"]] = r["split"]
    if len(seeds) != 1 or len(dates) != 1 or set(result) != {r["video_id"] for r in rows}:
        raise ValueError("Split/source membership or provenance mismatch")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-stratify", action="store_true")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    if a.input.resolve() == a.output.resolve():
        p.error("Input and output must differ")
    write_split(load_content(a.input), a.output, a.seed, not a.no_stratify, a.force)


if __name__ == "__main__":
    main()
