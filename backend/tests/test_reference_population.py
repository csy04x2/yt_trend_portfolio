"""고정 reference population · canonical view_multiple 테스트. 합성 데이터만 쓴다."""

import copy
import csv
import dataclasses
import datetime as dt
import json
import pathlib
import random
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.pipeline import reference as ref  # noqa: E402
from feature_outcome import runner  # noqa: E402
from feature_outcome.finding import build_findings  # noqa: E402
from test_finding_engine import data as engine_data, frozen_registry  # noqa: E402
from test_frozen_feature_outcome import case  # noqa: E402,F401

BOUNDARY = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
CAPTURED = "2026-09-10T00:00:00Z"
RULES = dataclasses.replace(ref.DEFAULT_RULES, min_per_axis=3)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def up(vid, days_before, views=1000, dur=60, **kw):
    """boundary 기준 days_before 일 전에 게시된 업로드 (음수면 boundary 이후)."""
    row = {"video_id": vid, "channel_id": "UC1", "published_at": iso(BOUNDARY - dt.timedelta(days=days_before)),
           "duration_sec": dur, "view_count": views, "captured_at": CAPTURED, "is_live": 0, "live_evidence": ""}
    row.update(kw)
    return row


def population(n_split=6):
    split = [up(f"s{i}", -i, views=10**6) for i in range(n_split)]  # s0 이 boundary 정각
    old = [up(f"r{i}", 10 + i, views=100 * (i + 1)) for i in range(5)]           # shorts 5
    old += [up(f"L{i}", 30 + i, views=5000 + i, dur=3000) for i in range(2)]     # long 2 → 부족
    return split, old


def manifest_for(uploads, split_ids, rules=RULES, **kw):
    return ref.select_reference(uploads, split_ids, channel_id="UC1", rules=rules, **kw)


# ---------------------------------------------------------------- 선정

def test_split_videos_never_enter_reference_randomized():
    rng = random.Random(7)
    for trial in range(30):
        uploads = [up(f"v{i}", rng.randint(-200, 500), views=rng.randint(0, 10**6),
                      dur=rng.choice([30, 600, 4000])) for i in range(80)]
        split_ids = {u["video_id"] for u in uploads if u["published_at"] >= iso(BOUNDARY)}
        if not split_ids:
            continue
        # split 이 아닌 boundary 이후 영상도 섞는다 (split 밖 최근 업로드)
        split_ids = set(sorted(split_ids)[: max(1, len(split_ids) // 2)])
        m = manifest_for(uploads, split_ids, boundary=iso(BOUNDARY))
        chosen = {r["video_id"] for r in m["reference"]}
        assert not chosen & split_ids
        assert m["exclusions"]["in_split"] == len(split_ids)
        assert all(r["published_at"] < iso(BOUNDARY) for r in m["reference"])


def test_split_video_before_boundary_is_rejected():
    split, old = population()
    with pytest.raises(ValueError, match="boundary"):
        manifest_for(split + old, {"s0", "r0"}, boundary=iso(BOUNDARY))


def test_boundary_requires_all_split_ids_or_explicit_value():
    split, old = population()
    with pytest.raises(ValueError, match="boundary"):
        manifest_for(old + split[1:], {s["video_id"] for s in split})
    m = manifest_for(old + split[1:], {s["video_id"] for s in split}, boundary=iso(BOUNDARY))
    assert m["boundary_published_before"] == iso(BOUNDARY)


def test_empty_split_and_duplicate_uploads_rejected():
    split, old = population()
    with pytest.raises(ValueError):
        manifest_for(split + old, set())
    with pytest.raises(ValueError, match="중복"):
        manifest_for(split + old + [old[0]], {s["video_id"] for s in split})


def test_exclusion_rules_are_counted():
    split, old = population()
    extra = [
        up("x_window", 400),
        up("x_live", 20, is_live=1),
        up("x_premiere", 20, live_evidence='{"actualStartTime": "x"}'),
        up("x_upcoming", 20, live_broadcast_content="upcoming"),
        up("x_duration", 20, dur=0),
        up("x_capture", 20, captured_at=None),
        up("x_immature", 20, captured_at=iso(BOUNDARY - dt.timedelta(days=1))),
        up("x_views", 20, views=None),
        up("x_channel", 20, channel_id="UC_OTHER"),
        up("x_recent_nonsplit", -30),
    ]
    m = manifest_for(split + old + extra, {s["video_id"] for s in split})
    assert m["exclusions"] == {
        "channel_mismatch": 1, "in_split": 6, "not_before_boundary": 1, "outside_window": 1,
        "live_or_premiere": 2, "upcoming_or_live_now": 1, "duration_unknown": 1,
        "captured_at_unknown": 1, "not_matured": 1, "views_unavailable": 1,
    }
    assert {r["video_id"] for r in m["reference"]} == {o["video_id"] for o in old}
    assert m["reference_n"] == 7


def test_selection_ignores_view_values():
    split, old = population()
    ids = {s["video_id"] for s in split}
    a = manifest_for(split + old, ids)
    shuffled = copy.deepcopy(split + old)
    for u in shuffled:
        u["view_count"] = random.Random(u["video_id"]).randint(0, 10**7)
    b = manifest_for(shuffled, ids)
    assert [r["video_id"] for r in a["reference"]] == [r["video_id"] for r in b["reference"]]


# ---------------------------------------------------------------- 해시·동결

def test_manifest_hash_stable_under_input_order_and_changes_with_snapshot():
    split, old = population()
    ids = {s["video_id"] for s in split}
    a = manifest_for(split + old, ids)
    reordered = list(reversed(split + old))
    b = manifest_for(reordered, set(sorted(ids, reverse=True)))
    assert a == b and a["manifest_sha256"] == b["manifest_sha256"]
    # 직렬화·역직렬화(파일 저장) 후에도 같은 해시
    assert ref.manifest_sha256(json.loads(json.dumps(a, indent=2, sort_keys=True))) == a["manifest_sha256"]
    changed = copy.deepcopy(old)
    changed[0]["view_count"] += 1
    assert manifest_for(split + changed, ids)["manifest_sha256"] != a["manifest_sha256"]
    other_rules = dataclasses.replace(RULES, maturity_days=91)
    assert manifest_for(split + old, ids, rules=other_rules)["manifest_sha256"] != a["manifest_sha256"]


def test_known_hash_is_pinned_and_tamper_detected():
    split, old = population()
    m = manifest_for(split + old, {s["video_id"] for s in split})
    # 이 값이 바뀌면 manifest 형식·규칙·해시 방식이 바뀐 것이다 → 버전을 올리고 재동결
    assert m["manifest_sha256"] == "0de5c7eee92c1a10504915f204661b1369bc2aa4a2a11b236f7f614dbace7b88"
    assert m["split"]["ids_sha256"] == ref.ids_sha256([f"s{i}" for i in range(6)])
    # 필드 하나라도 바꾸면 검증 실패
    tampered = copy.deepcopy(m)
    tampered["reference"][0]["view_count"] = 1
    with pytest.raises(ValueError, match="해시"):
        ref.verify_manifest(tampered)
    tampered = copy.deepcopy(m)
    tampered["rules"]["rules_status"] = "approved"
    with pytest.raises(ValueError, match="해시"):
        ref.verify_manifest(tampered)
    ref.verify_manifest(m)


# ---------------------------------------------------------------- 최소 표본

def test_min_size_per_axis_marks_insufficient_strata():
    split, old = population()
    m = manifest_for(split + old, {s["video_id"] for s in split})
    assert m["strata"]["shorts"]["n"] == 5 and m["strata"]["shorts"]["status"] == "sufficient"
    assert m["strata"]["long"]["n"] == 2 and m["strata"]["long"]["status"] == "insufficient"
    assert m["strata"]["standard"] == {"n": 0, "min_required": 3, "status": "insufficient",
                                       "median_view_count": None, "by_quarter": {}}
    assert sum(m["strata"]["shorts"]["by_quarter"].values()) == 5
    target = {"video_id": "s1", "duration_sec": 3000, "view_count": 9000, "age_days": 120}
    out = ref.canonical_view_multiple(target, m)
    assert out["view_multiple"] is None and out["status"] == "reference_insufficient"
    assert out["reference_n"] == 2


def test_summary_has_counts_only():
    split, old = population()
    s = ref.manifest_summary(manifest_for(split + old, {x["video_id"] for x in split}))
    text = json.dumps(s)
    assert "r0" not in text and "s0" not in text and "view_count" not in text


# ---------------------------------------------------------------- canonical 배수

def test_canonical_multiple_against_frozen_reference():
    split, old = population()
    m = manifest_for(split + old, {s["video_id"] for s in split})
    # shorts reference views 100..500 → median 300
    out = ref.canonical_view_multiple({"video_id": "s2", "duration_sec": 45, "view_count": 900, "age_days": 95.0}, m)
    assert out["status"] == "available"
    assert out["view_multiple"] == pytest.approx(3.0)
    assert out["reference_median_views"] == 300 and out["reference_n"] == 5
    assert out["canonical"] is True and out["definition"] == ref.CANONICAL_DEFINITION
    assert out["reference_manifest_sha256"] == m["manifest_sha256"]
    assert out["reference_rules_status"] == "proposal" and out["final_eligible"] is False
    # age_days 가 없으면 captured_at - published_at
    out = ref.canonical_view_multiple({"video_id": "s3", "duration_sec": 45, "view_count": 150,
                                       "published_at": "2026-03-01T00:00:00Z", "captured_at": CAPTURED}, m)
    assert out["view_multiple"] == pytest.approx(0.5)


@pytest.mark.parametrize("patch,status", [
    ({"age_days": 10}, "target_not_matured"),
    ({"is_live": 1}, "target_live_or_premiere"),
    ({"live_evidence": "{}x"}, "target_live_or_premiere"),
    ({"view_count": None}, "target_views_missing"),
    ({"age_days": None}, "target_age_unknown"),
    ({"duration_sec": None, "length_axis": None}, "target_axis_unknown"),
    ({"video_id": "r0"}, "target_in_reference"),
])
def test_canonical_missing_statuses(patch, status):
    split, old = population()
    m = manifest_for(split + old, {s["video_id"] for s in split})
    video = {"video_id": "s1", "duration_sec": 45, "view_count": 900, "age_days": 120, **patch}
    out = ref.canonical_view_multiple(video, m)
    assert out["status"] == status and out["view_multiple"] is None


def test_canonical_zero_median_and_approved_rules():
    split, old = population()
    zero = [dict(o, view_count=0) for o in old]
    m = manifest_for(split + zero, {s["video_id"] for s in split})
    out = ref.canonical_view_multiple({"video_id": "s1", "duration_sec": 45, "view_count": 9, "age_days": 120}, m)
    assert out["status"] == "reference_median_nonpositive" and out["view_multiple"] is None
    approved = dataclasses.replace(RULES, rules_status="approved")
    m = manifest_for(split + old, {s["video_id"] for s in split}, rules=approved)
    out = ref.canonical_view_multiple({"video_id": "s1", "duration_sec": 45, "view_count": 300, "age_days": 120}, m)
    assert out["final_eligible"] is True and out["view_multiple"] == pytest.approx(1.0)


def test_upload_from_api_item_keeps_hidden_views_missing():
    item = {"id": "abc", "snippet": {"channelId": "UC1", "publishedAt": "2025-01-01T00:00:00Z",
                                      "liveBroadcastContent": "none"},
            "contentDetails": {"duration": "PT1M5S"}, "statistics": {},
            "liveStreamingDetails": {"actualStartTime": "2025-01-01T00:00:00Z"}}
    row = ref.upload_from_api_item(item, CAPTURED)
    assert row["view_count"] is None and row["duration_sec"] == 65 and row["live_evidence"]
    assert "title" not in row and "description" not in row


# ---------------------------------------------------------------- Finding opt-in

def dev_manifest(videos):
    """engine 합성 영상 v0..v9 를 split 으로 두고, split 밖 과거 업로드로 reference 를 만든다."""
    split_ids = {v["video_id"] for v in videos}
    old = [up(f"r{i}", 10 + i, views=100) for i in range(5)]
    return manifest_for(old, split_ids, boundary=iso(BOUNDARY))


def test_finding_default_is_unchanged_and_opt_in_uses_canonical():
    videos, labels = engine_data()
    for i, v in enumerate(videos):
        v.update(duration_sec=45, age_days=120, view_count=100 * (i + 1))
    legacy = build_findings(copy.deepcopy(videos), labels, frozen_registry())
    assert legacy == build_findings(copy.deepcopy(videos), labels, frozen_registry(), reference_manifest=None)
    rp = legacy["input_contract"]["relative_performance"]
    assert rp["canonical"] is False and rp["canonical_status"] == "provisional_legacy"

    m = dev_manifest(videos)
    before = copy.deepcopy(videos)
    out = build_findings(videos, labels, frozen_registry(), reference_manifest=m)
    assert videos == before  # 입력을 바꾸지 않는다
    rp = out["input_contract"]["relative_performance"]
    assert rp["canonical"] is True and rp["reference_manifest_sha256"] == m["manifest_sha256"]
    assert rp["final_eligible"] is False and rp["status_counts"] == {"available": 10}
    assert rp["per_video"]["v3"]["reference_median_views"] == 100
    # canonical 배수 = view_count / 100 = i+1 → 공급된 view_multiple 과 다르다
    leg = out["calculations"]["feature_to_performance"][0]
    assert leg["effect"]["estimate"] == pytest.approx(2.5 - 6.5)
    assert leg["effect"]["estimate"] != legacy["calculations"]["feature_to_performance"][0]["effect"]["estimate"]


def test_finding_opt_in_rejects_tampered_manifest_and_reports_missing():
    videos, labels = engine_data()
    for v in videos:
        v.update(duration_sec=45, age_days=120, view_count=100)
    videos[0]["age_days"] = 5
    m = dev_manifest(videos)
    out = build_findings(videos, labels, frozen_registry(), reference_manifest=m)
    rp = out["input_contract"]["relative_performance"]
    assert rp["status_counts"] == {"available": 9, "target_not_matured": 1}
    assert out["calculations"]["feature_to_performance"][0]["missingness"]["missing_metric_n"] == 1
    bad = copy.deepcopy(m)
    bad["reference"][0]["view_count"] = 1
    with pytest.raises(ValueError, match="해시"):
        build_findings(videos, labels, frozen_registry(), reference_manifest=bad)


def test_runner_opt_in_records_reference_provenance(case):  # noqa: F811
    evidence = json.loads(case["ev"].read_text(encoding="utf-8"))
    dev = [v for v in evidence["videos"] if v["video_id"].startswith("d")]
    for v in dev:
        v["age_days"] = 120
    case["ev"].write_text(json.dumps(evidence), encoding="utf-8")
    with case["split"].open(encoding="utf-8", newline="") as stream:
        split_ids = {r["video_id"] for r in csv.DictReader(stream)}
    m = manifest_for([up(f"r{i}", 10 + i, views=50) for i in range(4)], split_ids, boundary=iso(BOUNDARY))
    path = case["root"].parent / "reference-manifest.json"
    path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    assert runner.main(case["args"][1:] + ["--reference-manifest", str(path)]) == 0
    manifest = json.loads((case["out"] / "manifest.json").read_text(encoding="utf-8"))
    findings = json.loads((case["out"] / "findings.json").read_text(encoding="utf-8"))
    assert manifest["relative_performance"]["mode"] == "canonical_reference"
    assert manifest["relative_performance"]["reference_manifest_sha256"] == m["manifest_sha256"]
    assert findings["input_contract"]["relative_performance"]["status_counts"] == {"available": 10}

    second = case["root"] / "legacy"
    runner.run(registry=case["reg"], labels=case["labels"], split=case["split"], evidence=case["ev"], out=second)
    legacy_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert "relative_performance" not in legacy_manifest


# ---------------------------------------------------------------- 스크립트

def test_script_build_dry_run_writes_nothing_and_write_refuses_overwrite(tmp_path, capsys):
    import build_reference_population as script

    split, old = population()
    uploads = tmp_path / "uploads.json"
    uploads.write_text(json.dumps({"schema": ref.UPLOADS_SCHEMA, "channel_id": "UC1", "videos": split + old}),
                       encoding="utf-8")
    split_csv = tmp_path / "split.csv"
    with split_csv.open("w", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(["video_id", "split"])
        w.writerows((s["video_id"], "development") for s in split)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert script.main(["build", "--uploads-json", str(uploads), "--split", str(split_csv)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    out = tmp_path / "manifest.json"
    assert script.main(["build", "--uploads-json", str(uploads), "--split", str(split_csv), "--write", str(out)]) == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    ref.verify_manifest(saved)
    assert saved["rules"] == dataclasses.asdict(ref.DEFAULT_RULES)
    first = out.read_bytes()
    assert script.main(["build", "--uploads-json", str(uploads), "--split", str(split_csv), "--write", str(out)]) == 2
    assert out.read_bytes() == first


def test_script_fetch_without_confirmation_never_calls_api(tmp_path, monkeypatch):
    import build_reference_population as script
    from app.clients import youtube

    def forbidden(*a, **k):
        raise AssertionError("API called")

    monkeypatch.setattr(youtube.YouTubeClient, "_get", forbidden)
    out = tmp_path / "uploads.json"
    assert script.main(["fetch", "--channel", "UC1", "--max-uploads", "120", "--out", str(out)]) == 0
    assert not out.exists()
    assert script.estimate_units(120) == 1 + 3 + 3
