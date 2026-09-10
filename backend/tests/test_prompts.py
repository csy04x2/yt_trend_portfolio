"""프롬프트 레지스트리와 Claude 래퍼의 순수 부분.

API 키도 anthropic 패키지도 없이 도는 테스트다. 실제 호출을 하는 부분은
여기서 검증하지 않는다 — 그건 키를 붙인 뒤 `label --limit 20` 으로 한다.
"""

import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients import claude  # noqa: E402
from app.prompts import registry as R  # noqa: E402


# --------------------------------------------------------------------------
# 파일이 곧 프롬프트다
# --------------------------------------------------------------------------

def test_every_prompt_loads():
    prompts = R.all_prompts()
    assert prompts, "app/prompts/ 에 프롬프트가 하나도 없다"
    for name, p in prompts.items():
        assert p.version, f"{name}: 버전이 비었다"
        assert len(p.system) > 200, f"{name}: 본문이 너무 짧다 ({len(p.system)}자)"


def test_prompt_used_for_live_labels_exists():
    """DB 에 쌓인 라벨의 버전은 저장소에 원문이 있어야 한다.

    실제로 없었다 — topics-v1 로 300편이 라벨돼 있는데 그 원문이 대화
    기록 안에만 있었다. 그 라벨은 아무도 재현할 수 없는 상태였다.
    """
    known = set()
    for p in R.all_prompts().values():
        known.add(p.version)
        known |= p.history
    # v1 은 이제 comment_label 의 옛 버전이다. 파일은 v2 지만 이력에 남아
    # 있으므로 682건은 여전히 재현 가능한 것으로 잡혀야 한다.
    for v in ("v1", "v2", "topics-v1"):
        assert v in known, f"'{v}' 로 쌓인 라벨의 프롬프트 파일이 없다"


def test_get_rejects_version_mismatch():
    try:
        R.get("comment_label", version="v99")
    except R.PromptError as e:
        assert "v99" in str(e)
        return
    raise AssertionError("파일과 다른 버전을 조용히 돌려줬다")


def test_get_unknown_name_lists_what_exists():
    try:
        R.get("없는프롬프트")
    except R.PromptError as e:
        assert "comment_label" in str(e), e
        return
    raise AssertionError("없는 프롬프트가 통과했다")


def test_system_is_the_same_text_the_offline_path_sends():
    """오프라인에서 다듬은 프롬프트와 API 가 보내는 프롬프트가 달라지면
    오프라인에서 잰 정확도가 아무 의미가 없다."""
    p = R.get("comment_label")
    assert p.system in p.full_text
    assert "판단 기준" in p.system or "감성" in p.system


# --------------------------------------------------------------------------
# 출력 검증
# --------------------------------------------------------------------------

def test_check_accepts_good_output():
    p = R.get("comment_label")
    ok = {"results": [{"idx": 1, "sentiment": "positive",
                       "confidence": 0.9, "topics": ["T8"]}]}
    assert R.check(p, ok) == []


def test_check_collects_every_problem_at_once():
    p = R.get("comment_label")
    bad = {"results": [{"idx": "1", "sentiment": "great",
                        "confidence": 3, "topics": []}]}
    msgs = " / ".join(R.check(p, bad))
    for expect in ("idx", "sentiment", "confidence", "topics"):
        assert expect in msgs, f"{expect} 를 못 잡았다: {msgs}"


def test_check_rejects_missing_required():
    assert R.check(R.get("comment_label"), {}), "필수 항목 누락이 통과했다"


def test_check_rejects_boolean_as_number():
    p = R.get("conclusion_phrase")
    assert R.check(p, {"text": True}), "boolean 이 문자열로 통과했다"


def test_check_rejects_empty_conclusion():
    assert R.check(R.get("conclusion_phrase"), {"text": ""})


def test_check_skips_when_no_schema():
    p = R.load(R.DIR / "comment_label.md")
    stripped = R.Prompt(p.name, p.version, p.stage, p.system, None, p.path)
    assert R.check(stripped, {"아무거나": 1}) == []


# --------------------------------------------------------------------------
# DB 대조 — 재현 가능성의 마지막 방어선
# --------------------------------------------------------------------------

def _mem_db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE comment_labels (comment_id TEXT, prompt_version TEXT,
                 model TEXT)""")
    return c


def test_check_against_db_flags_unknown_version():
    c = _mem_db()
    c.execute("INSERT INTO comment_labels VALUES ('c1','유령-v9','claude-sonnet-5')")
    problems = R.check_against_db(c)
    assert any("유령-v9" in m for m in problems), problems


def test_check_against_db_ignores_rule_models():
    """rules.py 와 segments.py 는 코드가 곧 원문이다. 프롬프트 파일이 없는 게 정상."""
    c = _mem_db()
    c.execute("INSERT INTO comment_labels VALUES ('c1','rules-v1','rule')")
    c.execute("INSERT INTO comment_labels VALUES ('c2','seg-v1','playlist')")
    assert R.check_against_db(c) == []


# --------------------------------------------------------------------------
# 응답에서 JSON 꺼내기
# --------------------------------------------------------------------------

def test_extract_json_plain():
    assert claude.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_with_chatter():
    got = claude.extract_json('판정했습니다.\n```json\n{"a": 1}\n```\n확인해 주세요')
    assert got == {"a": 1}


def test_extract_json_survives_braces_inside_strings():
    """댓글 원문에 중괄호가 들어 있으면 세는 것만으로는 잘린다."""
    got = claude.extract_json('{"t": "여기 } 닫는 괄호", "n": 2}')
    assert got == {"t": "여기 } 닫는 괄호", "n": 2}


def test_extract_json_raises_when_absent():
    try:
        claude.extract_json("죄송하지만 판정할 수 없습니다.")
    except claude.BadOutput:
        return
    raise AssertionError("JSON 이 없는데 통과했다")


# --------------------------------------------------------------------------
# 비용
# --------------------------------------------------------------------------

def test_usage_returns_none_for_unpriced_model():
    """틀린 단가로 계산한 금액이 없는 금액보다 나쁘다."""
    u = claude.Usage(calls=1, input_tokens=1000, output_tokens=500)
    assert u.cost("아직-없는-모델") is None
    assert "단가 미등록" in u.describe("아직-없는-모델")


def test_usage_prices_known_model():
    u = claude.Usage(calls=1, input_tokens=1_000_000, output_tokens=0)
    assert abs(u.cost("claude-opus-5") - 5.0) < 1e-9


def test_usage_cache_read_is_cheaper():
    a = claude.Usage(input_tokens=1_000_000)
    b = claude.Usage(cache_read=1_000_000)
    assert b.cost("claude-opus-5") < a.cost("claude-opus-5") / 5


# --------------------------------------------------------------------------
# 패키지가 없어도 모듈은 살아 있어야 한다
# --------------------------------------------------------------------------

def test_client_constructs_without_sdk():
    c = claude.ClaudeClient(api_key="x")
    assert c.model == claude.DEFAULT_MODEL


def test_cache_key_changes_with_model_and_version():
    p = R.get("comment_label")
    a = claude.ClaudeClient(api_key="x", model="m1")
    b = claude.ClaudeClient(api_key="x", model="m2")
    assert a._key(p, "같은 입력") != b._key(p, "같은 입력"), \
        "모델이 달라도 캐시 키가 같으면 다른 모델의 결과를 돌려준다"
    assert a._key(p, "입력1") != a._key(p, "입력2")


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
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"  ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)
