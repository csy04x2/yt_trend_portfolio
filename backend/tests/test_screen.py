"""4단계 Claude 선별 — 검증, 저장 자리, 규칙 행과의 공존.

버리는 판정이라 조용히 틀리면 댓글이 영원히 사라진다. 그래서 여기서
보는 것은 "무엇을 잡아내는가"와 "무엇을 건드리지 않는가" 둘이다.
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import connect  # noqa: E402
from app.pipeline import offline_llm  # noqa: E402
from app.pipeline import screen_comments as sc  # noqa: E402

MAP = {"1": "c1", "2": "c2", "3": "c3"}


def _result(rows):
    return {"batch": "b_001", "prompt_version": "screen-v1", "results": rows}


def _all_keep():
    return _result([{"idx": i, "verdict": "keep"} for i in (1, 2, 3)])


# --------------------------------------------------------------------------
# 검증 — 틀린 것은 전부 모아 한 번에 알린다
# --------------------------------------------------------------------------

def test_validate_ok():
    rows = sc.validate_screens(_all_keep(), MAP)
    assert [r["comment_id"] for r in rows] == ["c1", "c2", "c3"]
    assert all(r["verdict"] == "keep" for r in rows)
    assert all(r["reason"] is None for r in rows)


def test_validate_catches_missing_idx():
    """빠뜨린 댓글은 판정이 없는 것이지 통과한 것이 아니다."""
    try:
        sc.validate_screens(_result([{"idx": 1, "verdict": "keep"}]), MAP)
    except sc.ValidationError as e:
        assert "빠진 번호" in str(e), e
        return
    raise AssertionError("빠진 번호를 통과시켰다")


def test_validate_catches_unknown_idx():
    try:
        sc.validate_screens(_result([{"idx": i, "verdict": "keep"}
                                     for i in (1, 2, 3, 9)]), MAP)
    except sc.ValidationError as e:
        assert "없는 번호 9" in str(e), e
        return
    raise AssertionError("입력에 없는 번호를 통과시켰다")


def test_validate_catches_duplicate_idx():
    """같은 번호가 두 번 오면 뒤엣것이 앞엣것을 조용히 덮는다."""
    try:
        sc.validate_screens(_result([
            {"idx": 1, "verdict": "keep"}, {"idx": 1, "verdict": "drop"},
            {"idx": 2, "verdict": "keep"}, {"idx": 3, "verdict": "keep"}]), MAP)
    except sc.ValidationError as e:
        assert "중복" in str(e), e
        return
    raise AssertionError("중복된 번호를 통과시켰다")


def test_validate_catches_bad_verdict():
    try:
        sc.validate_screens(_result([
            {"idx": 1, "verdict": "아마도"}, {"idx": 2, "verdict": "keep"},
            {"idx": 3, "verdict": "keep"}]), MAP)
    except sc.ValidationError as e:
        assert "아마도" in str(e), e
        return
    raise AssertionError("허용값 아닌 verdict 를 통과시켰다")


def test_validate_collects_every_problem_at_once():
    """하나씩 알려주면 프롬프트를 고칠 때마다 한 가지씩만 알게 된다."""
    try:
        sc.validate_screens(_result([
            {"idx": 9, "verdict": "keep"},
            {"idx": 1, "verdict": "나중에"},
            {"idx": 2, "verdict": "keep"},
            {"idx": 2, "verdict": "keep"}]), MAP)
    except sc.ValidationError as e:
        msg = str(e)
        for expect in ("없는 번호 9", "나중에", "중복", "빠진 번호"):
            assert expect in msg, f"{expect} 를 못 잡았다: {msg}"
        return
    raise AssertionError("전부 통과했다")


def test_validate_rejects_non_list_results():
    try:
        sc.validate_screens({"results": {"1": "keep"}}, MAP)
    except sc.ValidationError:
        return
    raise AssertionError("results 가 배열이 아닌데 통과했다")


def test_validate_keeps_the_reason():
    """왜 버렸는지가 없으면 나중에 오탐을 셀 수 없다."""
    rows = sc.validate_screens(_result([
        {"idx": 1, "verdict": "drop", "reason": "다른 채널 구독 유도 + 링크"},
        {"idx": 2, "verdict": "keep", "reason": "   "},
        {"idx": 3, "verdict": "keep"}]), MAP)
    assert rows[0]["reason"] == "다른 채널 구독 유도 + 링크"
    assert rows[1]["reason"] is None, "공백뿐인 이유는 이유가 아니다"


# --------------------------------------------------------------------------
# 오프라인 경로 — 라벨링과 같은 본문을 보낸다
# --------------------------------------------------------------------------

COMMENTS = [
    {"comment_id": "c1", "video_id": "v1", "text": "ㅋㅋㅋ", "like_count": 3},
    {"comment_id": "c2", "video_id": "v1", "text": "앞\n뒤", "like_count": 0},
]


def test_export_sends_the_same_body_as_the_label_path():
    """본문이 갈라지면 오프라인에서 잰 정확도가 API 를 보장하지 못한다."""
    out = pathlib.Path(tempfile.mkdtemp())
    path = sc.export(COMMENTS, "영상 제목", "b_001", out)
    text = path.read_text(encoding="utf-8")
    body, mapping = offline_llm.batch_body(COMMENTS, "영상 제목", "b_001")
    assert body in text, "묶음 본문이 offline_llm 과 다르다"
    assert mapping == {"1": "c1", "2": "c2"}


def test_export_carries_the_whole_screen_prompt():
    out = pathlib.Path(tempfile.mkdtemp())
    text = sc.export(COMMENTS, "영상 제목", "b_001", out).read_text(encoding="utf-8")
    assert "- 버전: screen-v1" in text, "헤더(버전)가 빠졌다"
    assert "애매하면 `keep`" in text, "프롬프트 전문이 빠졌다"
    data = json.loads((out / "b_001.map.json").read_text(encoding="utf-8"))
    assert data["map"]["2"] == "c2"


# --------------------------------------------------------------------------
# 저장 — 규칙 행 옆에 앉는다. 덮어쓰지 않는다
# --------------------------------------------------------------------------

def _db():
    """영상 1편·댓글 3건에 규칙 판정이 붙어 있는 임시 DB."""
    path = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    conn = connect(path)
    conn.execute("""INSERT INTO channels (channel_id, input_url, title,
                        uploads_playlist, first_analyzed_at)
                    VALUES ('ch1','u','채널','UU','2026-01-01')""")
    conn.execute("""INSERT INTO videos (video_id, channel_id, title,
                        duration_sec, published_at, length_axis, first_seen_at)
                    VALUES ('v1','ch1','영상 제목',60,'2026-01-01','shorts','2026-01-01')""")
    verdicts = {"c1": "keep", "c2": "suspect_repeat", "c3": "promo"}
    for cid, verdict in verdicts.items():
        conn.execute("""INSERT INTO comments (comment_id, video_id, text,
                            published_at, like_count, fetched_at)
                        VALUES (?, 'v1', ?, '2026-01-01', 0, '2026-01-01')""",
                     (cid, f"{cid} 원문"))
        conn.execute("""INSERT INTO comment_screens (comment_id, prompt_version,
                            model, rule_flags_json, verdict, screened_at)
                        VALUES (?, 'rules-v1', 'rule', '[]', ?, '2026-01-01')""",
                     (cid, verdict))
    return conn


def test_save_screens_sits_next_to_the_rule_row():
    """규칙이 통과시킨 것을 모델이 버렸다는 사실 자체가 이 단계의 산출물이다."""
    conn = _db()
    n = sc.save_screens(conn, [{"comment_id": "c1", "idx": 1, "verdict": "drop",
                                "reason": "홍보 유인"}], "screen-v1", "m1")
    assert n == 1
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM comment_screens WHERE comment_id='c1' ORDER BY model")]
    assert len(rows) == 2, "규칙 행을 덮어썼다"
    rule = [r for r in rows if r["model"] == "rule"][0]
    mine = [r for r in rows if r["model"] == "m1"][0]
    assert rule["verdict"] == "keep" and rule["rule_flags_json"] == "[]"
    assert mine["verdict"] == "drop" and mine["reason"] == "홍보 유인"


def test_reason_has_its_own_column():
    """rule_flags_json 은 규칙 표시의 자리라 문장을 넣으면 그 열을 읽는 쪽이 틀린다."""
    conn = _db()
    sc.save_screens(conn, [{"comment_id": "c1", "idx": 1, "verdict": "drop",
                            "reason": "도박 사이트 유인"}], "screen-v1", "m1")
    row = conn.execute("SELECT rule_flags_json, reason FROM comment_screens "
                       "WHERE comment_id='c1' AND model='m1'").fetchone()
    assert row["rule_flags_json"] is None
    assert row["reason"] == "도박 사이트 유인"


def test_rule_rows_leave_reason_null():
    conn = _db()
    rows = conn.execute("SELECT reason FROM comment_screens WHERE model='rule'")
    assert all(r["reason"] is None for r in rows)


def test_save_screens_upserts_the_same_key():
    conn = _db()
    for verdict in ("keep", "drop"):
        sc.save_screens(conn, [{"comment_id": "c1", "idx": 1, "verdict": verdict,
                                "reason": None}], "screen-v1", "m1")
    n = conn.execute("SELECT COUNT(*) FROM comment_screens "
                     "WHERE comment_id='c1' AND model='m1'").fetchone()[0]
    assert n == 1
    assert conn.execute("SELECT verdict FROM comment_screens WHERE model='m1'"
                        ).fetchone()["verdict"] == "drop"


# --------------------------------------------------------------------------
# 대상 고르기
# --------------------------------------------------------------------------

def test_pending_sends_only_what_the_rule_left_open():
    """규칙이 확정한 promo 를 다시 물으면 돈만 나간다."""
    conn = _db()
    got = {r["comment_id"] for r in sc.pending(conn, "screen-v1", "m1")}
    assert got == {"c1", "c2"}, got


def test_pending_skips_what_this_model_already_judged():
    conn = _db()
    sc.save_screens(conn, [{"comment_id": "c1", "idx": 1, "verdict": "keep",
                            "reason": None}], "screen-v1", "m1")
    assert {r["comment_id"] for r in sc.pending(conn, "screen-v1", "m1")} == {"c2"}
    # 모델이 다르면 다시 대상이다 — 두 모델을 나란히 놓고 비교하려고 키에 모델이 있다
    assert len(sc.pending(conn, "screen-v1", "m2")) == 2


def test_pending_does_not_count_its_own_rows_as_rule_verdicts():
    """모델 행을 규칙 행으로 세면 같은 댓글이 여러 번 대상에 오른다."""
    conn = _db()
    sc.save_screens(conn, [{"comment_id": "c1", "idx": 1, "verdict": "keep",
                            "reason": None}], "screen-v1", "m1")
    rows = sc.pending(conn, "screen-v1", "m2")
    assert len(rows) == len({r["comment_id"] for r in rows}), rows


def test_chunk_does_not_mix_videos():
    """묶음 본문이 영상 제목을 맥락으로 준다 — 섞이면 제목이 틀린다."""
    rows = [{"video_id": "v1"}, {"video_id": "v2"}, {"video_id": "v1"}]
    groups = sc.chunk(rows, 10)
    assert len(groups) == 2
    assert all(len({r["video_id"] for r in g}) == 1 for g in groups)


def test_estimate_counts_batches_per_video():
    rows = [{"video_id": "v1", "text": "x"}] * 3 + [{"video_id": "v2", "text": "y"}]
    est = sc.estimate(rows, 2)
    assert est["comments"] == 4
    assert est["batches"] == 3, est          # v1 은 2묶음, v2 는 1묶음


# --------------------------------------------------------------------------
# 전체 경로 — 실패는 묶음 단위로 격리한다
# --------------------------------------------------------------------------

class _Usage:
    def describe(self, model):
        return f"호출 0회 (가짜 client, model={model})"


class FakeClient:
    def __init__(self, replies):
        self.model = "fake-model"
        self.replies = list(replies)
        self.usage = _Usage()

    def judge(self, prompt, user_text, **kw):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_run_keeps_going_after_a_bad_batch():
    conn = _db()
    client = FakeClient([
        _result([{"idx": 1, "verdict": "없는판정"}]),        # 검증에 걸린다
        _result([{"idx": 1, "verdict": "drop", "reason": "복붙"}]),
    ])
    p = sc.run(conn, client, model="m1", size=1, log=lambda *a: None)
    assert p.batches == 2 and p.done == 1, (p.batches, p.done)
    assert len(p.failed) == 1
    assert p.screened == 1 and p.dropped == 1
    # 실패한 묶음의 댓글은 판정 없이 남아 다음 실행이 다시 집는다
    assert len(sc.pending(conn, "screen-v1", "m1")) == 1


def test_run_dry_run_calls_nothing():
    conn = _db()
    client = FakeClient([])                  # 하나라도 부르면 IndexError
    p = sc.run(conn, client, model="m1", dry_run=True, log=lambda *a: None)
    assert p.batches == 1 and p.done == 0
    assert conn.execute("SELECT COUNT(*) FROM comment_screens WHERE model='m1'"
                        ).fetchone()[0] == 0


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
