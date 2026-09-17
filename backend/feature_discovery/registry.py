"""Validate registry against the bundled JSON Schema subset, without dependencies."""
import argparse
import json
import math
from pathlib import Path

SCHEMA = Path(__file__).with_name("feature_registry") / "schema.json"


def _validate(value, schema, path="$", root=None):
    root = root or schema
    if "$ref" in schema:
        key = schema["$ref"].removeprefix("#/$defs/")
        return _validate(value, root["$defs"][key], path, root)
    checks = {"object": lambda v: isinstance(v, dict),
              "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str)}
    if not checks[schema["type"]](value):
        raise ValueError(f"{path}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum value {value!r}")
    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise ValueError(f"{path}: empty text")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        for i, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{i}]", root)
    if isinstance(value, dict):
        props = schema["properties"]
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"{path}: missing required fields")
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{path}: unexpected fields")
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], f"{path}.{key}", root)


def validate_registry(registry):
    _validate(registry, json.loads(SCHEMA.read_text(encoding="utf-8")))
    keys = [(f["feature_id"], f["version"]) for f in registry["features"]]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate feature_id/version")
    for feature in registry["features"]:
        if feature["value_type"] == "categorical" and not feature.get("categories"):
            raise ValueError("Categorical feature requires categories")


def validate_value(feature, value):
    """Label value contract; no labels are generated or persisted here."""
    if value == "U":
        return
    kind = feature["value_type"]
    valid = ((kind == "binary" and type(value) is int and value in (0, 1))
             or (kind == "numeric" and type(value) in (int, float)
                 and math.isfinite(value))
             or (kind == "categorical" and isinstance(value, str)
                 and value in feature.get("categories", [])))
    if not valid:
        raise ValueError("Invalid feature value")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("registry", type=Path)
    a = p.parse_args()
    registry = json.loads(a.registry.read_text(encoding="utf-8"))
    validate_registry(registry)
    print(f"Valid registry: {len(registry['features'])} features")


if __name__ == "__main__":
    main()
