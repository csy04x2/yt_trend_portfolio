"""댓글 참여의 성격 — 호응이냐 논쟁이냐.

댓글을 다는 행위 자체는 영상에 대한 긍정적 신호로 볼 수 있다. 그런데
논쟁이 붙어서 댓글이 많이 달린 경우도 똑같이 댓글율을 올린다. 댓글율
하나로는 둘을 못 가른다.

실제로 이 저장소의 데이터가 그렇다. 같은 채널의 두 영상에서 토론 영상의
댓글율이 리뷰 영상의 절반인데, 댓글의 성격은 정반대다. 숫자가 낮은 쪽이
"반응이 약하다"는 뜻이 아니다.

그래서 세 값으로 나눈다:

    approval       긍정 ÷ (긍정 + 부정)              0 = 전부 부정, 1 = 전부 긍정
    contention     2 × min(긍정, 부정) ÷ (긍정 + 부정)  0 = 한쪽 쏠림, 1 = 완전 반반
    labeled_ratio  라벨된 댓글 ÷ 그 영상의 분석 대상 댓글  위 두 값을 얼마나 믿을지

approval 과 contention 은 같은 분포를 다른 각도에서 본다. approval 만으로는
0.5 가 "반반으로 갈렸다"인지 "애매하다"인지 알 수 없고, contention 만으로는
쏠린 방향이 칭찬인지 비난인지 알 수 없다. 둘을 같이 읽어야 한다.

**neutral 은 approval·contention 의 분모에서 뺀다.** "잘 봤습니다" 와
"몇 분에 나오는 곡 제목이 뭔가요" 를 같은 축에 놓으면 호응도 논쟁도 아닌
댓글이 두 값을 다 0.5 쪽으로 끌어당긴다. 대신 몇 건이 neutral 이었는지는
그대로 저장해 둔다 — 나중에 "이 영상은 정보성 질문이 많다"를 말할 재료다.

**왜 정규화(2단계)가 아니라 별도 모듈인가.** 이 계산에는 5단계가 내는
감성 라벨(`comment_labels`)이 필요하다. 2단계는 5단계보다 먼저 돈다.
정규화 안에서 라벨을 읽으면 파이프라인 의존 방향이 거꾸로 뒤집힌다.
라벨이 필요 없는 `comment_rate_multiple` 만 정규화에 두고, 라벨을 읽는
부분은 여기로 뺐다.

표본이 모자라면 값을 내지 않는다 — `view_multiple` 과 같은 규칙이다.
긍·부정 라벨 세 건으로 낸 approval 은 0, 0.33, 0.67, 1 네 값밖에 못 갖는데
소수점 두 자리로 찍히면 정밀한 측정처럼 보인다. 그 착시가 값이 비는 것보다
나쁘다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

POSITIVE = "positive"
NEGATIVE = "negative"
NEUTRAL = "neutral"


@dataclass
class EngagementConfig:
    # 긍정+부정이 이보다 적으면 approval·contention 을 내지 않는다.
    # neutral 은 여기 안 센다 — 분모에 안 들어가는 라벨이 표본 수를
    # 채워주면 안 된다.
    min_polar: int = 10


DEFAULT = EngagementConfig()


def compute(
    video_id: str,
    counts: dict[str, int],
    collected_comments: int,
    cfg: EngagementConfig = DEFAULT,
) -> dict:
    """영상 하나의 참여 성격. 순수 함수 — DB 를 모른다.

    counts 는 {'positive': n, 'negative': n, 'neutral': n} 꼴.
    collected_comments 는 그 영상에서 받아둔 댓글 중 분석 대상(analysis_eligible=1)의
    수 (라벨 여부 무관). 채널 자신의 댓글·잘못 들어온 데이터·확정 스팸은 raw 에는
    남지만 시청자 반응의 분모가 아니다 (checkpoint H3, docs/design/comment-eligibility.md).
    """
    positive = counts.get(POSITIVE, 0)
    negative = counts.get(NEGATIVE, 0)
    neutral = counts.get(NEUTRAL, 0)
    labeled = positive + negative + neutral
    polar = positive + negative

    # 라벨을 몇 건이나 봤는지는 값을 못 내는 경우에도 남긴다.
    # "표본이 모자라다"와 "댓글 자체가 없다"는 다른 상황이다.
    labeled_ratio = (labeled / collected_comments) if collected_comments else None

    out = {
        "video_id": video_id,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "approval": None,
        "contention": None,
        "labeled_ratio": labeled_ratio,
        "basis": "",
    }

    if labeled == 0:
        out["basis"] = (
            f"라벨된 댓글이 없다 (분석 대상 댓글 {collected_comments}건) — "
            f"먼저 export-batch · import-batch 로 감성 라벨을 채운다"
        )
        return out

    if polar < cfg.min_polar:
        out["basis"] = (
            f"긍·부정 라벨 {polar}건 (최소 {cfg.min_polar}건 필요). "
            f"라벨 {labeled}건 중 {neutral}건이 neutral 이라 분모에서 빠졌다"
        )
        return out

    out["approval"] = positive / polar
    out["contention"] = 2 * min(positive, negative) / polar
    out["basis"] = (
        f"긍정 {positive} · 부정 {negative} (neutral {neutral}건은 분모에서 제외) · "
        f"라벨 {labeled}/{collected_comments}건"
    )
    return out


def read_label_counts(conn, prompt_version: str, model: str) -> dict[str, dict[str, int]]:
    """{video_id: {sentiment: n}}. 한 (프롬프트 버전, 모델) 조합만 읽는다.

    버전을 섞으면 같은 댓글이 두 번 세어진다.
    """
    rows = conn.execute(
        """SELECT c.video_id AS video_id, l.sentiment AS sentiment, COUNT(*) AS n
           FROM comment_labels l
           JOIN comments c ON c.comment_id = l.comment_id
           WHERE l.prompt_version = ? AND l.model = ?
             AND c.analysis_eligible = 1
           GROUP BY c.video_id, l.sentiment""",
        (prompt_version, model),
    )
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["video_id"], {})[r["sentiment"]] = r["n"]
    return out


def label_versions(conn) -> list[tuple[str, str]]:
    """comment_labels 에 실제로 들어 있는 (프롬프트 버전, 모델) 조합."""
    return [
        (r["prompt_version"], r["model"])
        for r in conn.execute(
            """SELECT prompt_version, model FROM comment_labels
               GROUP BY prompt_version, model
               ORDER BY MAX(labeled_at) DESC"""
        )
    ]


# --------------------------------------------------------------------------
# DB 연결부
# --------------------------------------------------------------------------

def run(
    conn,
    run_id: str,
    prompt_version: str | None = None,
    model: str | None = None,
    cfg: EngagementConfig = DEFAULT,
) -> list[dict]:
    """comment_labels 를 영상 단위로 접어 comment_engagement 를 채운다.

    prompt_version·model 을 주지 않으면 DB 에 있는 조합을 전부 돈다.
    한 조합의 결과는 다른 조합의 결과와 섞이지 않는다 — PK 가 그것을 보장한다.

    댓글을 한 건이라도 받아둔 영상은 전부 대상이다. 라벨이 하나도 없는
    영상도 행을 남긴다 — "왜 값이 없는지"를 리포트가 말할 수 있어야 한다.
    """
    if prompt_version and model:
        versions = [(prompt_version, model)]
    else:
        versions = label_versions(conn)
    if not versions:
        return []

    collected = {
        r["video_id"]: r["n"]
        for r in conn.execute(
            "SELECT video_id, SUM(analysis_eligible = 1) AS n FROM comments GROUP BY video_id"
        )
    }
    if not collected:
        return []

    titles = {
        r["video_id"]: r["title"]
        for r in conn.execute("SELECT video_id, title FROM videos")
    }

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out: list[dict] = []
    for pv, mdl in versions:
        counts = read_label_counts(conn, pv, mdl)
        for video_id, n_comments in collected.items():
            e = compute(video_id, counts.get(video_id, {}), n_comments, cfg)
            conn.execute(
                """INSERT INTO comment_engagement (video_id, run_id, prompt_version,
                       model, positive, negative, neutral, approval, contention,
                       labeled_ratio, basis, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(video_id, run_id, prompt_version, model) DO UPDATE SET
                       positive=excluded.positive, negative=excluded.negative,
                       neutral=excluded.neutral, approval=excluded.approval,
                       contention=excluded.contention,
                       labeled_ratio=excluded.labeled_ratio,
                       basis=excluded.basis, computed_at=excluded.computed_at""",
                (video_id, run_id, pv, mdl, e["positive"], e["negative"],
                 e["neutral"], e["approval"], e["contention"],
                 e["labeled_ratio"], e["basis"], now),
            )
            e["prompt_version"] = pv
            e["model"] = mdl
            e["title"] = titles.get(video_id, "(제목 없음)")
            e["comment_count_collected"] = n_comments
            out.append(e)
    return out
