"""4단계 규칙 필터.

설계 원칙 — 논의(2026-09-09)에서 확정한 것:

    규칙은 "명백히 버릴 것"만 확정한다. 감성 판단은 절대 하지 않는다.

이모지만 있는 댓글(👍👍👍)은 버리지도, 규칙이 긍정으로 못 박지도 않는다.
그냥 통과시켜 5단계 LLM이 영상 제목과 함께 맥락으로 판단한다. 규칙이 감성을
확정하면 바로 그 판단을 하라고 있는 단계를 우회하는 셈이기 때문이다.

같은 이유로 자수(글자 수)는 판정 근거로 쓰지 않는다. 한국어는 "재밌다",
"유익함", "아쉽다"가 전부 세 글자로 완결된 피드백이다.

verdict 값은 아키텍처 4.2 comment_screens.verdict와 같다:
    promo | irrelevant | suspect_repeat | keep
"promo"와 "irrelevant"만 규칙이 확정하고, 나머지는 keep으로 LLM에 넘긴다.
suspect_repeat은 표시만 남기고 라벨링 단계로 함께 보낸다(아키텍처 6.5).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# 규칙이 확정할 수 있는 verdict
VERDICT_PROMO = "promo"
VERDICT_IRRELEVANT = "irrelevant"
VERDICT_SUSPECT_REPEAT = "suspect_repeat"
VERDICT_KEEP = "keep"

# 모델을 부르지 않고 규칙만으로 정한 행은 comment_screens.model에 이 값을 쓴다
MODEL_RULE = "rule"


# --------------------------------------------------------------------------
# 설정 — 코드에 박지 않는다. 0단계에서 실제 댓글을 보고 채운다.
# --------------------------------------------------------------------------

@dataclass
class RuleConfig:
    """규칙 임계값과 목록.

    전부 설정으로 빼둔 이유는 채널 장르마다 분포가 다르기 때문이다.
    0단계(첫 채널 댓글 100건 확인) 결과로 조정한다.
    """

    # 홍보 유인 문구. URL 단독은 스팸 근거가 아니다 — 아래 is_promo 참조.
    promo_phrases: tuple[str, ...] = (
        "무료", "체험", "문의", "카톡", "톡방", "디엠", "dm", "구매", "할인",
        "코드입력", "링크타고", "가입", "수익", "부업", "재테크", "먹튀",
        "텔레", "텔레그램", "오픈채팅", "상담",
    )
    # 홍보성 이모지. 유인 문구와 함께 나올 때만 신호로 본다.
    promo_emoji: tuple[str, ...] = ("🔞", "💰", "💵", "📲", "👉", "➡️", "🔗", "💊")

    # 선점 댓글 — 피드백 가치가 0이라 집계에서 뺀다. 스팸은 아니다.
    first_post_patterns: tuple[str, ...] = (
        r"^\s*\d+\s*(등|빠|착)\s*[!！?.。~ㅋㅎ\u110f\u1112]*\s*$",
        r"^\s*first\s*!*\s*$",
        r"^\s*선\s*(댓|점)\s*$",
        r"^\s*\d+\s*번째\s*$",
    )

    # 같은 작성자가 같은 문장을 이 횟수 이상 반복하면 suspect_repeat
    repeat_threshold: int = 3

    # 채널 내 서로 다른 작성자가 같은 문장을 이 횟수 이상 올리면 suspect_repeat
    # (한 사람이 여러 계정을 쓰거나 복붙이 도는 경우)
    cross_author_repeat_threshold: int = 5


DEFAULT_CONFIG = RuleConfig()


# --------------------------------------------------------------------------
# 판정 결과
# --------------------------------------------------------------------------

@dataclass
class Screen:
    comment_id: str
    verdict: str
    rule_flags: list[str] = field(default_factory=list)
    # 규칙이 확정하지 못하면 True — 4단계 LLM으로 보낸다
    needs_llm: bool = False


# --------------------------------------------------------------------------
# 텍스트 유틸
# --------------------------------------------------------------------------

_URL_RE = re.compile(r"(https?://|www\.)\S+|\b\S+\.(?:com|net|kr|io|me|ly|co)\b", re.I)
_WS_RE = re.compile(r"\s+")


# 이모지를 이루는 조합 문자. 단독으로는 카테고리가 Mn/Cf라 So 검사에 걸리지
# 않는다 — ❤️(U+2764 + U+FE0F)가 대표적이고, 이걸 빠뜨리면 하트 댓글이
# "이모지만 있는 댓글"로 잡히지 않아 그대로 LLM 비용을 태운다.
_EMOJI_JOINERS = frozenset({
    0x200D,           # ZWJ — 👨‍👩‍👧 같은 결합 이모지
    0xFE0E, 0xFE0F,   # 변이 선택자 (텍스트/이모지 표현)
    0x20E3,           # 키캡 결합 문자 — 1️⃣
})


def _is_emoji(ch: str) -> bool:
    """이모지·기호 계열인지. 한글/라틴/숫자/공백이 아니면 기호로 본다."""
    if ch.isspace() or ch.isalnum():
        return False
    if ord(ch) in _EMOJI_JOINERS:
        return True
    cat = unicodedata.category(ch)
    # So=기타 기호(이모지 대부분), Sk=수식 기호(피부색 등), Cf=서식 제어
    return cat in ("So", "Sk", "Cf") or ord(ch) >= 0x1F000


def normalize(text: str) -> str:
    """반복 탐지용 정규화. 원문은 절대 바꾸지 않는다(아키텍처 설계 원칙 4)."""
    t = unicodedata.normalize("NFKC", text).strip().lower()
    return _WS_RE.sub(" ", t)


def has_url(text: str) -> bool:
    return bool(_URL_RE.search(text))


def emoji_only(text: str) -> bool:
    """이모지·기호만으로 이루어진 댓글인가.

    이 함수는 "버릴 것"을 찾는 게 아니라 "규칙이 판단하지 말아야 할 것"을
    찾는다. 👍👍👍는 여기 걸리고, 그대로 keep으로 통과한다.
    """
    stripped = [c for c in text if not c.isspace()]
    if not stripped:
        return False
    return all(_is_emoji(c) for c in stripped)


# --------------------------------------------------------------------------
# 개별 규칙
# --------------------------------------------------------------------------

def is_promo(text: str, cfg: RuleConfig) -> bool:
    """홍보로 확정할 것인가.

    URL이 있다는 것만으로는 홍보가 아니다. 타임스탬프 링크, 출처 제시,
    관련 자료 공유가 전부 URL을 포함한다. 특히 언론사 채널에서는
    "이거 틀렸어요, 원자료는 여기" 같은 댓글이 가장 값진 피드백인데,
    URL만 보고 버리면 그게 통째로 사라진다.

    그래서 URL 또는 홍보 이모지가 "유인 문구"와 함께 나올 때만 확정한다.
    """
    lowered = text.lower()
    has_phrase = any(p in lowered for p in cfg.promo_phrases)
    if not has_phrase:
        return False
    return has_url(text) or any(e in text for e in cfg.promo_emoji)


def is_first_post(text: str, cfg: RuleConfig) -> bool:
    """선점 댓글. 스팸은 아니지만 피드백 가치가 없어 집계에서 뺀다."""
    t = normalize(text)
    return any(re.match(p, t, re.I) for p in cfg.first_post_patterns)


# --------------------------------------------------------------------------
# 배치 판정
# --------------------------------------------------------------------------

def screen_comments(
    comments: list[dict],
    cfg: RuleConfig = DEFAULT_CONFIG,
) -> list[Screen]:
    """댓글 목록에 규칙을 적용한다.

    comments 각 항목은 최소한 comment_id, text, author_channel_id를 갖는다.
    반복 탐지가 채널 전체를 봐야 하므로 한 번에 받는다.
    """
    # 반복 집계 — 같은 작성자 안에서, 그리고 작성자를 가로질러
    by_author: dict[str, Counter] = defaultdict(Counter)
    across = Counter()
    for c in comments:
        key = normalize(c.get("text", ""))
        if not key:
            continue
        by_author[c.get("author_channel_id") or ""][key] += 1
        across[key] += 1

    # 작성자를 가로지르는 반복은 서로 다른 작성자 수로 센다
    authors_per_text: dict[str, set] = defaultdict(set)
    for c in comments:
        key = normalize(c.get("text", ""))
        if key:
            authors_per_text[key].add(c.get("author_channel_id") or "")

    results: list[Screen] = []
    for c in comments:
        text = c.get("text", "")
        cid = c["comment_id"]
        author = c.get("author_channel_id") or ""
        key = normalize(text)
        flags: list[str] = []

        if has_url(text):
            flags.append("url")
        if emoji_only(text):
            flags.append("emoji_only")

        # 1) 홍보 — 확정
        if is_promo(text, cfg):
            flags.append("promo_phrase")
            results.append(Screen(cid, VERDICT_PROMO, flags))
            continue

        # 2) 선점 — 확정
        if is_first_post(text, cfg):
            flags.append("first_post")
            results.append(Screen(cid, VERDICT_IRRELEVANT, flags))
            continue

        # 3) 반복 — 표시만 하고 라벨링 단계로 함께 보낸다
        same_author = by_author[author][key] if key else 0
        distinct_authors = len(authors_per_text.get(key, ()))
        if key and (
            same_author >= cfg.repeat_threshold
            or distinct_authors >= cfg.cross_author_repeat_threshold
        ):
            flags.append("repeat")
            results.append(
                Screen(cid, VERDICT_SUSPECT_REPEAT, flags, needs_llm=False)
            )
            continue

        # 4) 나머지는 전부 LLM으로. 이모지만 있는 댓글도 여기로 온다.
        #    규칙은 감성을 판단하지 않는다.
        results.append(Screen(cid, VERDICT_KEEP, flags, needs_llm=True))

    return results


def summarize(screens: list[Screen]) -> dict[str, int]:
    """verdict별 건수. 규칙 튜닝할 때 한눈에 보려고."""
    return dict(Counter(s.verdict for s in screens))
