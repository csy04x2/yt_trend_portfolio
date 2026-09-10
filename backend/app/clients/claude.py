"""Anthropic API 래퍼 — 구조화 출력, 캐시, 재시도, 프롬프트 버전 주입.

**아직 이 저장소에서 한 번도 호출된 적이 없다.** 지금까지 3단계와 5단계는
오프라인 경로(Claude Code 가 파일을 읽고 판정)로만 돌았다. 이 모듈은 그
경로를 API 로 바꿔 끼우기 위한 것이고, 남은 준비물은 셋뿐이다.

    pip install anthropic
    .env 에 ANTHROPIC_API_KEY=sk-ant-...
    yt-trend label --online

## 오프라인에서 검증한 것과 같은 문자열을 보낸다

`system` 은 `prompts/registry.py` 가 읽은 파일 본문 그대로다. 오프라인 묶음
파일에 붙는 것과 같은 텍스트다. 이게 어긋나면 오프라인에서 잰 정확도가
API 결과를 보장하지 못한다.

## 모델을 바꾸면 결과가 달라진다

해석 테이블의 키가 (대상, prompt_version, **model**) 인 이유가 이것이다.
지금 DB 에 쌓인 라벨 282건의 model 은 `claude-code-offline` — Opus 급이
판정한 것이다. 기본 모델을 Sonnet 으로 두는 것은 댓글 분류가 단순 분류
작업이고 건수가 많아서지만, **처음 붙일 때는 같은 묶음을 두 모델로 돌려
비교해 보라.** 비교 없이 갈아타면 라벨 분포가 왜 변했는지 영원히 모른다.

## 다음 지렛대

Batches API 를 쓰면 같은 호출이 절반 값이다. 댓글 라벨링은 즉시성이 전혀
필요 없는 작업이라 여기에 딱 맞는데, 지금은 넣지 않았다 — 동기 경로가
실제 데이터에서 검증되기 전에 비동기 제출·수거를 얹으면 실패 지점이 둘로
는다. 동기로 한 채널을 끝까지 돌린 다음에 붙인다.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re
import time
from dataclasses import dataclass, field

from app.prompts.registry import Prompt, check

# 댓글 분류는 단순 분류이고 건수가 많다. 위 「모델을 바꾸면」 을 읽을 것.
DEFAULT_MODEL = "claude-sonnet-5"

# 백만 토큰당 달러 (입력, 출력). **확인한 것만 적는다.** 없는 모델은
# 비용을 None 으로 돌려준다 — 틀린 단가로 계산한 금액이 없는 금액보다 나쁘다.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
}

# 재시도할 SDK 예외. 형을 import 하지 않고 이름으로 가른다 — 이 모듈은
# anthropic 이 깔려 있지 않아도 import 되어야 한다.
RETRYABLE = frozenset({
    "OverloadedError", "RateLimitError", "APIConnectionError",
    "APITimeoutError", "InternalServerError",
})


class ClaudeError(RuntimeError):
    pass


class MissingPackage(ClaudeError):
    pass


class Refused(ClaudeError):
    """모델이 판정을 거부했다.

    이건 통신 오류가 아니라 정상 응답이다 — HTTP 200 에 stop_reason 만
    'refusal' 이다. 오류로 안 보고 지나가면 빈 결과가 조용히 저장된다.
    """


class BadOutput(ClaudeError):
    """JSON 이 아니거나 스키마에 맞지 않는다. 재시도해도 같을 수 있다."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cached_hits: int = 0          # 우리 파일 캐시로 아예 호출을 안 한 횟수

    def add(self, u) -> None:
        self.calls += 1
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0

    def cost(self, model: str) -> float | None:
        p = PRICES.get(model)
        if not p:
            return None
        # 캐시 읽기는 입력가의 10%, 캐시 쓰기는 125%.
        return (
            self.input_tokens * p[0]
            + self.cache_read * p[0] * 0.10
            + self.cache_write * p[0] * 1.25
            + self.output_tokens * p[1]
        ) / 1_000_000

    def describe(self, model: str) -> str:
        c = self.cost(model)
        money = f"${c:.4f}" if c is not None else "단가 미등록"
        return (f"호출 {self.calls}회 (캐시 적중 {self.cached_hits}회) · "
                f"입력 {self.input_tokens:,} · 출력 {self.output_tokens:,} · "
                f"캐시 읽기 {self.cache_read:,} · {money}")


def extract_json(text: str):
    """응답에서 JSON 하나를 꺼낸다.

    모델이 울타리를 치거나 앞뒤에 한마디를 붙이는 일이 흔하다. 그때마다
    실패로 처리하면 멀쩡한 판정을 버리게 된다. 다만 문자열 안의 중괄호는
    세지 않는다 — 댓글 원문에 중괄호가 들어 있으면 거기서 잘린다.
    """
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    cands = [f.strip() for f in fenced] or [text.strip()]
    for c in cands:
        start = c.find("{")
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(c[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(c[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise BadOutput("응답에서 JSON 을 찾지 못했다:\n" + text[:400])


@dataclass
class ClaudeClient:
    api_key: str
    model: str = DEFAULT_MODEL
    max_tokens: int = 8000
    max_retries: int = 4
    timeout: float = 600.0
    cache_dir: pathlib.Path | None = None
    usage: Usage = field(default_factory=Usage)
    _sdk: object = None

    def __post_init__(self) -> None:
        if self.cache_dir:
            self.cache_dir = pathlib.Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- SDK 는 필요할 때 들여온다. 패키지가 없어도 이 모듈은 import 된다 --
    def _client(self):
        if self._sdk is None:
            try:
                import anthropic
            except ImportError as e:
                raise MissingPackage(
                    "anthropic 패키지가 없다. `pip install anthropic` 후 다시 실행한다. "
                    "API 없이 돌리려면 export-batch · import-batch 오프라인 경로를 쓴다."
                ) from e
            self._sdk = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._sdk

    # -- 캐시 키는 결과를 바꾸는 것 전부를 담는다 --
    def _key(self, prompt: Prompt, user_text: str) -> str:
        h = hashlib.sha256()
        for part in (self.model, prompt.name, prompt.version, prompt.system, user_text):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()[:32]

    def _cached(self, key: str):
        if not self.cache_dir:
            return None
        f = self.cache_dir / f"{key}.json"
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))["data"]
        except Exception:
            return None      # 깨진 캐시는 없는 것으로 본다

    def _store(self, key: str, prompt: Prompt, data) -> None:
        if not self.cache_dir:
            return
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps({"model": self.model, "prompt": prompt.name,
                        "version": prompt.version, "data": data},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")

    def judge(self, prompt: Prompt, user_text: str, *, use_cache: bool = True):
        """프롬프트 하나로 한 번 판정한다. 검증까지 통과한 dict 를 돌려준다.

        같은 (모델, 프롬프트, 입력) 이면 파일 캐시에서 돌려준다. 프롬프트를
        고치는 동안 같은 묶음을 몇 번씩 돌리게 되는데, 그때마다 돈이 나가면
        프롬프트를 덜 고치게 된다.
        """
        key = self._key(prompt, user_text)
        if use_cache:
            hit = self._cached(key)
            if hit is not None:
                self.usage.cached_hits += 1
                return hit

        msg = self._call(prompt, user_text)
        stop = getattr(msg, "stop_reason", None)

        if stop == "refusal":
            raise Refused(
                f"{prompt.name}({prompt.version}): 모델이 판정을 거부했다. "
                f"이 묶음에 정책에 걸리는 내용이 있는지 사람이 본다"
            )
        if stop == "max_tokens":
            raise BadOutput(
                f"{prompt.name}: 출력이 max_tokens({self.max_tokens}) 에서 잘렸다. "
                f"묶음 크기를 줄여라 — 잘린 JSON 을 살려 쓰면 안 된다"
            )

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = extract_json(text)

        problems = check(prompt, data)
        if problems:
            raise BadOutput("\n  - ".join(
                [f"{prompt.name}({prompt.version}) 출력이 스키마에 안 맞는다:"] + problems))

        self._store(key, prompt, data)
        return data

    def _call(self, prompt: Prompt, user_text: str):
        """재시도. 과부하·속도 제한만 다시 걸고, 나머지는 그대로 올린다."""
        client = self._client()
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                msg = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    # 시스템은 묶음마다 그대로라 캐시가 붙는다. 길이가 캐시
                    # 최소치에 못 미치면 API 가 조용히 무시한다 — 오류가
                    # 아니므로 따로 처리하지 않는다.
                    system=[{"type": "text", "text": prompt.system,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_text}],
                )
                self.usage.add(getattr(msg, "usage", None))
                return msg
            except Exception as e:
                if type(e).__name__ not in RETRYABLE:
                    raise
                last = e
                if attempt == self.max_retries - 1:
                    break
                # 지수 백오프 + 지터. 지터가 없으면 여러 묶음이 한꺼번에
                # 재시도해 같은 순간에 다시 몰린다.
                time.sleep(min(2 ** attempt, 16) * (1 + random.random() * 0.3))
        raise ClaudeError(
            f"{self.max_retries}회 재시도 후에도 실패했다: {type(last).__name__} {last}")


def from_config(config, *, model: str | None = None,
                cache_dir: str | pathlib.Path | None = "./data/cache/claude"):
    """.env 에서 키를 읽어 클라이언트를 만든다. 키가 없으면 여기서 막는다."""
    key = config.require(
        "ANTHROPIC_API_KEY",
        "console.anthropic.com 에서 발급받아 backend/.env 에 넣는다. "
        "키 없이 돌리려면 export-batch · import-batch 오프라인 경로를 쓴다.",
    )
    return ClaudeClient(
        api_key=key,
        model=model or config.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        cache_dir=cache_dir,
    )
