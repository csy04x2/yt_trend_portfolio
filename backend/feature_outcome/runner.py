"""Finding Runner v0.1: read frozen artifacts and write a new Development run.

From backend: python -m feature_outcome.runner --registry R.json --labels L.json
--split split.csv --evidence E.json --out feature_discovery/outputs/experiment-analysis/RUN_ID
Shared input JSON is decoded by frozen.prepare; only Development rows are analyzed.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from .finding import VERSION as ENGINE_VERSION, build_findings
from .frozen import prepare
from .labels import load_registry

VERSION = "0.1"


def run(*, registry, labels, split, evidence, out, split_name="development"):
    """Run the existing engine without changing inputs or allowing other splits."""
    if split_name != "development":
        raise ValueError("Finding Runner v0.1 only analyzes the Development split")
    # Reject plain registries (including a forged internal _envelope marker).
    with open(registry, encoding="utf-8") as stream:
        if "registry" not in json.load(stream):
            raise ValueError("Finding Runner requires a validated frozen registry envelope")
    loaded = load_registry(registry)
    args = SimpleNamespace(registry=registry, labels=labels, split=split,
                           evidence=evidence, out=out, split_name="development",
                           unseal_holdout=False, u_as_control=False,
                           events=None, evidence_out=None)
    videos, _, _, scoped_labels, provenance = prepare(args, loaded)
    findings = build_findings(videos, scoped_labels, loaded, split_name="development")
    manifest = {
        "runner_version": VERSION,
        "engine_version": ENGINE_VERSION,
        "split": "development",
        "registry_version": loaded["_envelope"]["freeze_metadata"]["registry_version"],
        "inputs": {name: str(Path(path).resolve()) for name, path in
                   (("registry", registry), ("labels", labels), ("split", split), ("evidence", evidence))},
        "input_sha256": provenance["input_sha256"],
        "bootstrap_iterations": None,
        "seed": None,
        "bootstrap_note": "Not implemented by this engine version",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    # Serialize before reserving the directory; mkdir also rejects concurrent reuse.
    artifacts = {"manifest.json": manifest, "findings.json": findings}
    serialized = {name: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                  for name, value in artifacts.items()}
    destination = Path(out).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in serialized.items():
        with (destination / name).open("x", encoding="utf-8") as stream:
            stream.write(content)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("registry", "labels", "split", "evidence", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--split-name", default="development", choices=["development"])
    args = parser.parse_args(argv)
    try:
        destination = run(**vars(args))
    except (ValueError, OSError) as error:
        parser.exit(2, f"Finding Runner refused: {error}\n")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
