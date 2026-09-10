"""3단계 제목 판정 경로 — 묶음 본문, 오프라인 파일, 체계가 하나라는 것.

API 키 없이 도는 테스트다. 실제 호출 대신 가짜 client 를 넣어 "무엇을
보냈고 무엇을 저장했나"만 본다 — 이 모듈에서 틀리면 조용히 틀리는 것들이
거기 있다.
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import connect  # noqa: E402
from app.pipeline import classify_videos as cv  # noqa: E402
from app.pipeline import label_videos as lv  # noqa: E402


ROWS = [
    {"video_id": "v1", "title": "하겐다즈 맛이...", "length_axis": "shorts"},
    {"video_id": "v2", "title": "돈슐랭 후기", "length_axis": "standard"},
    {"video_id": "v3", "title": "10분 토론", "length_axis": "long"},
    {"video_id": "v4", "title": "아직 안 잰 것", "length_axis": None},
]


class _Usage:
    def describe(self, model):
        return f"호출 0회 (가짜 client, model={model})"


class FakeClient:
    """judge 를 부를 때마다 준비된 답을 하나씩 내준다."""

    def __init__(self, replies):
        self.model = "fake-model"
        self.replies = list(replies)
        self.sent = []
        self.usage = _Usage()

    def judge(self, prompt, user_text, **kw):
        self.sent.append(user_text)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _db():
    """채널 1개 · 영상 4편이 든 임시 DB."""
    path = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    conn = connect(path)
    conn.execute("""INSERT INTO channels (channel_id, input_url, title,
                        uploads_playlist, first_analyzed_at)
                    VALUES ('ch1','u','채널','UU','2026-01-01')""")
    for i, r in enumerate(ROWS):
        conn.execute("""INSERT INTO videos (video_id, channel_id, title,
                            duration_sec, published_at, length_axis, first_seen_at)
                        VALUES (?,?,?,?,?,?,?)""",
                     (r["video_id"], "ch1", r["title"], 60,
                      f"2026-01-0{i + 1}", r["length_axis"], "2026-01-01"))
    return conn


# --------------------------------------------------------------------------
# 묶음 본문 — 번호와 길이 축
# --------------------------------------------------------------------------

def test_titles_body_numbers_round_trip():
    """번호↔video_id 가 어긋나면 라벨이 통째로 엉뚱한 영상에 붙는다."""
    body, mapping = lv.titles_body(ROWS, "b_001", "채널")
    assert mapping == {"1": "v1", "2": "v2", "3": "v3", "4": "v4"}
    for i, r in enumerate(ROWS, 1):
        assert r["title"] in body
        assert body.count(f"\n{i}.[") == 1, f"{i}번 줄이 하나가 아니다"


def test_titles_body_marks_length_axis():
    """길이 축은 제목 옆에 붙는 유일한 사실이다 — 없으면 쇼츠 낚시에 끌려간다."""
    body, _ = lv.titles_body(ROWS, "b_001", "채널")
    assert "1.[S] 하겐다즈 맛이..." in body
    assert "2.[M] 돈슐랭 후기" in body
    assert "3.[L] 10분 토론" in body


def test_titles_body_marks_unknown_axis_as_question():
    """축을 아직 안 잰 영상에 S 를 적으면 없는 사실을 주는 것이다."""
    body, _ = lv.titles_body(ROWS, "b_001", "채널")
    assert "4.[?] 아직 안 잰 것" in body


def test_titles_body_flattens_newlines():
    """제목 안의 줄바꿈을 두면 번호 목록이 끊겨 한 편이 둘로 읽힌다."""
    body, mapping = lv.titles_body(
        [{"video_id": "v1", "title": "앞\n뒤", "length_axis": "shorts"}],
        "b", "채널")
    assert "1.[S] 앞 ⏎ 뒤" in body
    assert body.strip().splitlines()[-1].startswith("1."), "제목이 두 줄로 끊겼다"
    assert mapping == {"1": "v1"}


def test_chunk_and_estimate_agree():
    rows = ROWS * 30                       # 120편
    assert len(lv.chunk(rows, 50)) == 3
    assert lv.estimate(rows, 50)["batches"] == 3
    assert lv.estimate(rows, 50)["videos"] == 120
    assert lv.estimate([], 50)["batches"] == 0


# --------------------------------------------------------------------------
# 오프라인 파일 — 프롬프트 전문이 통째로 들어가야 한다
# --------------------------------------------------------------------------

def test_export_carries_the_whole_prompt():
    """전문이 아니라 요약이 나가면, 오프라인에서 잰 정확도가 API 를 보장하지 못한다."""
    out = pathlib.Path(tempfile.mkdtemp())
    path = lv.export(None, "ch1", lv.PROMPT_TYPES, "b_001", out,
                     rows=ROWS, channel_title="채널")
    text = path.read_text(encoding="utf-8")
    from app.prompts.registry import get as get_prompt
    prompt = get_prompt(lv.PROMPT_TYPES)
    assert prompt.full_text in text, "프롬프트 전문이 빠졌다"
    assert "- 버전: topics-v1" in text, "헤더(버전)가 빠졌다"
    assert "1.[S] 하겐다즈 맛이..." in text
    assert '"1": "v1"' in text, "대응표 블록이 빠졌다"


def test_export_writes_map_file():
    out = pathlib.Path(tempfile.mkdtemp())
    lv.export(None, "ch1", lv.PROMPT_TAXONOMY, "b_001", out,
              rows=ROWS, channel_title="채널")
    data = json.loads((out / "b_001.map.json").read_text(encoding="utf-8"))
    assert data["map"]["3"] == "v3"
    assert data["prompt_version"] == "taxonomy-v1"


# --------------------------------------------------------------------------
# 저장 — 체계와 라벨은 함께 들어간다
# --------------------------------------------------------------------------

def test_save_result_puts_labels_on_their_own_taxonomy():
    conn = _db()
    payload = {"taxonomy_version": "t-v1", "types": {"A": "가", "B": "나"},
               "labels": {"1": "A", "2": "B"}}
    tid, n, rows = lv.save_result(conn, "ch1", payload, {"1": "v1", "2": "v2"},
                                  "test-offline")
    assert n == 2
    got = conn.execute("SELECT taxonomy_id, type_code FROM video_type_labels").fetchall()
    assert {r["taxonomy_id"] for r in got} == {tid}


def test_save_result_saves_nothing_when_validation_fails():
    """검증에 걸린 묶음이 체계만 남기고 죽으면, 라벨 없는 자가 활성이 된다."""
    conn = _db()
    before = conn.execute("SELECT COUNT(*) FROM video_taxonomies").fetchone()[0]
    try:
        lv.save_result(conn, "ch1", {"types": {"A": "가"}, "labels": {"9": "A"}},
                       {"1": "v1"}, "test-offline")
    except cv.ValidationError:
        after = conn.execute("SELECT COUNT(*) FROM video_taxonomies").fetchone()[0]
        assert after == before, "검증에 걸렸는데 체계가 저장됐다"
        return
    raise AssertionError("없는 번호가 통과했다")


# --------------------------------------------------------------------------
# 체계는 한 번의 호출에서만 나온다
# --------------------------------------------------------------------------

def test_chunked_labeling_keeps_one_taxonomy():
    """묶음마다 체계를 새로 받으면 코드 이름이 같아도 다른 자가 된다.

    두 번째 호출이 새 types 를 들고 와도 버리고, 첫 호출의 자로만 잰다.
    """
    conn = _db()
    client = FakeClient([
        {"types": {"A": "가"}, "labels": {"1": "A"}},
        {"types": {"B": "나"}, "labels": {"1": "A"}},   # 새 체계는 무시된다
        {"types": {"C": "다"}, "labels": {"1": "A"}},
        {"types": {"D": "라"}, "labels": {"1": "A"}},
    ])
    p = lv.label(conn, client, "ch1", model="m1", size=1, log=lambda *a: None)

    assert p.batches == 4 and p.done == 4, (p.batches, p.done)
    assert p.labeled == 4
    taxes = conn.execute("SELECT types_json FROM video_taxonomies "
                         "WHERE axis='topic'").fetchall()
    assert len(taxes) == 1, f"체계가 {len(taxes)}벌 생겼다"
    assert json.loads(taxes[0]["types_json"]) == {"A": "가"}
    assert "이미 확정된 유형 체계" in client.sent[1], \
        "두 번째 묶음에 확정된 체계를 주지 않았다"
    assert "이미 확정된 유형 체계" not in client.sent[0]


def test_label_isolates_a_failed_batch():
    """한 묶음이 틀려도 나머지는 계속 간다. 실패한 영상은 라벨 없이 남는다."""
    conn = _db()
    client = FakeClient([
        {"types": {"A": "가"}, "labels": {"1": "A"}},
        {"types": {"A": "가"}, "labels": {"1": "없는코드"}},   # 검증에 걸린다
        {"types": {"A": "가"}, "labels": {"1": "A"}},
        {"types": {"A": "가"}, "labels": {"1": "A"}},
    ])
    p = lv.label(conn, client, "ch1", model="m1", size=1, log=lambda *a: None)
    assert p.done == 3 and len(p.failed) == 1, (p.done, p.failed)
    assert p.labeled == 3
    left = conn.execute("SELECT COUNT(*) FROM video_type_labels").fetchone()[0]
    assert left == 3


def test_pending_skips_already_labeled():
    conn = _db()
    client = FakeClient([{"types": {"A": "가"}, "labels": {str(i + 1): "A"
                                                          for i in range(4)}}])
    lv.label(conn, client, "ch1", model="m1", log=lambda *a: None)
    assert lv.pending(conn, "ch1", "topics-v1", "m1") == []
    # 모델이 다르면 다시 대상이다 — 덮어쓰기가 아니라 나란히 쌓는 설계다
    assert len(lv.pending(conn, "ch1", "topics-v1", "m2")) == 4


# --------------------------------------------------------------------------
# 체계 제안은 저장하지 않는다
# --------------------------------------------------------------------------

PROPOSAL = {
    "taxonomy_version": "ch1-topics-v1",
    "types": {"A": "가", "B": "나", "C": "다", "D": "라", "E": "마"},
    "definitions": {k: "든다: … · 안 든다: …" for k in "ABCDE"},
    "rationale": "왜 이렇게 갈랐는지.",
}


def test_propose_does_not_save_a_taxonomy():
    """제안은 제안이다. 아무도 보지 않은 자에 라벨이 매달리면 안 된다."""
    conn = _db()
    client = FakeClient([PROPOSAL])
    p = lv.propose(conn, client, "ch1", log=lambda *a: None)

    assert p.proposal == PROPOSAL
    assert p.taxonomy_id is None
    n = conn.execute("SELECT COUNT(*) FROM video_taxonomies").fetchone()[0]
    assert n == 0, "제안 단계에서 체계가 저장됐다"
    assert conn.execute("SELECT COUNT(*) FROM video_type_labels").fetchone()[0] == 0


def test_propose_writes_the_proposal_to_a_file():
    conn = _db()
    out = pathlib.Path(tempfile.mkdtemp())
    lv.propose(conn, FakeClient([PROPOSAL]), "ch1", out_dir=out,
               log=lambda *a: None)
    files = list(out.glob("*.result.json"))
    assert files, "제안을 파일로 남기지 않았다"
    assert json.loads(files[0].read_text(encoding="utf-8"))["types"] == PROPOSAL["types"]


def test_propose_asks_once_even_with_many_titles():
    """나눠 물으면 나눈 만큼의 체계가 나온다 — 질문 자체가 성립하지 않는다."""
    conn = _db()
    client = FakeClient([PROPOSAL])
    lv.propose(conn, client, "ch1", log=lambda *a: None)
    assert len(client.sent) == 1


def test_describe_leaves_counts_empty_without_labels():
    """편수를 0 으로 찍으면 '이 유형은 비었다'는 다른 말이 된다."""
    out = []
    lv.describe(PROPOSAL, None, log=out.append)
    text = "\n".join(out)
    assert "—편" in text
    assert "아직 라벨이 없어서다" in text


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
