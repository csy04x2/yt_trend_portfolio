"""Reaction Phase 3 판정기 — 프롬프트 등록, 출력 검증 규칙, 저장.

API 키도 anthropic 패키지도 없이 돈다. 댓글은 전부 이 파일에서 지어낸 합성
문장이다 — 실제 수집 댓글 원문을 테스트에 넣지 않는다.
"""

import json
import pathlib
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients import claude  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.pipeline import label_reactions as lr  # noqa: E402
from app.prompts import registry as R  # noqa: E402

# 합성 댓글. 실제 댓글이 아니다.
SYN = {
    "c1": "합성댓글 설명이 정리가 잘 되어 있어서 이해가 쉬웠다",
    "c2": "합성댓글 12:34 여기 배경 소리 뭐지",
    "c3": "합성댓글 ㅎㅎ",
}
MAPPING = {"1": "c1", "2": "c2", "3": "c3"}


def _row(idx, reactions, targets, ts=(), flag=False, reason=None, why="합성 근거"):
    return {"idx": idx, "reactions": list(reactions), "targets": list(targets),
            "explicit_timestamps": list(ts), "review_flag": flag,
            "review_reason": reason, "rationale": why}


def _good():
    return {"results": [
        _row(1, ["R7", "R1"], ["T2"]),
        _row(2, ["R6"], ["UNKNOWN"], ts=["12:34"]),
        _row(3, [], []),
    ]}


def _fails(result, *expect):
    try:
        lr.validate_reactions(result, MAPPING, SYN)
    except lr.ValidationError as e:
        for x in expect:
            assert x in str(e), f"'{x}' 를 못 잡았다: {e}"
        return str(e)
    raise AssertionError("규칙 위반이 통과했다")


# --------------------------------------------------------------------------
# 프롬프트 레지스트리
# --------------------------------------------------------------------------

def test_prompt_registered_with_version_and_history():
    p = R.get(lr.PROMPT_NAME)
    assert p.version == "reaction-v1"
    assert "reaction-v1" in p.history
    assert p.schema is not None, "출력 스키마가 읽히지 않는다"
    assert "comment_reaction" in R.all_prompts()
    assert p.system in p.full_text   # 오프라인과 API 가 같은 문자열


def test_prompt_carries_every_code_and_rule_from_the_docs():
    s = R.get(lr.PROMPT_NAME).system
    for code, name in lr.REACTION_NAMES.items():
        assert f"| {code} | {name} |" in s, f"{code} {name} 정의가 없다"
    for code in ("T1", "T2", "T3", "T4", "T5"):
        assert f"| {code} | {lr.TARGET_NAMES[code]} |" in s
    for must in ("H1", "H2", "H3", "H4", "substantive cognitive contribution",
                 "R8(요청·제안)", "UNKNOWN", "추정하지 않는다",
                 "APPLICATION_ERROR", "DEFINITION_BOUNDARY", "STRUCTURE_CANDIDATE"):
        assert must in s, f"'{must}' 가 프롬프트에 없다"
    assert "R11" not in s and "T6" not in s


def test_schema_rejects_unknown_code_and_bad_reason():
    p = R.get(lr.PROMPT_NAME)
    assert R.check(p, _good()) == []
    bad = {"results": [_row(1, ["R11"], ["T6"], reason="WHATEVER")]}
    msgs = " / ".join(R.check(p, bad))
    for x in ("R11", "T6", "WHATEVER"):
        assert x in msgs, msgs


def test_check_against_db_knows_reaction_table():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE comment_reactions (comment_id TEXT, prompt_version TEXT, model TEXT)")
    c.execute("INSERT INTO comment_reactions VALUES ('c1','reaction-v1','m')")
    assert R.check_against_db(c) == []
    c.execute("INSERT INTO comment_reactions VALUES ('c2','reaction-v9','m')")
    assert any("comment_reactions" in m and "reaction-v9" in m for m in R.check_against_db(c))


# --------------------------------------------------------------------------
# 출력 검증 — 코드
# --------------------------------------------------------------------------

def test_valid_batch_passes_and_normalizes_order():
    rows = lr.validate_reactions(_good(), MAPPING, SYN)
    by = {r["comment_id"]: r for r in rows}
    assert by["c1"]["reactions"] == ["R1", "R7"]
    assert by["c3"]["reactions"] == [] and by["c3"]["targets"] == []


def test_rejects_unknown_reaction_and_target_codes():
    r = _good()
    r["results"][0]["reactions"] = ["R11"]
    r["results"][1]["targets"] = ["T6"]
    _fails(r, "R11", "T6")


def test_none_string_is_not_reaction_none():
    r = _good()
    r["results"][2]["reactions"] = ["None"]
    _fails(r, "[] 로 쓴다")
    r["results"][2]["reactions"] = None
    _fails(r, "배열")


def test_duplicate_code_rejected():
    r = _good()
    r["results"][0]["reactions"] = ["R1", "R1"]
    _fails(r, "두 번")


# --------------------------------------------------------------------------
# None 과 UNKNOWN
# --------------------------------------------------------------------------

def test_none_and_unknown_are_kept_distinct():
    r = _good()
    r["results"][2] = _row(3, ["UNKNOWN"], ["UNKNOWN"])
    rows = {x["comment_id"]: x for x in lr.validate_reactions(r, MAPPING, SYN)}
    assert rows["c3"]["reactions"] == ["UNKNOWN"]
    assert rows["c3"]["reactions"] != []


def test_unknown_cannot_mix_with_codes():
    r = _good()
    r["results"][0]["reactions"] = ["R1", "UNKNOWN"]
    r["results"][1]["targets"] = ["T2", "UNKNOWN"]
    msg = _fails(r, "UNKNOWN 은 다른 코드와 섞을 수 없다")
    assert "reactions" in msg and "targets" in msg


def test_reaction_requires_target_but_none_does_not():
    r = _good()
    r["results"][0]["targets"] = []
    _fails(r, "targets 가 비었다")
    r = _good()
    r["results"][2] = _row(3, ["UNKNOWN"], [])
    _fails(r, "targets 가 비었다")
    r = _good()
    r["results"][2] = _row(3, [], ["T2"])    # None 이어도 대상이 분명하면 붙일 수 있다
    lr.validate_reactions(r, MAPPING, SYN)


# --------------------------------------------------------------------------
# timestamp — 원문에 없는 값은 받지 않는다 (H2)
# --------------------------------------------------------------------------

def test_invented_timestamp_rejected():
    r = _good()
    r["results"][0]["explicit_timestamps"] = ["03:10"]   # c1 원문에 없다
    _fails(r, "원문에 없다")


def test_literal_timestamp_filled_when_model_missed_it():
    r = _good()
    r["results"][1]["explicit_timestamps"] = []
    rows = {x["comment_id"]: x for x in lr.validate_reactions(r, MAPPING, SYN)}
    assert rows["c2"]["explicit_timestamps"] == ["12:34"]
    assert rows["c1"]["explicit_timestamps"] == []   # 원문에 없으면 아무것도 채우지 않는다


def test_literal_timestamps_extractor():
    assert lr.literal_timestamps("1:02 그리고 1:02, 1:99 와 1:02:03") == ["1:02", "1:02:03"]
    assert lr.literal_timestamps("숫자 없음") == []


# --------------------------------------------------------------------------
# review_flag · rationale · 번호
# --------------------------------------------------------------------------

def test_review_reason_rules():
    r = _good()
    r["results"][0]["review_flag"] = True
    _fails(r, "review_reason")
    r = _good()
    r["results"][0]["review_reason"] = "DEFINITION_BOUNDARY"
    _fails(r, "null 이어야")
    r = _good()
    r["results"][0].update(review_flag=True, review_reason="STRUCTURE_CANDIDATE")
    lr.validate_reactions(r, MAPPING, SYN)


def test_missing_fields_and_empty_rationale_rejected():
    r = _good()
    del r["results"][0]["explicit_timestamps"]
    r["results"][1]["rationale"] = "  "
    _fails(r, "explicit_timestamps", "rationale 이 비었다")


def test_missing_and_extra_idx_rejected():
    r = _good()
    r["results"] = r["results"][:2] + [_row(9, [], [])]
    _fails(r, "빠진 번호", "입력에 없는 번호 9")


# --------------------------------------------------------------------------
# 저장 · 입력 · 경로
# --------------------------------------------------------------------------

def _db(tmp: pathlib.Path, eligible_col: bool = False):
    conn = connect(tmp / "t.db")
    conn.execute("INSERT INTO channels VALUES ('ch','u',NULL,'합성채널','pl',NULL,'2026-01-01',NULL)")
    conn.execute("""INSERT INTO videos (video_id, channel_id, title, duration_sec, published_at,
                    first_seen_at) VALUES ('v1','ch','합성 영상',600,'2026-01-01','2026-01-01')""")
    for i, (cid, text) in enumerate(SYN.items()):
        conn.execute("""INSERT INTO comments (comment_id, video_id, text, published_at, fetched_at)
                        VALUES (?,?,?,?,?)""", (cid, "v1", text, f"2026-01-0{i + 1}", "2026-01-09"))
    if eligible_col:
        # 수집기 브랜치가 합쳐지면 스키마에 이미 있다. 없는 옛 스키마일 때만 추가한다
        cols = {r[1] for r in conn.execute("PRAGMA table_info(comments)")}
        if "analysis_eligible" not in cols:
            conn.execute("ALTER TABLE comments ADD COLUMN analysis_eligible INTEGER")
        conn.execute("UPDATE comments SET analysis_eligible = 0 WHERE comment_id='c3'")
    return conn


def test_table_created_and_existing_tables_untouched():
    with tempfile.TemporaryDirectory() as t:
        conn = _db(pathlib.Path(t))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"comment_reactions", "comment_labels", "comment_screens"} <= tables
        cols = [r[1] for r in conn.execute("PRAGMA table_info(comment_reactions)")]
        for c in ("comment_id", "prompt_version", "model", "reactions_json", "targets_json",
                  "timestamps_json", "review_flag", "review_reason", "rationale", "labeled_at"):
            assert c in cols
        conn.close()


def test_save_roundtrip_and_pending_skips_labeled():
    with tempfile.TemporaryDirectory() as t:
        conn = _db(pathlib.Path(t))
        assert len(lr.pending(conn, "reaction-v1", "m")) == 3
        rows = lr.validate_reactions(_good(), MAPPING, SYN)
        assert lr.save_reactions(conn, rows, "reaction-v1", "m") == 3
        assert lr.pending(conn, "reaction-v1", "m") == []
        assert len(lr.pending(conn, "reaction-v1", "다른모델")) == 3
        data = lr.labels_from_db(conn, "reaction-v1", "m")
        by = {x["comment_id"]: x for x in data["labels"]}
        assert by["c3"]["reactions"] == [] and by["c2"]["explicit_timestamps"] == ["12:34"]
        assert data["status"] == "검증 전 AI 판정"
        assert "text" not in json.dumps(data["labels"][0])
        conn.close()


def test_pending_respects_analysis_eligible_when_column_exists():
    with tempfile.TemporaryDirectory() as t:
        conn = _db(pathlib.Path(t), eligible_col=True)
        ids = {r["comment_id"] for r in lr.pending(conn, "reaction-v1", "m")}
        assert ids == {"c1", "c2"}   # c3 은 제외 확정. NULL 은 보낸다
        conn.close()


def test_load_raw_comments_skips_ineligible():
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t) / "raw.json"
        p.write_text(json.dumps({"comments": [
            {"comment_id": "c1", "text": SYN["c1"], "analysis_eligible": True},
            {"comment_id": "c2", "text": SYN["c2"], "analysis_eligible": False,
             "exclusion_reason": "own_channel"},
            {"comment_id": "c3", "text": SYN["c3"]},
        ]}, ensure_ascii=False), encoding="utf-8")
        rows, skipped = lr.load_raw_comments(p)
        assert [r["comment_id"] for r in rows] == ["c1", "c3"] and skipped == 1


def test_private_path_guard():
    with tempfile.TemporaryDirectory() as t:
        base = pathlib.Path(t) / "data"
        lr.ensure_private_path(base / "x" / "y.html", base)
        for bad in (pathlib.Path(t) / "y.html", base / ".." / "y.html"):
            try:
                lr.ensure_private_path(bad, base)
            except lr.UnsafePath:
                continue
            raise AssertionError(f"{bad} 가 통과했다")
    # 기본 base 는 gitignored 인 backend/data 다
    assert lr.DATA_DIR == ROOT / "data"


def test_export_writes_only_inside_base():
    with tempfile.TemporaryDirectory() as t:
        base = pathlib.Path(t) / "data"
        comments = [{"comment_id": k, "video_id": "v1", "video_title": "합성 영상",
                     "channel_name": "합성채널", "text": v} for k, v in SYN.items()]
        path = lr.export(comments, "b1", base / "batches", base=base)
        meta = json.loads((base / "batches" / "b1.map.json").read_text(encoding="utf-8"))
        assert meta["prompt_version"] == "reaction-v1" and meta["texts"]["c2"] == SYN["c2"]
        body = path.read_text(encoding="utf-8")
        assert "합성채널" in body and "좋아요" not in body.split("# 이 묶음")[1]
        try:
            lr.export(comments, "b2", pathlib.Path(t) / "outside", base=base)
        except lr.UnsafePath:
            return
        raise AssertionError("base 밖 경로에 원문 묶음을 썼다")


class FakeClient:
    """고정 응답을 돌려주는 가짜. 네트워크를 쓰지 않는다."""

    def __init__(self, responses):
        self.model = "fake-model"
        self.usage = claude.Usage()
        self.responses = list(responses)

    def judge(self, prompt, body):
        assert prompt.name == lr.PROMPT_NAME
        return self.responses.pop(0)


def test_run_saves_valid_batches_and_skips_invalid():
    with tempfile.TemporaryDirectory() as t:
        conn = _db(pathlib.Path(t))
        rows = lr.pending(conn, "reaction-v1", "fake-model")
        good = {"results": [_row(1, ["R1"], ["T1"]), _row(2, [], [], ts=["12:34"])]}
        invented = {"results": [_row(1, ["R2"], ["T3"], ts=["00:01"])]}
        p = lr.run(FakeClient([good, invented]), rows, conn=conn, size=2, log=lambda m: None)
        assert p.done == 1 and len(p.failed) == 1 and p.labeled == 2
        saved = {r[0] for r in conn.execute("SELECT comment_id FROM comment_reactions")}
        assert saved == {"c1", "c2"}
        assert lr.pending(conn, "reaction-v1", "fake-model")[0]["comment_id"] == "c3"
        conn.close()


def test_run_to_label_file():
    with tempfile.TemporaryDirectory() as t:
        base = pathlib.Path(t) / "data"
        rows = [{"comment_id": k, "video_id": "v1", "video_title": "합성 영상",
                 "channel_name": "합성채널", "text": v} for k, v in SYN.items()]
        resp = {"results": [_row(1, ["R1"], ["T2"]), _row(2, ["R6"], ["UNKNOWN"]),
                            _row(3, [], [])]}
        out = base / "labels" / "ai.json"
        p = lr.run(FakeClient([resp]), rows, labels_out=out, base=base, log=lambda m: None)
        assert p.labeled == 3 and not p.failed
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["labeler"] == "ai:fake-model" and len(data["labels"]) == 3
        assert data["status"] == "검증 전 AI 판정"
        for v in SYN.values():
            assert v not in json.dumps(data, ensure_ascii=False), "라벨 파일에 원문이 들어갔다"
        # 다른 (버전, 모델) 의 파일에 섞어 넣지 않는다
        try:
            lr.merge_into_label_file(out, [], prompt_version="reaction-v1",
                                     model="다른모델", base=base)
        except ValueError:
            pass
        else:
            raise AssertionError("다른 모델의 라벨 파일에 섞어 넣었다")
        # base 밖 라벨 파일은 거부
        try:
            lr.run(FakeClient([resp]), rows, labels_out=pathlib.Path(t) / "ai.json",
                   base=base, log=lambda m: None)
        except lr.UnsafePath:
            return
        raise AssertionError("base 밖 라벨 파일에 썼다")


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"  ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)
