"""댓글 분석 포함 여부(analysis eligibility)와 명시적 timestamp.

근거는 `docs/reaction-phase1-checkpoint.md` H2·H3 이고, 필드·규칙 정리는
`docs/design/comment-eligibility.md` 에 있다.

## 원칙 — raw 보존과 분석 포함 여부를 나눈다 (H3)

    모든 수집 댓글은 raw 로 남는다. 제외는 **삭제가 아니라 표시**다.

`analysis_eligible=0` 인 행도 `comments` 표에 그대로 있고, 왜 빠졌는지는
`exclusion_reason` 에 남는다. Audience Behavior/Reaction 을 세는 집계만 이
표시를 보고 거른다. 수집 커버리지(받아둔 댓글 수 대 API 댓글 수) 같은
수집 사실은 거르지 않는다 — 그건 시청자 행동이 아니라 수집 기록이다.

## 무엇으로 제외하는가 — 작은 닫힌 목록

    misplaced_data   API 가 돌려준 댓글의 videoId 가 요청한 영상과 다르다
    own_channel      작성자 채널 = 영상 채널 (채널 자신의 댓글)
    spam_confirmed   규칙 필터가 **확정**한 홍보(comment_screens verdict=promo, model=rule)

앞의 둘은 수집 시점에 원문 없이 ID 비교만으로 정해진다 — 재현 100% 다.
셋째는 규칙 단계가 돈 뒤에 붙는다. 수집 시점에는 판정이 아직 없기 때문이다.

**의심만으로는 제외하지 않는다.** `suspect_repeat`(반복 의심), 모델의 `drop`,
직원·부계정·사칭·상업 계정 "같아 보임"은 전부 eligible 로 남는다 (H3 마지막 줄).
`irrelevant`(선점 댓글 "1등")도 스팸이 아니라 이 목록에 넣지 않는다 —
이미 라벨 대상에서 빠지는 것은 규칙 판정의 몫이다.

## 답글은 부모를 따라가지 않는다

채널이 단 고정 댓글에 시청자가 답글을 달면, 부모는 own_channel 로 빠지고
답글은 eligible 이다. 부모는 답글의 맥락으로 raw 에 남는다. 그래서 `decide`
는 부모의 판정을 입력으로 받지 않는다 — 받을 자리가 없으면 실수로 전파할
수도 없다.

## timestamp 는 적힌 것만 (H2)

`32:19`, `1:02:03` 처럼 원문에 **글자 그대로** 있는 것만 뽑는다. 영상을 보고
장면을 추정하지 않고, 영상 길이로 거르지도 않는다 — 길이를 넘는 값을 버릴지는
읽는 쪽이 정한다. 뽑은 원문 문자열을 초 값과 함께 남겨 무엇을 읽었는지
되짚을 수 있게 한다.
"""

from __future__ import annotations

import json
import re

# 제외 사유. 닫힌 목록이다 — 새 사유는 문서(comment-eligibility.md)와 함께 늘린다.
REASON_OWN_CHANNEL = "own_channel"
REASON_MISPLACED = "misplaced_data"
REASON_SPAM_CONFIRMED = "spam_confirmed"
EXCLUSION_REASONS = frozenset({REASON_OWN_CHANNEL, REASON_MISPLACED, REASON_SPAM_CONFIRMED})

# exclusion_source 값. 누가 이 판정을 내렸는지
SOURCE_COLLECT = "collect"        # 수집 시점 ID 비교
SOURCE_MIGRATION = "migration"    # 옛 DB 에 열을 붙이며 channel_id 비교로 채움
SCREEN_SOURCE_PREFIX = "comment_screens:"   # + "<prompt_version>/<model>"

# 규칙이 확정한 스팸. rules.VERDICT_PROMO 와 같은 값이다.
# rules 를 import 하지 않는 이유: 이 모듈은 connection 에서도 불리므로
# 의존을 가볍게 둔다. 값이 어긋나면 테스트가 잡는다.
SPAM_CONFIRMED_VERDICTS = ("promo",)
SPAM_CONFIRMED_MODEL = "rule"


def decide(
    expected_video_id: str,
    reported_video_id: str | None,
    author_channel_id: str | None,
    video_channel_id: str | None,
) -> tuple[int, str | None, int | None]:
    """(analysis_eligible, exclusion_reason, author_is_channel_owner).

    순수 함수. 우선순위는 misplaced_data > own_channel — 잘못 들어온 데이터면
    작성자가 누구든 이 영상의 댓글이 아니다 (phase2_collect.comment_record 와 같은 순서).

    author_is_channel_owner 는 판정과 별개의 사실이다. 작성자나 영상 채널을
    모르면 None — 0 으로 두면 "채널 주인이 아님을 확인했다"로 읽힌다.
    """
    if author_channel_id and video_channel_id:
        owner: int | None = int(author_channel_id == video_channel_id)
    else:
        owner = None

    if reported_video_id and reported_video_id != expected_video_id:
        return 0, REASON_MISPLACED, owner
    if owner == 1:
        return 0, REASON_OWN_CHANNEL, owner
    return 1, None, owner


# --------------------------------------------------------------------------
# timestamp
# --------------------------------------------------------------------------

# 앞뒤에 숫자나 콜론이 붙지 않은 m:ss / mm:ss / mmm:ss / h:mm:ss.
# observable.timestamps 와 같은 모양이지만 영상 길이로 거르지 않는다.
_TS_RE = re.compile(r"(?<![\d:])(\d{1,3}:\d{2}(?::\d{2})?)(?![\d:])")


def extract_timestamps(text: str | None) -> list[dict]:
    """원문에 적힌 timestamp 를 나온 순서대로. 같은 문자열은 한 번만.

    [{"text": "32:19", "seconds": 1939}, ...]

    초·분 자리가 60 이상이면 시각 표기가 아니므로 버린다 (`1:99`).
    없는 것을 만들지 않는다 — 원문에 없으면 빈 목록이다.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for m in _TS_RE.finditer(text or ""):
        literal = m.group(1)
        parts = [int(p) for p in literal.split(":")]
        if parts[-1] >= 60 or (len(parts) == 3 and parts[1] >= 60):
            continue
        if literal in seen:
            continue
        seen.add(literal)
        seconds = sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
        out.append({"text": literal, "seconds": seconds})
    return out


def timestamps_json(text: str | None) -> str:
    return json.dumps(extract_timestamps(text), ensure_ascii=False)


# --------------------------------------------------------------------------
# DB — 옛 행 채우기와 확정 스팸 반영
# --------------------------------------------------------------------------

def backfill_comments(conn) -> dict[str, int]:
    """열을 막 붙인 옛 DB 의 행을 채운다. 여러 번 돌려도 같은 결과다.

    - author_is_channel_owner: videos.channel_id 와 비교해 채운다.
    - own_channel: 같은 비교로 정한다. 이미 사유가 있는 행은 건드리지 않는다.
    - misplaced_data: 옛 행에는 API 의 videoId 가 저장돼 있지 않아 **알 수 없다.**
      추정하지 않고 eligible·사유 NULL 로 둔다.
    - timestamps_json: 원문에서 다시 뽑는다 (기본값 '[]' 인 행만).
    - spam_confirmed: 이미 저장된 규칙 판정이 있으면 반영한다.
    """
    conn.execute(
        """UPDATE comments SET author_is_channel_owner = (
               SELECT CASE WHEN comments.author_channel_id = v.channel_id THEN 1 ELSE 0 END
               FROM videos v WHERE v.video_id = comments.video_id)
           WHERE author_is_channel_owner IS NULL AND author_channel_id IS NOT NULL""")
    own = conn.execute(
        """UPDATE comments SET analysis_eligible = 0, exclusion_reason = ?,
               exclusion_source = ?
           WHERE exclusion_reason IS NULL AND author_is_channel_owner = 1""",
        (REASON_OWN_CHANNEL, SOURCE_MIGRATION)).rowcount

    ts = 0
    rows = conn.execute(
        "SELECT comment_id, text FROM comments WHERE timestamps_json = '[]'").fetchall()
    for r in rows:
        found = extract_timestamps(r["text"])
        if found:
            conn.execute("UPDATE comments SET timestamps_json = ? WHERE comment_id = ?",
                         (json.dumps(found, ensure_ascii=False), r["comment_id"]))
            ts += 1

    spam = apply_screen_exclusions(conn)
    return {"own_channel": own, "timestamps": ts, "spam_confirmed": spam}


def apply_screen_exclusions(conn) -> int:
    """규칙이 확정한 스팸을 comments 에 반영한다. 반영된 행 수를 돌려준다.

    댓글마다 **가장 최근 규칙 판정 하나**만 본다. 옛 규칙 버전이 promo 라
    했어도 새 버전이 keep 이면 확정이 아니다. 그래서 먼저 spam_confirmed 표시를
    전부 걷고 다시 붙인다 — 규칙을 고쳐 돌리면 표시도 따라온다.
    own_channel·misplaced_data 는 건드리지 않는다. 그 둘이 먼저다.

    연결 고리는 exclusion_source 에 "comment_screens:<prompt_version>/<model>"
    로 남는다. comment_screens 의 PK 가 (comment_id, prompt_version, model) 이라
    이 값과 comment_id 로 근거 행을 정확히 다시 찾을 수 있다.
    """
    conn.execute(
        """UPDATE comments SET analysis_eligible = 1, exclusion_reason = NULL,
               exclusion_source = NULL
           WHERE exclusion_reason = ?""", (REASON_SPAM_CONFIRMED,))
    rows = conn.execute(
        """SELECT s.comment_id, s.prompt_version, s.model, s.verdict
           FROM comment_screens s
           WHERE s.model = ?
           ORDER BY s.comment_id, s.screened_at DESC, s.prompt_version DESC""",
        (SPAM_CONFIRMED_MODEL,)).fetchall()
    latest: dict[str, tuple[str, str, str]] = {}
    for r in rows:
        latest.setdefault(r["comment_id"], (r["prompt_version"], r["model"], r["verdict"]))

    n = 0
    for cid, (pv, model, verdict) in latest.items():
        if verdict not in SPAM_CONFIRMED_VERDICTS:
            continue
        n += conn.execute(
            """UPDATE comments SET analysis_eligible = 0, exclusion_reason = ?,
                   exclusion_source = ?
               WHERE comment_id = ? AND exclusion_reason IS NULL""",
            (REASON_SPAM_CONFIRMED, f"{SCREEN_SOURCE_PREFIX}{pv}/{model}", cid)).rowcount
    return n
