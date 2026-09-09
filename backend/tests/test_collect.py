"""수집 모듈의 순수 함수 테스트.

API 를 부르지 않는 부분만 본다 — URL 파싱과 길이 파싱. 네트워크가 필요한
부분은 키가 생긴 뒤 실제 호출로 확인한다.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.collect import parse_duration, parse_video_id  # noqa: E402

VID = "EorZZyZ2d0s"


def test_parse_video_id_forms():
    for url in (
        f"https://www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/watch?v={VID}&t=30s",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://m.youtube.com/watch?v={VID}",
        VID,
    ):
        assert parse_video_id(url) == VID, f"실패: {url}"


def test_parse_video_id_rejects_channel_urls():
    """채널 URL 을 영상으로 착각하면 안 된다 — 명령을 잘못 쓴 것이다."""
    for url in (
        "https://www.youtube.com/@14FMBC",
        "https://www.youtube.com/channel/UCiQ4DB-7pv-9Vnh1FZ0-N5A",
        "https://www.youtube.com/c/somename",
        "not a url",
    ):
        try:
            got = parse_video_id(url)
        except ValueError:
            continue
        raise AssertionError(f"{url} 를 영상 ID 로 잘못 읽었다: {got}")


def test_parse_duration():
    cases = {
        "PT20M31S": 20 * 60 + 31,
        "PT52M17S": 52 * 60 + 17,
        "PT1H2M3S": 3723,
        "PT45S": 45,
        "P1DT2H": 93600,
        "": 0,
    }
    for iso, want in cases.items():
        assert parse_duration(iso) == want, f"{iso}: {want} 기대 → {parse_duration(iso)}"


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
