"""3단계 유형 분류·코너 축 순수 함수 테스트."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import segments as sg  # noqa: E402
from app.pipeline.classify_videos import (  # noqa: E402
    ALL,
    LONGFORM,
    SHORTS,
    ValidationError,
    masked_types,
    validate,
    view_group,
)


# --------------------------------------------------------------------------
# 유형 라벨 검증 — 조용히 넘어가는 것이 가장 나쁘다
# --------------------------------------------------------------------------

def _payload(labels, types=None):
    return {"types": types or {"A": "가", "B": "나"}, "labels": labels}


def test_validate_ok():
    rows = validate(_payload({"1": "A", "2": "B"}), {"1": "v1", "2": "v2"})
    assert [r["video_id"] for r in rows] == ["v1", "v2"]


def test_validate_catches_unknown_type():
    try:
        validate(_payload({"1": "A", "2": "ZZZ"}), {"1": "v1", "2": "v2"})
    except ValidationError as e:
        assert "ZZZ" in str(e)
        return
    raise AssertionError("정의되지 않은 유형 코드를 통과시켰다")


def test_validate_catches_missing_and_extra():
    try:
        validate(_payload({"1": "A", "9": "B"}), {"1": "v1", "2": "v2"})
    except ValidationError as e:
        assert "없는 번호 9" in str(e), e
        assert "빠진 번호" in str(e), e
        return
    raise AssertionError("빠진 번호·없는 번호를 통과시켰다")


def test_validate_requires_types():
    try:
        validate({"labels": {"1": "A"}}, {"1": "v1"})
    except ValidationError as e:
        assert "types" in str(e)
        return
    raise AssertionError("체계 없이 라벨만 넣는 것을 통과시켰다")


# --------------------------------------------------------------------------
# 길이 묶음 — 계산 축(3개)과 표시 축(2개)은 다르다
# --------------------------------------------------------------------------

def test_view_group():
    assert view_group("shorts") == SHORTS
    assert view_group("standard") == LONGFORM
    assert view_group("long") == LONGFORM


def test_masked_types_flags_opposite_directions():
    """쇼츠와 롱폼이 반대로 움직이면 합침 줄은 거짓말이 된다."""
    mets = [
        {"type_code": "HIST", "length_axis": SHORTS, "med_view_multiple": 0.59},
        {"type_code": "HIST", "length_axis": LONGFORM, "med_view_multiple": 1.61},
        {"type_code": "HIST", "length_axis": ALL, "med_view_multiple": 0.88},
        {"type_code": "FOOD", "length_axis": SHORTS, "med_view_multiple": 0.89},
        {"type_code": "FOOD", "length_axis": LONGFORM, "med_view_multiple": 0.76},
        {"type_code": "FOOD", "length_axis": ALL, "med_view_multiple": 0.85},
    ]
    flagged = masked_types(mets)
    assert [f["type_code"] for f in flagged] == ["HIST"], flagged
    assert abs(flagged[0]["gap"] - 1.02) < 1e-9


def test_masked_types_needs_both_sides():
    """한쪽만 있으면 비교 자체가 성립하지 않는다 — 경고하지 않는다."""
    mets = [{"type_code": "X", "length_axis": LONGFORM, "med_view_multiple": 2.0},
            {"type_code": "X", "length_axis": ALL, "med_view_multiple": 2.0}]
    assert masked_types(mets) == []


# --------------------------------------------------------------------------
# 코너 — 재생목록에서 읽되 서랍은 거른다
# --------------------------------------------------------------------------

def test_clean_name():
    assert sg.clean_name("돈슐랭ㅣ알고 먹으면 더 맛있는 이야기") == "돈슐랭"
    assert sg.clean_name("선발대 | 이슈 탐험대") == "선발대"
    assert sg.clean_name("10분 토론") == "10분 토론"


def test_pick_segments_drops_drawers():
    """채널의 큰 비율을 담으면 코너가 아니라 보관함이다."""
    pls = [
        {"id": "p1", "title": "14F's PICKㅣDaily", "item_count": 1943},
        {"id": "p2", "title": "돈슐랭ㅣ맛있는 이야기", "item_count": 279},
        {"id": "p3", "title": "10분 토론ㅣ토론", "item_count": 127},
    ]
    got = sg.pick_segments(pls, 6400)
    assert "p1" not in got, "서랍이 코너로 들어갔다"
    assert got == {"p2": "돈슐랭", "p3": "10분 토론"}


def test_pick_segments_drops_tiny():
    pls = [{"id": "p1", "title": "일회성 묶음", "item_count": 2}]
    assert sg.pick_segments(pls, 6400) == {}


def test_pick_segments_without_channel_total():
    """채널 전체 편수를 모르면 서랍을 못 가른다 — 그래도 죽지는 않는다."""
    pls = [{"id": "p1", "title": "무엇ㅣ설명", "item_count": 100}]
    assert sg.pick_segments(pls, 0) == {"p1": "무엇"}


def test_assign_picks_smallest():
    """여러 코너에 들면 작은 쪽이 더 구체적이다."""
    member = {"v1": ["big", "small"], "v2": ["big"], "v3": ["none"]}
    segs = {"big": "큰코너", "small": "작은코너"}
    sizes = {"big": 200, "small": 20}
    got = sg.assign(member, segs, sizes)
    assert got == {"v1": "small", "v2": "big"}, got
    assert "v3" not in got, "코너가 아닌 재생목록에 배정됐다"


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
