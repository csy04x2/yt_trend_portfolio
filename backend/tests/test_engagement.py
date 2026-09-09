"""참여 성격(호응/논쟁) 순수 함수 테스트.

여기서 지키려는 것은 두 가지다.

1. approval 과 contention 이 실제로 서로 다른 것을 말하는가.
   한쪽으로 쏠린 100건과 반반으로 갈린 100건은 댓글 수가 같다. 두 값이
   그 둘을 갈라내지 못하면 이 지표는 존재할 이유가 없다.
2. 표본이 모자랄 때 값을 내지 않는가.
   긍·부정 세 건으로 낸 approval 이 소수점 두 자리로 찍히면 정밀한
   측정처럼 보인다. `view_multiple` 과 같은 규칙 — 못 내면 이유를 남긴다.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.engagement import (  # noqa: E402
    DEFAULT,
    EngagementConfig,
    compute,
)


def _c(pos=0, neg=0, neu=0):
    return {"positive": pos, "negative": neg, "neutral": neu}


def test_one_sided_has_no_contention():
    """칭찬만 90건. 논쟁은 0 이어야 한다."""
    e = compute("v", _c(pos=90, neg=0), 100)
    assert e["contention"] == 0.0, f"기대 0 → {e['contention']}"
    assert e["approval"] == 1.0, f"기대 1 → {e['approval']}"


def test_one_sided_negative_is_also_uncontested():
    """비난만 90건도 '갈린 것'이 아니다. 논쟁 0, 호응 0."""
    e = compute("v", _c(pos=0, neg=90), 100)
    assert e["contention"] == 0.0
    assert e["approval"] == 0.0


def test_even_split_is_full_contention():
    """긍정 45 · 부정 45 → 완전히 반반. 논쟁 1, 호응 0.5."""
    e = compute("v", _c(pos=45, neg=45), 100)
    assert abs(e["contention"] - 1.0) < 1e-9, f"기대 1.0 → {e['contention']}"
    assert abs(e["approval"] - 0.5) < 1e-9


def test_contention_separates_same_comment_volume():
    """댓글 수가 같아도 성격이 다르면 값이 갈려야 한다.

    이 테스트가 이 모듈의 존재 이유다. 두 영상 다 라벨 100건인데
    하나는 호응, 하나는 논쟁이다.
    """
    calm = compute("calm", _c(pos=95, neg=5), 100)
    fight = compute("fight", _c(pos=52, neg=48), 100)
    assert calm["contention"] < 0.2, f"호응 영상의 논쟁이 높다: {calm['contention']}"
    assert fight["contention"] > 0.8, f"논쟁 영상의 논쟁이 낮다: {fight['contention']}"
    assert calm["approval"] > fight["approval"]


def test_refuses_small_polar_sample():
    """긍·부정이 10건 미만이면 값 대신 이유. 착시가 빈칸보다 나쁘다."""
    e = compute("v", _c(pos=5, neg=4), 20)
    assert e["approval"] is None, f"표본 9건인데 값을 냈다: {e['approval']}"
    assert e["contention"] is None
    assert "9건" in e["basis"] and "10건" in e["basis"], e["basis"]


def test_accepts_exactly_the_minimum():
    """경계 포함 — 10건이면 낸다. 9건에서 멈추고 10건에서 낸다."""
    e = compute("v", _c(pos=6, neg=4), 20)
    assert e["approval"] is not None, e["basis"]
    assert abs(e["approval"] - 0.6) < 1e-9


def test_neutral_only_yields_nothing():
    """neutral 만 50건. 호응도 논쟁도 아니라 둘 다 값이 없다."""
    e = compute("v", _c(neu=50), 60)
    assert e["approval"] is None
    assert e["contention"] is None
    assert "neutral" in e["basis"], e["basis"]
    # 라벨을 본 것 자체는 사실이므로 라벨비율은 남는다
    assert abs(e["labeled_ratio"] - 50 / 60) < 1e-9


def test_neutral_stays_out_of_the_denominator():
    """neutral 이 분모에 들어가면 호응이 0.5 쪽으로 눌린다."""
    e = compute("v", _c(pos=30, neg=10, neu=200), 300)
    assert abs(e["approval"] - 0.75) < 1e-9, (
        f"neutral 200건이 분모에 섞였다 → {e['approval']}"
    )
    assert abs(e["contention"] - 0.5) < 1e-9
    assert e["neutral"] == 200, "neutral 건수 자체는 버리지 않는다"


def test_no_labels_at_all_leaves_a_reason():
    """라벨이 하나도 없는 영상도 행을 남긴다 — 왜 비었는지 말해야 한다."""
    e = compute("v", {}, 40)
    assert e["approval"] is None and e["contention"] is None
    assert e["labeled_ratio"] == 0.0
    assert "라벨된 댓글이 없다" in e["basis"], e["basis"]


def test_labeled_ratio_is_none_without_collected_comments():
    """수집 댓글이 0이면 비율이 0 이 아니라 없는 것이다."""
    e = compute("v", {}, 0)
    assert e["labeled_ratio"] is None


def test_labeled_ratio_reports_coverage():
    """282건 중 91건만 라벨됐다면 두 값도 그만큼만 믿는다."""
    e = compute("v", _c(pos=54, neg=37, neu=117), 209)
    assert abs(e["labeled_ratio"] - 208 / 209) < 1e-9
    assert "209" in e["basis"], e["basis"]


def test_min_polar_is_configurable():
    """기준은 설정값이다. 하드코딩된 10 을 읽는 곳이 없어야 한다."""
    cfg = EngagementConfig(min_polar=3)
    e = compute("v", _c(pos=2, neg=1), 10, cfg)
    assert e["approval"] is not None, e["basis"]
    assert DEFAULT.min_polar == 10


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
