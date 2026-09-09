"""YouTube Data API v3 래퍼.

의존성 없이 표준 라이브러리 urllib만 쓴다. 프로토타입에 SDK를 끌어오면
설치 단계가 하나 늘고, 우리가 쓰는 엔드포인트는 네 개뿐이다.

할당량은 유닛이지 돈이 아니다. 하루 10,000 유닛이고 아래 호출은 전부
1유닛이라, 영상 50개 + 댓글 전부를 받아도 200유닛을 넘기지 않는다.
search.list(100유닛)는 폴백 경로에서만 쓴다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API = "https://www.googleapis.com/youtube/v3/"

# 엔드포인트별 할당량 비용
COST = {"channels": 1, "playlistItems": 1, "videos": 1, "commentThreads": 1, "search": 100}


class QuotaExhausted(RuntimeError):
    """할당량 소진. 여기까지 저장한 것은 그대로 두고 멈춘다."""


class ChannelNotFound(RuntimeError):
    """URL 오류·비공개·삭제. 재시도 대상이 아니다."""


class CommentsDisabled(RuntimeError):
    """댓글이 꺼진 영상. 실패가 아니라 건너뛸 사유다."""


@dataclass
class YouTubeClient:
    api_key: str
    daily_quota: int = 10_000
    units_used: int = 0
    calls: list[str] = field(default_factory=list)

    def _get(self, endpoint: str, **params) -> dict:
        cost = COST.get(endpoint, 1)
        if self.units_used + cost > self.daily_quota * 0.95:
            raise QuotaExhausted(
                f"할당량 95% 도달 ({self.units_used}/{self.daily_quota})"
            )
        params["key"] = self.api_key
        url = API + endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 403 and "quota" in detail.lower():
                raise QuotaExhausted(detail[:300]) from e
            if e.code == 403 and "commentsDisabled" in detail:
                raise CommentsDisabled(detail[:200]) from e
            if e.code == 404:
                raise ChannelNotFound(detail[:200]) from e
            raise
        self.units_used += cost
        self.calls.append(endpoint)
        return body

    # ---------------- 채널 해석 ----------------

    def resolve_channel(self, url: str) -> dict:
        """채널 URL 세 형식을 채널 정보로 바꾼다."""
        part = "snippet,contentDetails,statistics"
        path = urllib.parse.urlparse(url).path.strip("/")
        seg = path.split("/") if path else []

        body = None
        if seg and seg[0].startswith("@"):
            body = self._get("channels", part=part, forHandle=seg[0])
        elif len(seg) >= 2 and seg[0] == "channel":
            body = self._get("channels", part=part, id=seg[1])
        elif len(seg) >= 2 and seg[0] in ("c", "user"):
            body = self._get("channels", part=part, forUsername=seg[1])
            if not body.get("items"):
                # 폴백. 100유닛이라 마지막 수단이다.
                found = self._get("search", part="snippet", q=seg[1],
                                  type="channel", maxResults=1)
                items = found.get("items", [])
                if not items:
                    raise ChannelNotFound(url)
                cid = items[0]["snippet"]["channelId"]
                body = self._get("channels", part=part, id=cid)
        elif url.startswith("UC"):
            body = self._get("channels", part=part, id=url)

        items = (body or {}).get("items", [])
        if not items:
            raise ChannelNotFound(f"채널을 찾을 수 없다: {url}")
        it = items[0]
        return {
            "channel_id": it["id"],
            "title": it["snippet"]["title"],
            "handle": it["snippet"].get("customUrl"),
            "uploads_playlist": it["contentDetails"]["relatedPlaylists"]["uploads"],
            "subscriber_count": int(it["statistics"].get("subscriberCount") or 0) or None,
        }

    # ---------------- 영상 목록 ----------------

    def list_upload_ids(self, uploads_playlist: str, limit: int) -> list[str]:
        ids, token = [], None
        while len(ids) < limit:
            body = self._get("playlistItems", part="contentDetails",
                             playlistId=uploads_playlist, maxResults=50,
                             **({"pageToken": token} if token else {}))
            for it in body.get("items", []):
                ids.append(it["contentDetails"]["videoId"])
            token = body.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def fetch_videos(self, video_ids: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            body = self._get(
                "videos",
                part="snippet,contentDetails,statistics,liveStreamingDetails",
                id=",".join(chunk),
            )
            out.extend(body.get("items", []))
        return out

    # ---------------- 댓글 ----------------

    def iter_comment_pages(self, video_id: str, page_token: str | None = None):
        """commentThreads를 시간순으로 한 페이지씩 내준다.

        페이지 단위로 넘기는 이유는 호출부가 페이지마다 커서를 커밋할 수
        있어야 하기 때문이다. 단계 끝에 한꺼번에 쓰면 중간에 멈췄을 때
        못 받은 구간을 다음 실행이 건너뛴다.
        """
        token = page_token
        while True:
            try:
                body = self._get("commentThreads", part="snippet",
                                 videoId=video_id, order="time", maxResults=100,
                                 textFormat="plainText",
                                 **({"pageToken": token} if token else {}))
            except CommentsDisabled:
                return
            items = []
            for it in body.get("items", []):
                s = it["snippet"]["topLevelComment"]["snippet"]
                items.append({
                    "comment_id": it["snippet"]["topLevelComment"]["id"],
                    "video_id": video_id,
                    "author_channel_id": (s.get("authorChannelId") or {}).get("value"),
                    "author_name": s.get("authorDisplayName"),
                    "text": s.get("textOriginal") or s.get("textDisplay") or "",
                    "published_at": s.get("publishedAt"),
                    "like_count": int(s.get("likeCount") or 0),
                })
            yield items
            token = body.get("nextPageToken")
            if not token:
                return


def classify_live(item: dict) -> tuple[int, str]:
    """라이브·프리미어 판정.

    liveStreamingDetails가 있다는 것만으로 라이브로 보면 안 된다 —
    프리미어로 공개한 일반 영상도 이 필드를 갖는다. 프리미어 공개가 잦은
    한국 채널에서는 정규 콘텐츠가 통째로 분석에서 빠진다.

    지금은 판정하지 않고 근거만 기록한다. 0단계에서 실제 응답 분포를 보고
    규칙을 확정한 뒤 이 함수를 채운다 (결정 문서 3장 미결).
    """
    lsd = item.get("liveStreamingDetails")
    if not lsd:
        return 0, ""
    evidence = json.dumps(
        {k: lsd.get(k) for k in
         ("actualStartTime", "actualEndTime", "scheduledStartTime")},
        ensure_ascii=False,
    )
    # 미확정: 일단 라이브로 표시하지 않고 근거만 남긴다
    return 0, evidence
