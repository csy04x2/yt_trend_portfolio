"""정규화 순수 함수 테스트."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.normalize import (  # noqa: E402
    DEFAULT,
    comment_rate_multiple,
    compute,
    length_axis,
    quarter_of,
    strip_boilerplate,
    view_multiple,
)


def _v(vid, views, dur=1500, when="2026-07-01T00:00:00Z", **kw):
    d = {"video_id": vid, "view_count": views, "duration_sec": dur,
         "published_at": when, "is_live": 0, "like_count": 100,
         "comment_count": 10}
    d["length_axis"] = length_axis(dur)
    d.update(kw)
    return d


def test_length_axis_boundaries():
    assert length_axis(60) == "shorts"
    assert length_axis(180) == "shorts"        # 경계 포함
    assert length_axis(181) == "standard"
    assert length_axis(1200) == "standard"     # 20분 정각
    assert length_axis(1231) == "long"         # 20분 31초 → long
    assert length_axis(3137) == "long"


def test_quarter_of():
    assert quarter_of("2026-09-09T12:00:00Z") == "2026Q3"
    assert quarter_of("2026-01-01T00:00:00+00:00") == "2026Q1"
    assert quarter_of("2025-12-31T23:00:00Z") == "2025Q4"


def test_view_multiple_refuses_small_population():
    """영상 두 개로 낸 배수는 정보가 아니라 착시다. 값 대신 이유를 낸다."""
    a, b = _v("a", 100_000), _v("b", 20_000)
    mult, basis = view_multiple(a, [a, b], DEFAULT)
    assert mult is None
    assert "비교군 부족" in basis and "1개" in basis


def test_view_multiple_excludes_self():
    """자기 자신이 분모에 들어가면 배수가 1 쪽으로 눌린다."""
    pop = [_v("a", 100_000)] + [_v(f"p{i}", 20_000) for i in range(4)]
    mult, basis = view_multiple(pop[0], pop, DEFAULT)
    assert mult == 5.0, f"기대 5.0 → {mult}"     # 100000 / median(20000×4)
    assert "중앙값" in basis


def test_view_multiple_splits_by_axis_and_quarter():
    """길이 축이나 분기가 다르면 비교군에 넣지 않는다."""
    target = _v("t", 50_000, dur=1500, when="2026-07-01T00:00:00Z")
    others = (
        [_v(f"s{i}", 10_000, dur=60, when="2026-07-01T00:00:00Z") for i in range(4)] +
        [_v(f"q{i}", 10_000, dur=1500, when="2026-01-01T00:00:00Z") for i in range(4)]
    )
    mult, basis = view_multiple(target, [target] + others, DEFAULT)
    assert mult is None, "축·분기가 다른 영상이 비교군에 들어갔다"


def test_view_multiple_excludes_live():
    pop = [_v("a", 100_000)] + [_v(f"L{i}", 20_000, is_live=1) for i in range(4)]
    mult, _ = view_multiple(pop[0], pop, DEFAULT)
    assert mult is None, "라이브가 비교군에 들어갔다"


def test_like_rate_none_when_hidden():
    """좋아요가 비공개면 0 이 아니라 NULL. 0 이면 '평가가 나쁘다'로 읽힌다."""
    m = compute(_v("a", 1000, like_count=None), [_v("a", 1000)])
    assert m["like_rate"] is None
    m2 = compute(_v("b", 1000, like_count=25), [_v("b", 1000)])
    assert abs(m2["like_rate"] - 0.025) < 1e-9


def test_strip_boilerplate():
    common = "구독과 좋아요 부탁드립니다"
    ds = [f"{common}\n첫 영상 설명", f"{common}\n둘째 설명", f"{common}\n셋째 설명"]
    out = strip_boilerplate(ds, DEFAULT)
    assert all(common not in o for o in out), "상용구가 안 지워졌다"
    assert "첫 영상 설명" in out[0] and "셋째 설명" in out[2]


def test_strip_boilerplate_leaves_small_sets_alone():
    """영상이 적으면 우연히 겹친 줄까지 지울 위험이 크다."""
    ds = ["같은 줄\nA", "같은 줄\nB"]
    assert strip_boilerplate(ds, DEFAULT) == ds


# --------------------------------------------------------------------------
# 댓글율 배수 — 비교군 잡는 법은 조회 배수와 똑같아야 한다
# --------------------------------------------------------------------------

def test_comment_rate_multiple_excludes_self():
    """자기 자신이 분모에 들어가면 배수가 1 쪽으로 눌린다."""
    target = _v("a", 100_000, comment_count=400)          # 댓글율 0.4%
    pop = [target] + [_v(f"p{i}", 100_000, comment_count=100) for i in range(4)]
    mult, basis = comment_rate_multiple(target, pop, DEFAULT)
    assert mult == 4.0, f"기대 4.0 → {mult}"              # 0.4% / 중앙값 0.1%
    assert "중앙값" in basis


def test_comment_rate_multiple_refuses_small_population():
    """조회 배수와 같은 규칙 — 표본이 모자라면 값 대신 이유."""
    a, b = _v("a", 100_000, comment_count=400), _v("b", 100_000, comment_count=100)
    mult, basis = comment_rate_multiple(a, [a, b], DEFAULT)
    assert mult is None
    assert "비교군 부족" in basis and "1개" in basis


def test_comment_rate_multiple_splits_by_axis_and_quarter():
    """조회 배수와 같은 비교군을 써야 둘을 나란히 읽을 수 있다."""
    target = _v("t", 50_000, dur=1500, when="2026-07-01T00:00:00Z")
    others = (
        [_v(f"s{i}", 10_000, dur=60, when="2026-07-01T00:00:00Z") for i in range(4)] +
        [_v(f"q{i}", 10_000, dur=1500, when="2026-01-01T00:00:00Z") for i in range(4)]
    )
    mult, _ = comment_rate_multiple(target, [target] + others, DEFAULT)
    assert mult is None, "축·분기가 다른 영상이 비교군에 들어갔다"


def test_comment_rate_multiple_in_compute():
    """compute 가 값과 근거를 함께 낸다. 근거 없이 빈 값만 내면 안 된다."""
    target = _v("a", 100_000, comment_count=400)
    pop = [target] + [_v(f"p{i}", 100_000, comment_count=100) for i in range(4)]
    m = compute(target, pop)
    assert m["comment_rate_multiple"] == 4.0
    assert m["comment_rate_multiple_basis"]
    lonely = compute(_v("z", 1000), [_v("z", 1000)])
    assert lonely["comment_rate_multiple"] is None
    assert "비교군 부족" in lonely["comment_rate_multiple_basis"]


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
