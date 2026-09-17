"""프롬프트 레지스트리 — 이름 → (버전, 시스템 프롬프트, 출력 스키마).

**프롬프트는 코드가 아니라 파일이다.** 해석 테이블은 전부 (대상,
prompt_version, model) 을 키로 갖는데, 그 `prompt_version` 이 가리키는 원문이
저장소에 없으면 라벨을 재현할 수 없다. 실제로 그 일이 있었다 — DB 에
`topics-v1` 으로 영상 300편이 라벨돼 있는데 그 v1 의 원문은 대화 기록 안에만
있었다. 팀원이 라벨을 검수하려 해도 무슨 지시로 붙은 것인지 볼 수가 없었다.

## 오프라인 경로와 API 경로는 같은 문자열을 쓴다

`Prompt.system` 은 파일의 헤더(제목·버전·이력) 아래 **전문**이다. 오프라인
경로(`offline_llm.export_batch`)가 파일 전체를 붙여 내보내는 것과 같은 내용이
API 의 system 으로 간다.

이게 이 모듈에서 가장 중요한 성질이다. 오프라인에서 프롬프트를 다듬어 놓고
API 에는 다른 문자열을 보내면, 오프라인에서 잰 정확도가 아무 의미가 없어진다.
그래서 두 경로가 같은 파일을 읽게 묶어 둔다.

## 파일 형식

    # <이름>

    - 버전: <prompt_version — DB 에 그대로 들어가는 값>
    - 단계: <파이프라인 단계>
    - 이력: ...

    ---

    ## 시스템 지시
    ...
    ## 출력 형식
    ```json ... ```      ← 사람이 읽는 예시
    ## 출력 스키마
    ```json ... ```      ← 검증용 JSON Schema. 없으면 검증을 건너뛴다

버전을 올릴 때는 파일을 새로 만들지 않고 같은 파일의 `버전` 을 바꾸고 이력에
줄을 더한다. 옛 버전의 원문이 필요하면 git 이 갖고 있다.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

DIR = pathlib.Path(__file__).resolve().parent

# 프롬프트가 아니라 코드가 판정한 것들. 파일이 없는 게 정상이다.
RULE_MODELS = frozenset({"rule", "playlist"})


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    stage: str
    system: str          # 헤더 아래 전문. 오프라인·API 가 함께 쓴다
    schema: dict | None  # JSON Schema. 없으면 None
    path: pathlib.Path
    # 이 파일이 지나온 옛 버전들. 프롬프트를 고치면 버전이 오르는데, 그 순간
    # DB 에 쌓여 있던 옛 버전 라벨이 「원문 없는 라벨」로 잡히면 안 된다.
    # 옛 원문은 git 이 갖고 있고, 이력 줄이 그 버전이 이 파일의 조상임을 밝힌다.
    history: frozenset = frozenset()

    @property
    def full_text(self) -> str:
        """파일 전문. 오프라인 경로가 묶음 파일 앞에 붙이는 그것."""
        return self.path.read_text(encoding="utf-8")


class PromptError(LookupError):
    pass


VERSION_TOKEN = re.compile(r"\b(?:[a-z]+-)?v\d+\b")


def _history(head: str) -> frozenset:
    """이력 줄에 적힌 모든 버전 토큰. 현재 버전도 포함된다."""
    m = re.search(r"^-\s*이력\s*:(.*?)(?=^-\s|\Z)", head, re.M | re.S)
    return frozenset(t.group(0) for t in VERSION_TOKEN.finditer(m.group(1))) if m else frozenset()


def _field(head: str, key: str) -> str:
    m = re.search(rf"^-\s*{key}\s*:\s*(.+)$", head, re.M)
    return m.group(1).strip() if m else ""


def _fenced_json(body: str, heading: str) -> dict | None:
    """`## <heading>` 아래 첫 ```json 블록을 읽는다."""
    m = re.search(rf"^##\s*{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)",
                  body, re.M | re.S)
    if not m:
        return None
    block = re.search(r"```json\s*(.*?)```", m.group(1), re.S)
    if not block:
        return None
    try:
        return json.loads(block.group(1))
    except json.JSONDecodeError as e:
        raise PromptError(f"'{heading}' 의 JSON 블록을 읽을 수 없다: {e}") from e


def load(path: pathlib.Path) -> Prompt:
    text = path.read_text(encoding="utf-8")
    # 헤더(메타)와 본문을 첫 번째 --- 로 가른다
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        raise PromptError(f"{path.name}: 헤더와 본문을 가르는 '---' 가 없다")
    head, body = parts[0], parts[1].strip()

    version = _field(head, "버전")
    if not version:
        raise PromptError(f"{path.name}: '- 버전:' 줄이 없다 — "
                          f"DB 의 prompt_version 과 맞출 값이라 필수다")
    return Prompt(
        name=path.stem,
        version=version,
        stage=_field(head, "단계"),
        system=body,
        schema=_fenced_json(body, "출력 스키마"),
        path=path,
        history=_history(head),
    )


def all_prompts() -> dict[str, Prompt]:
    return {p.stem: load(p) for p in sorted(DIR.glob("*.md"))}


def get(name: str, version: str | None = None) -> Prompt:
    """이름으로 찾는다. version 을 주면 파일의 버전과 다를 때 막는다.

    조용히 다른 버전을 돌려주면 DB 에 적힌 버전과 실제로 쓴 프롬프트가
    어긋난 채로 라벨이 쌓인다. 그게 이 모듈이 막으려는 바로 그 일이다.
    """
    path = DIR / f"{name}.md"
    if not path.exists():
        have = ", ".join(sorted(p.stem for p in DIR.glob("*.md"))) or "(없음)"
        raise PromptError(f"프롬프트 '{name}' 이 없다. 있는 것: {have}")
    p = load(path)
    if version and p.version != version:
        raise PromptError(
            f"{name}: 요청한 버전 '{version}' 과 파일의 버전 '{p.version}' 이 다르다. "
            f"파일을 되돌리거나, DB 에 쌓인 라벨을 새 버전으로 다시 만들어야 한다"
        )
    return p


def check_against_db(conn) -> list[str]:
    """DB 에 쌓인 prompt_version 이 저장소의 파일과 맞는지 본다.

    맞지 않는 것들을 사람이 읽을 문장으로 돌려준다. 빈 리스트면 전부 맞다.
    재현 가능성을 지키는 마지막 방어선이라 CLI 가 이걸 보여준다.
    """
    files = all_prompts()
    # 현재 버전 + 이력에 적힌 옛 버전. 옛 버전으로 쌓인 라벨은 원문이
    # git 에 있고 이력이 그 사실을 밝히므로 재현 가능한 것으로 본다.
    known = set()
    for p in files.values():
        known.add(p.version)
        known |= p.history
    problems: list[str] = []

    for table, col in (("comment_labels", "prompt_version"),
                       ("comment_screens", "prompt_version"),
                       ("comment_reactions", "prompt_version"),
                       ("video_type_labels", "prompt_version")):
        try:
            rows = conn.execute(
                f"SELECT {col} AS v, model, COUNT(*) AS n FROM {table} GROUP BY 1,2")
        except Exception:
            continue
        for r in rows:
            # 규칙이 붙인 것은 프롬프트가 없는 게 정상이다. rules.py 와
            # segments.py 가 코드로 판정하며, 그 코드가 곧 원문이다.
            if r["model"] in RULE_MODELS:
                continue
            if r["v"] not in known:
                problems.append(
                    f"{table}: 버전 '{r['v']}' ({r['model']}, {r['n']}건) 에 해당하는 "
                    f"프롬프트 파일이 없다 — 이 라벨은 재현할 수 없다"
                )
    return problems


# --------------------------------------------------------------------------
# 출력 검증 — 스키마는 파일 옆에 있고, 검사도 여기서 한다
# --------------------------------------------------------------------------

_TYPES = {
    "object": dict, "array": list, "string": str,
    "number": (int, float), "integer": int, "boolean": bool,
}


def _check(node, schema: dict, path: str, out: list[str]) -> None:
    t = schema.get("type")
    if t and t in _TYPES and not isinstance(node, _TYPES[t]):
        # bool 은 int 의 하위형이라 따로 막는다 — True 가 정수로 통과하면 안 된다
        if not (t in ("number", "integer") and isinstance(node, bool)):
            out.append(f"{path}: {t} 이어야 하는데 {type(node).__name__} 이다")
            return
        out.append(f"{path}: {t} 이어야 하는데 boolean 이다")
        return

    if "enum" in schema and node not in schema["enum"]:
        out.append(f"{path}: {node!r} 는 허용값이 아니다 (허용: {schema['enum']})")

    if isinstance(node, dict):
        for k in schema.get("required", []):
            if k not in node:
                out.append(f"{path}: 필수 항목 '{k}' 이 없다")
        if len(node) < schema.get("minProperties", 0):
            out.append(f"{path}: 항목이 {len(node)}개뿐이다 "
                       f"(최소 {schema['minProperties']}개)")
        for k, sub in (schema.get("properties") or {}).items():
            if k in node:
                _check(node[k], sub, f"{path}.{k}" if path else k, out)

    elif isinstance(node, list):
        if len(node) < schema.get("minItems", 0):
            out.append(f"{path}: {len(node)}개뿐이다 (최소 {schema['minItems']}개)")
        item = schema.get("items")
        if item:
            for i, v in enumerate(node):
                _check(v, item, f"{path}[{i}]", out)

    elif isinstance(node, str):
        if len(node) < schema.get("minLength", 0):
            out.append(f"{path}: 비었다")

    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            out.append(f"{path}: {node} 가 최솟값 {schema['minimum']} 보다 작다")
        if "maximum" in schema and node > schema["maximum"]:
            out.append(f"{path}: {node} 가 최댓값 {schema['maximum']} 보다 크다")


def check(prompt: Prompt, data) -> list[str]:
    """출력이 프롬프트의 스키마에 맞는지. 어긋난 것들을 문장으로 돌려준다.

    `jsonschema` 를 쓰지 않는다. 의존성 하나를 아끼려는 게 아니라, 여기서
    필요한 검사가 좁고(형·필수·허용값·개수) 그 이상을 하면 틀린 출력을
    "스키마 위반"이라는 이름으로 뭉뚱그리게 되기 때문이다. 무엇이 어떻게
    어긋났는지가 프롬프트를 고치는 재료다.

    번호 대조(빠진 idx·없는 idx)는 여기서 하지 않는다 — 그건 스키마가 아니라
    입력과의 관계라 `offline_llm.validate_result` 와 `classify_videos.validate`
    가 맡는다.
    """
    if not prompt.schema:
        return []
    out: list[str] = []
    _check(data, prompt.schema, "", out)
    return out
