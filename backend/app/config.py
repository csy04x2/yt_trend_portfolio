""".env 로드와 설정 읽기.

python-dotenv를 쓰지 않는다. 프로토타입의 의존성을 0으로 유지하는 편이
팀원이 받아서 바로 돌려보는 데 유리하다. 필요한 문법은 KEY=VALUE 한 줄뿐이다.

우선순위는 환경변수 > .env 다. 이미 셸에 넣어둔 값을 .env가 덮어쓰지 않는다.
"""

from __future__ import annotations

import os
import pathlib
import sys

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_ROOT / ".env"


def setup_console() -> None:
    """윈도우 콘솔에서 출력이 깨지지 않게 한다.

    한국어 윈도우의 기본 콘솔 코드페이지는 cp949라, 리포트에 쓰는 em-dash(—)나
    일부 기호를 못 찍고 UnicodeEncodeError로 프로그램이 죽는다. 계산은 멀쩡한데
    출력에서 죽는 것이라 원인을 찾기 어렵다.

    stdout/stderr를 UTF-8로 바꾸고, 그래도 못 찍는 글자는 errors='replace'로
    넘긴다 — 글자 하나 때문에 실행이 실패하는 것보다 낫다. 터미널이 UTF-8을
    지원하지 않으면 재설정 자체가 실패할 수 있으므로 조용히 넘어간다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

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

    # utf-8-sig 로 읽는 이유: 윈도우 메모장과 PowerShell 의 Set-Content 는
    # UTF-8 저장 시 파일 앞에 BOM(EF BB BF)을 붙인다. 그냥 utf-8 로 읽으면
    # 첫 줄의 키 이름이 "﻿YOUTUBE_API_KEY" 가 되어 아무도 못 읽는다.
    # 파일은 멀쩡해 보이고 값도 들어 있는데 "키가 없다"고만 나와서 원인을
    # 찾기 어렵다. utf-8-sig 는 BOM 이 없어도 그대로 동작한다.
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lstrip("﻿")
        value = value.strip().strip('"').strip("'")
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
