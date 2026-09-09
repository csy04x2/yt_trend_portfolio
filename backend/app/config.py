""".env 로드와 설정 읽기.

python-dotenv를 쓰지 않는다. 프로토타입의 의존성을 0으로 유지하는 편이
팀원이 받아서 바로 돌려보는 데 유리하다. 필요한 문법은 KEY=VALUE 한 줄뿐이다.

우선순위는 환경변수 > .env 다. 이미 셸에 넣어둔 값을 .env가 덮어쓰지 않는다.
"""

from __future__ import annotations

import os
import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_ROOT / ".env"

DEFAULTS = {
    "DB_PATH": "./data/yt_trend.db",
    "MAX_VIDEOS_PER_CHANNEL": "50",
    "MAX_COMMENTS_PER_VIDEO": "2000",
    "YOUTUBE_DAILY_QUOTA": "10000",
}


def load_env(path: pathlib.Path = ENV_FILE) -> list[str]:
    """.env를 os.environ에 얹는다. 이미 있는 키는 건드리지 않는다.

    돌려주는 값은 이번에 채운 키 목록 — 무엇이 어디서 왔는지 보여주려고.
    """
    filled: list[str] = []
    if not path.exists():
        return filled
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            filled.append(key)
    return filled


def get(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, DEFAULTS.get(key, default))


def require(key: str, how: str) -> str:
    """없으면 무엇을 해야 하는지 알려주고 죽는다."""
    value = os.environ.get(key)
    if not value:
        raise SystemExit(
            f"{key} 가 없다.\n"
            f"  {how}\n"
            f"  넣는 곳: {ENV_FILE}  (.env.example 복사해서 쓴다)\n"
            f"  또는 셸에서: $env:{key}=\"...\"   /   export {key}=..."
        )
    return value


def describe() -> str:
    """현재 설정 상태 한 줄 요약. 키 값은 절대 찍지 않는다."""
    marks = []
    for key in ("YOUTUBE_API_KEY", "ANTHROPIC_API_KEY"):
        marks.append(f"{key}={'설정됨' if os.environ.get(key) else '없음'}")
    marks.append(f"DB_PATH={get('DB_PATH')}")
    return " · ".join(marks)
