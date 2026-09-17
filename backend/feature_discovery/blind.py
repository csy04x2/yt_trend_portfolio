"""Single, closed content schema shared by adapters and export validation."""
import re

CONTENT_FIELDS = (
    "video_id", "title", "description", "transcript", "duration_sec",
    "length_axis", "corner", "playlist", "published_at",
)
# Includes actual metrics/labels in schema.sql, plus future audience families.
FORBIDDEN = re.compile(
    r"view|like|comment|baseline|comparison|excess|normalized|metric|"
    r"unique_commenters|participant|repeat_share|reply|thread|timestamp|"
    r"sentiment|reaction|positive|negative|neutral|approval|contention|"
    r"labeled_ratio|topic_counts|top_.*topics|basis|engagement|audience|"
    r"subscriber|sarcasm|confidence|rationale|rate|multiple", re.I
)


def validate_fields(fields):
    fields = list(fields)
    bad = [f for f in fields if not isinstance(f, str)
           or FORBIDDEN.search(f) or f not in CONTENT_FIELDS]
    if bad:
        raise ValueError(f"Non-content/forbidden fields: {bad}")
    if "video_id" not in fields or len(set(fields)) != len(fields):
        raise ValueError("Unique fields including video_id required")


def validate_rows(rows):
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Content row must be an object")
        validate_fields(row)
        vid = row.get("video_id")
        if not isinstance(vid, str) or not vid.strip() or vid in seen:
            raise ValueError("Nonempty, unique string video_id required")
        seen.add(vid)
        for key, value in row.items():
            if value is None:
                continue
            if key == "duration_sec":
                if type(value) is not int or value < 0:
                    raise ValueError("duration_sec must be a nonnegative integer")
            elif not isinstance(value, str):
                raise ValueError(f"{key} must be text, not nested data")
