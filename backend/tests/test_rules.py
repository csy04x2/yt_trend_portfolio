"""규칙 필터 테스트.

fixtures/sample_comments.json의 _expect가 곧 명세다. 표본을 고치면
테스트가 따라 움직인다 — 0단계에서 실제 댓글로 표본을 갈아끼울 때
기대값도 같이 적으면 된다.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.rules import (  # noqa: E402
    DEFAULT_CONFIG,
    VERDICT_KEEP,
    emoji_only,
    has_url,
    is_first_post,
    is_promo,
    screen_comments,
)

FIXTURE = json.loads(
    (ROOT / "fixtures" / "sample_comments.json").read_text(encoding="utf-8")
)
COMMENTS = FIXTURE["comments"]


def test_fixture_expectations():
    """표본 전체가 기대한 verdict로 떨어지는가."""
    screens = {s.comment_id: s for s in screen_comments(COMMENTS)}
    wrong = []
    for c in COMMENTS:
        got = screens[c["comment_id"]].verdict
        want = c["_expect"]
        if got != want:
            wrong.append(f"  {c['comment_id']} {c['text'][:24]!r}: {want} 기대 → {got}")
    assert not wrong, "기대와 다른 판정:\n" + "\n".join(wrong)


def test_emoji_only_is_never_dropped():
    """이 프로토타입의 존재 이유. 👍👍👍는 버려지지 않는다."""
    for text in ("👍👍👍", "❤️", "🔥🔥🔥🔥🔥", "😂😂"):
        screens = screen_comments([
            {"comment_id": "x", "author_channel_id": "UC1", "text": text}
        ])
        assert screens[0].verdict == VERDICT_KEEP, f"{text} 가 버려졌다"
        assert screens[0].needs_llm, f"{text} 가 LLM으로 안 갔다"
        assert "emoji_only" in screens[0].rule_flags


def test_rules_never_decide_sentiment():
    """규칙 결과에 감성 정보가 섞여 있지 않은가."""
    screens = screen_comments(COMMENTS)
    for s in screens:
        assert not hasattr(s, "sentiment")
        for flag in s.rule_flags:
            assert flag not in ("positive", "negative", "neutral")


def test_url_alone_is_not_promo():
    """URL만으로 홍보 판정하지 않는다 — 출처 제시 댓글을 살린다."""
    source = "이 수치 틀렸습니다. 원자료는 https://www.moef.go.kr/example 여기요"
    assert has_url(source)
    assert not is_promo(source, DEFAULT_CONFIG)

    promo = "무료 체험 문의 카톡 👉 https://spam.example.com"
    assert is_promo(promo, DEFAULT_CONFIG)


def test_short_korean_feedback_survives():
    """자수를 판정 근거로 쓰지 않는다."""
    for text in ("유익함", "아쉽다", "재밌다", "별로"):
        screens = screen_comments([
            {"comment_id": "x", "author_channel_id": "UC1", "text": text}
        ])
        assert screens[0].verdict == VERDICT_KEEP, f"{text} 가 버려졌다"


def test_first_post_detected():
    for text in ("1등", "4등!!", "10빠", "3착", "2등ㅋㅋㅋ", "first!!", "선댓", "1빠", "3번째"):
        assert is_first_post(text, DEFAULT_CONFIG), f"{text} 를 선점으로 못 잡았다"
    for text in ("1등이라니 대단하네요", "4등이라니 대단하네요", "3착으로 들어왔지만 재밌게 봤어요", "first impression 좋았어요"):
        assert not is_first_post(text, DEFAULT_CONFIG), f"{text} 를 잘못 잡았다"


def test_emoji_only_helper():
    assert emoji_only("👍👍👍")
    assert emoji_only("🔥 🔥")
    assert not emoji_only("👍 좋아요")
    assert not emoji_only("ㅋㅋㅋ")   # 자음은 이모지가 아니다
    assert not emoji_only("")


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
            print(f"  FAIL  {fn.__name__}\n{e}")
        except Exception:
            failed += 1
            print(f"  ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)
