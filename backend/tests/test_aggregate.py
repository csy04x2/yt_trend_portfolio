"""6단계 집계 순수 함수 테스트 — 접기, 전후 비교, 축 선택, 결론 문장."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import aggregate as ag  # noqa: E402
from app.pipeline.classify_videos import ALL, LONGFORM, SHORTS  # noqa: E402


def _c(cid, sentiment, topics, likes=0, sarcasm=False, conf=0.9):
    return {"comment_id": cid, "text": f"{cid} 본문", "like_count": likes,
            "sentiment": sentiment, "confidence": conf,
            "sarcasm_suspect": sarcasm, "topics": topics}


# --------------------------------------------------------------------------
# 영상별 접기
# --------------------------------------------------------------------------

def test_video_rollup_ratios():
    labels = ([_c(f"p{i}", "positive", ["T8"]) for i in range(6)]
              + [_c(f"n{i}", "negative", ["T1"]) for i in range(2)]
              + [_c(f"u{i}", "neutral", ["T9"]) for i in range(2)])
    got = ag.video_rollup(labels, collected=12)
    assert got["valid_comment_count"] == 10
    assert abs(got["positive_ratio"] - 0.6) < 1e-9
    assert abs(got["negative_ratio"] - 0.2) < 1e-9
    assert got["topic_counts"] == {"T8": 6, "T1": 2, "T9": 2}


def test_video_rollup_refuses_small_sample():
    """세 건으로 낸 비율이 소수점 두 자리로 찍히면 정밀해 보인다."""
    got = ag.video_rollup([_c("a", "positive", ["T1"])] * 3, collected=3)
    assert got["positive_ratio"] is None
    assert "최소" in got["basis"]
    assert got["top_positive"], "비율을 못 내도 대표 댓글은 남겨야 한다"


def test_video_rollup_empty_says_why():
    got = ag.video_rollup([], collected=40)
    assert got["valid_comment_count"] == 0
    assert "export-batch" in got["basis"], got["basis"]


def test_representatives_exclude_sarcasm_but_counts_keep_it():
    labels = [_c("s", "positive", ["T8"], likes=999, sarcasm=True),
              _c("ok", "positive", ["T8"], likes=5)]
    labels += [_c(f"x{i}", "neutral", ["T9"]) for i in range(8)]
    got = ag.video_rollup(labels, collected=10)
    ids = [r["comment_id"] for r in got["top_positive"]]
    assert ids == ["ok"], f"반어 의심이 대표 댓글에 들어갔다: {ids}"
    assert got["positive"] == 2, "세는 데서는 빼면 안 된다"


def test_representatives_sorted_by_likes():
    labels = [_c("low", "positive", ["T1"], likes=1),
              _c("high", "positive", ["T1"], likes=50),
              _c("mid", "positive", ["T1"], likes=10)]
    got = ag.video_rollup(labels, collected=3)
    assert [r["comment_id"] for r in got["top_positive"]] == ["high", "mid", "low"]


# --------------------------------------------------------------------------
# 유형별 접기
# --------------------------------------------------------------------------

def test_type_rollup_counts_comments_not_videos():
    """댓글 2건짜리 영상이 200건짜리 영상과 같은 무게를 가지면 안 된다."""
    big = [_c(f"b{i}", "positive", ["T1"]) for i in range(18)]
    small = [_c(f"s{i}", "negative", ["T1"]) for i in range(2)]
    got = ag.type_comment_rollup(
        {"v1": big, "v2": small},
        {"v1": "A", "v2": "A"},
        {"v1": "long", "v2": "long"})
    allrow = [r for r in got if r["length_axis"] == ALL][0]
    assert allrow["valid_comment_count"] == 20
    # 영상별 비율의 평균이면 0.5, 댓글을 다시 세면 0.9
    assert abs(allrow["positive_ratio"] - 0.9) < 1e-9, allrow


def test_type_rollup_splits_shorts_and_longform():
    rows = [_c(f"x{i}", "positive", ["T1"]) for i in range(10)]
    got = ag.type_comment_rollup(
        {"s1": rows, "l1": rows},
        {"s1": "A", "l1": "A"},
        {"s1": "shorts", "l1": "long"})
    axes = sorted(r["length_axis"] for r in got)
    assert axes == [ALL, LONGFORM, SHORTS], axes


def test_type_rollup_skips_unlabeled_videos():
    got = ag.type_comment_rollup(
        {"v1": [_c("a", "positive", ["T1"])]}, {}, {"v1": "long"})
    assert got == [], "유형이 없는 영상이 집계에 들어갔다"


# --------------------------------------------------------------------------
# 전후 비교
# --------------------------------------------------------------------------

def _v(i, code, vm, day):
    return {"video_id": f"v{i}", "type_code": code,
            "published_at": f"2026-{day}", "view_multiple": vm}


def test_recent_vs_prior_needs_three_each_side():
    cfg = ag.AggregateConfig(window=4)
    rows = ([_v(i, "A", 2.0, f"09-{10 + i:02d}") for i in range(4)]
            + [_v(i + 10, "A", 1.0, f"08-{10 + i:02d}") for i in range(4)])
    got = ag.recent_vs_prior(rows, cfg)
    assert "A" in got["types"]
    assert abs(got["types"]["A"]["delta"] - 1.0) < 1e-9


def test_recent_vs_prior_drops_thin_types():
    cfg = ag.AggregateConfig(window=4)
    rows = ([_v(i, "A", 2.0, f"09-{10 + i:02d}") for i in range(4)]
            + [_v(i + 10, "B", 1.0, f"08-{10 + i:02d}") for i in range(4)])
    assert ag.recent_vs_prior(rows, cfg)["types"] == {}, "한쪽에만 있는 유형이 남았다"


def test_recent_vs_prior_says_why_when_too_few():
    got = ag.recent_vs_prior([_v(0, "A", 1.0, "09-01")], ag.AggregateConfig(window=30))
    assert got["types"] == {}
    assert "가를 수 없다" in got["basis"], got["basis"]


# --------------------------------------------------------------------------
# 어느 축으로 읽는가
# --------------------------------------------------------------------------

def test_pick_axis_segment_when_covered():
    axis, why = ag.pick_axis({"topic": 1.0, "segment": 0.72}, LONGFORM)
    assert axis == "segment"
    assert "72%" in why


def test_pick_axis_topic_when_segment_thin():
    """14F 쇼츠 194편에는 코너가 0편이다 — 같은 채널 안에서도 답이 갈린다."""
    axis, why = ag.pick_axis({"topic": 1.0, "segment": 0.0}, SHORTS)
    assert axis == "topic"
    assert "0%" in why


# --------------------------------------------------------------------------
# 조사 — 결론 문장은 사람이 읽는 물건이다
# --------------------------------------------------------------------------

def test_particles():
    assert ag.ro("생활·정책") == "생활·정책으로"
    assert ag.ro("선발대") == "선발대로"          # ㄹ 받침은 '로'
    assert ag.ro("주락이월드") == "주락이월드로"    # 받침 없음
    assert ag.neun("돈슐랭") == "돈슐랭은"
    assert ag.neun("주락이월드") == "주락이월드는"
    assert ag.ga("역사·인문") == "역사·인문이"


# --------------------------------------------------------------------------
# 결론 문장
# --------------------------------------------------------------------------

NAMES = {"A": "생활·정책", "B": "역사·인문", "C": "선발대"}
TOPICS = {"T1": "정보·내용", "T8": "감정·응원"}


def _perf(code, vm, n):
    return {"type_code": code, "med_view_multiple": vm, "video_count": n}


def test_draft_needs_enough_videos():
    got, comp = ag.conclusion_draft([_perf("A", 9.9, 2)], [], NAMES, TOPICS,
                                    "topic", ALL)
    assert comp == "empty"
    assert "비교할 수 없다" in got, got


def test_draft_performance_only_without_comments():
    perf = [_perf("A", 2.43, 24), _perf("B", 0.88, 22)]
    got, comp = ag.conclusion_draft(perf, [], NAMES, TOPICS, "topic", SHORTS)
    assert comp == "performance_only"
    assert "생활·정책으로 2.43배" in got, got
    assert "피드백은 넣지 못했다" in got


def test_draft_says_how_many_types_had_comments():
    """7개 중 2개만 보고 '가장 높은'이라고 쓰면 7개를 다 잰 줄 안다."""
    perf = [_perf(c, v, 20) for c, v in (("A", 2.4), ("B", 1.1), ("C", 0.4))]
    comments = [{"type_code": "B", "negative_ratio": 0.178,
                 "valid_comment_count": 208, "top_negative_topics": {"T1": 22},
                 "top_positive_topics": {}}]
    got, comp = ag.conclusion_draft(perf, comments, NAMES, TOPICS, "topic", ALL)
    assert comp == "partial"
    assert "댓글이 있는 주제 1개 중" in got, got
    assert "나머지 주제 2개는" in got, got


def test_draft_warns_about_masked_types():
    perf = [_perf("A", 2.43, 24), _perf("B", 0.88, 22)]
    masked = [{"type_code": "B", "shorts": 0.59, "longform": 1.61, "gap": 1.02}]
    got, _ = ag.conclusion_draft(perf, [], NAMES, TOPICS, "topic", ALL, masked)
    assert "역사·인문은 쇼츠 0.59배와 롱폼 1.61배" in got, got
    assert "합친 값으로 읽으면 안 된다" in got


# --------------------------------------------------------------------------
# Claude 가 다듬은 문장을 언제 버리는가
# --------------------------------------------------------------------------

def test_same_numbers_rejects_rounding():
    assert ag.same_numbers("배수는 1.76배다", "배수는 1.76배였다")
    assert not ag.same_numbers("배수는 1.76배다", "배수는 약 1.8배다")


def test_same_numbers_ignores_order():
    assert ag.same_numbers("A 1.5, B 2.5", "B는 2.5이고 A는 1.5다")


def test_same_numbers_catches_invented_figure():
    assert not ag.same_numbers("1.76배다", "1.76배로 전년 대비 20% 늘었다")


class _Client:
    def __init__(self, text): self.text = text
    def judge(self, prompt, user): return {"text": self.text}


class _Broken:
    def judge(self, prompt, user): raise RuntimeError("과부하")


def test_polish_keeps_draft_when_numbers_change():
    draft = "조회 배수가 가장 높은 코너는 돈슐랭으로 1.76배다."
    text, src = ag.polish(_Client("돈슐랭이 약 1.8배로 가장 높다."), draft)
    assert (text, src) == (draft, "draft")


def test_polish_takes_text_when_numbers_match():
    draft = "조회 배수가 가장 높은 코너는 돈슐랭으로 1.76배다."
    better = "돈슐랭의 조회 배수가 1.76배로 가장 높다."
    text, src = ag.polish(_Client(better), draft)
    assert (text, src) == (better, "claude")


def test_polish_survives_api_failure():
    """리포트는 API 가 죽어도 나와야 한다."""
    draft = "배수 1.00배다."
    assert ag.polish(_Broken(), draft) == (draft, "draft")


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
