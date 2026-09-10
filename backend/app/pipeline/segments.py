"""코너(시리즈) 축 — 채널의 재생목록에서 읽는다.

**추측하지 않는다.** 코너는 채널이 스스로 선언한 것이고 재생목록이 그
선언이다. 제목 정규식으로 뽑으려 했더니 14F 에서 5개를 찾았는데 재생목록에는
20개가 넘게 있었다 — 「월드클로즈업」, 「아이돈케어」, 「본스토리」는 제목에
아예 안 나타난다. 이름도 다르다. 제목에서는 "경제 이슈"로 보이는데 채널이
부르는 이름은 「경제한쌈」이다.

주제(topic) 축이 LLM 판단인 것과 대비된다. 이 저장소는 규칙으로 확실히 알 수
있는 것을 LLM 에 묻지 않는다 — 댓글 필터에서 정한 원칙과 같다.

## 재생목록이 전부 코너는 아니다

세 종류가 섞인다.

- **서랍** — 「14F's PICKㅣDaily」 1,943편, 「이슈픽!」 1,725편. 채널 영상의
  30% 를 담는다. 코너가 아니라 보관함이다.
- **끝난 기획** — 「2022 베이징 겨울 올림픽」. 한때의 묶음이다.
- **진짜 코너** — 돈슐랭, 10분 토론처럼 계속 나오는 것.

서랍은 비율로 거른다. 끝난 기획은 우리가 받은 영상과 겹치지 않으면 자연히
빠지므로 따로 규칙을 두지 않았다 — 임계값을 늘리면 그만큼 틀릴 여지도 는다.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass


@dataclass
class SegmentConfig:
    # 채널 영상의 이 비율 이상을 담으면 코너가 아니라 서랍이다
    drawer_ratio: float = 0.25
    # 이보다 적게 담은 재생목록은 코너로 치지 않는다 (일회성 묶음)
    min_items: int = 5
    # **우리가 받은 영상** 중 이 비율 이상을 한 재생목록이 덮으면 서랍이다.
    # drawer_ratio 는 채널 전체가 분모라 큰 채널에서 기준선이 커져 새어 나간다
    # — drop_broad() 의 설명을 볼 것.
    sample_ratio: float = 0.4


DEFAULT = SegmentConfig()


def clean_name(title: str) -> str:
    """「돈슐랭ㅣ알고 먹으면 더 맛있는 이야기」 → 「돈슐랭」.

    재생목록 제목은 대개 '이름ㅣ설명' 꼴이다. 표에 쓸 이름만 남긴다.
    """
    name = re.split(r"[ㅣ|｜]", title)[0].strip()
    return name or title.strip()


def pick_segments(playlists: list[dict], channel_video_count: int,
                  cfg: SegmentConfig = DEFAULT) -> dict[str, str]:
    """재생목록 목록에서 코너만 골라 {playlist_id: 이름} 으로.

    playlists 각 항목은 {"id", "title", "item_count"}.
    """
    out = {}
    for p in playlists:
        n = p["item_count"]
        if n < cfg.min_items:
            continue
        if channel_video_count and n / channel_video_count >= cfg.drawer_ratio:
            continue                      # 서랍
        out[p["id"]] = clean_name(p["title"])
    return out


def drop_broad(membership: dict[str, list[str]], segments: dict[str, str],
               sample_size: int, cfg: SegmentConfig = DEFAULT) -> dict[str, str]:
    """우리가 받은 영상의 너무 많은 부분을 덮는 재생목록을 코너에서 뺀다.

    `pick_segments` 의 비율 검사만으로는 큰 채널에서 새어 나간다. 그 검사는
    **채널 전체 편수**를 기준으로 하는데, 침착맨은 영상이 7,698편이라 서랍
    기준선이 1,925편이 된다. 「침착맨 Shorts」 는 그보다 작아서 코너로
    통과했고, 우리가 받은 300편 중 174편(58%)을 혼자 덮었다. 「2026년 침착맨
    정주행」 도 64편을 덮었다. 둘 다 코너가 아니라 형식 묶음과 연도 묶음이다.

    채널이 클수록 기준선이 커지는 것이 문제의 뿌리다. 그래서 **우리 표본을
    기준으로 한 번 더 본다** — 받은 영상의 절반 가까이를 한 재생목록이 덮으면
    그것은 유형이 아니다. 무엇을 가르지도 못한다.

    이 검사는 소속을 받아온 **뒤에만** 할 수 있다. 열거 비용은 이미 치른
    다음이지만, 틀린 축으로 리포트를 내는 것보다는 낫다.

    또 하나: 「침착맨 Shorts」 는 길이 축을, 「2026년 정주행」 은 시간 축을
    다시 말한다. 우리가 이미 가진 축을 코너가 흉내내면 두 축이 같은 말을
    두 번 하게 된다.
    """
    if not sample_size:
        return segments
    covered: dict[str, int] = {}
    for pls in membership.values():
        for pid in pls:
            if pid in segments:
                covered[pid] = covered.get(pid, 0) + 1
    return {pid: name for pid, name in segments.items()
            if covered.get(pid, 0) / sample_size < cfg.sample_ratio}


def assign(membership: dict[str, list[str]], segments: dict[str, str],
           sizes: dict[str, int]) -> dict[str, str]:
    """영상마다 코너 하나를 정한다. {video_id: playlist_id}

    여러 코너에 들면 **가장 작은 것**을 고른다 — 작을수록 구체적이다.
    14F 에서는 중복이 0건이었지만, 규칙 없이 두면 채널이 바뀔 때 임의로
    갈린다.
    """
    picked = {}
    for vid, pls in membership.items():
        cand = [p for p in pls if p in segments]
        if cand:
            picked[vid] = min(cand, key=lambda p: sizes.get(p, 1 << 30))
    return picked


def fetch(yt, channel_id: str, log=print) -> tuple[list[dict], dict[str, list[str]]]:
    """재생목록과 소속 영상을 받는다.

    영상이 어느 재생목록에 속하는지 되묻는 API 가 없어서 재생목록을 열거하는
    수밖에 없다. 서랍은 건너뛰어 호출을 아낀다 — 14F 기준 전체를 다 받으면
    164유닛, 서랍을 빼면 90유닛쯤이다.
    """
    playlists = yt.list_playlists(channel_id)
    log(f"[재생목록] {len(playlists)}개")

    ch = yt.resolve_channel(f"https://www.youtube.com/channel/{channel_id}")
    total = ch.get("video_count") or 0
    segs = pick_segments(playlists, total, DEFAULT)
    log(f"[코너] {len(segs)}개 (채널 영상 {total:,}편 기준, 서랍·소규모 제외)")

    membership: dict[str, list[str]] = {}
    for p in playlists:
        if p["id"] not in segs:
            continue                       # 서랍은 받지 않는다
        for vid in yt.iter_playlist_video_ids(p["id"]):
            membership.setdefault(vid, []).append(p["id"])
    return playlists, membership


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
