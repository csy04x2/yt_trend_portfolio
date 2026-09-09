"""규칙 필터 채점기.

루프가 "나아졌는가"를 판단하려면 숫자가 하나 있어야 한다. 이 파일이 그 숫자를
만든다. 사람이 라벨한 표본에 규칙을 돌려 네 가지를 센다.

  오탐 (false_drop)   정상 댓글을 promo/irrelevant로 버렸다  ← 가장 위험
  미탐 (missed)       홍보·선점을 keep으로 통과시켰다        ← 덜 위험 (LLM이 잡음)
  정확도 (accuracy)    기대 verdict와 일치한 비율
  호출량 (llm_batches) LLM으로 보낼 묶음 수                  ← 비용 대리 지표

오탐과 미탐의 무게가 다른 이유: 규칙이 확정 제외한 댓글은 리포트에 영영
나타나지 않는다. 조용히, 복구 불가능하게 사라진다. 반면 통과시킨 것은
다음 단계 LLM이 다시 본다. 그래서 목표는 오탐 0을 우선한다.

  python -m app.eval            사람이 읽는 표
  python -m app.eval --json     기계가 읽는 JSON (훅과 루프가 쓴다)

종료 코드: 목표 달성 0, 미달 1. 루프의 정지 조건이다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.pipeline.rules import DEFAULT_CONFIG, screen_comments  # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "fixtures"

# 규칙이 확정 제외하는 verdict. 여기 잘못 들어가면 복구 불가능하다.
DROPPING = {"promo", "irrelevant"}

# 목표치. 루프는 이 셋을 모두 만족하면 멈춘다.
GOAL = {
    "false_drop": 0,        # 정상 댓글을 하나도 버리지 않는다
    "min_accuracy": 1.0,    # 라벨한 표본을 전부 맞춘다
    "min_samples": 25,      # 표본이 이보다 적으면 목표 달성으로 치지 않는다
}


def load_labeled() -> list[dict]:
    """fixtures/ 아래 _expect가 붙은 댓글을 전부 모은다.

    표본을 늘리려면 같은 형식의 JSON을 fixtures/labeled/ 에 넣으면 된다.
    파일을 늘리는 것이 규칙을 손보는 것보다 대개 먼저다.
    """
    files = [FIXTURES / "sample_comments.json"]
    files += sorted((FIXTURES / "labeled").glob("*.json")) if (FIXTURES / "labeled").exists() else []

    out: list[dict] = []
    for f in files:
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for c in data.get("comments", []):
            if "_expect" in c:
                c = dict(c)
                c["_source"] = f.name
                out.append(c)
    return out


def score(comments: list[dict]) -> dict:
    screens = {s.comment_id: s for s in screen_comments(comments, DEFAULT_CONFIG)}

    false_drop, missed, correct, wrong = [], [], 0, []
    for c in comments:
        got = screens[c["comment_id"]].verdict
        want = c["_expect"]
        if got == want:
            correct += 1
        else:
            wrong.append({
                "comment_id": c["comment_id"],
                "text": c["text"][:60],
                "want": want, "got": got,
                "why": c.get("_why", ""),
                "source": c.get("_source", ""),
            })
            if got in DROPPING and want not in DROPPING:
                false_drop.append(c["comment_id"])
            elif want in DROPPING and got not in DROPPING:
                missed.append(c["comment_id"])

    n = len(comments) or 1
    to_llm = sum(1 for s in screens.values() if s.needs_llm)
    accuracy = correct / n

    result = {
        "samples": len(comments),
        "accuracy": round(accuracy, 4),
        "false_drop": len(false_drop),
        "missed": len(missed),
        "llm_comments": to_llm,
        "llm_batches": -(-to_llm // 20),
        "wrong": wrong,
    }
    result["goal_met"] = bool(
        result["false_drop"] <= GOAL["false_drop"]
        and accuracy >= GOAL["min_accuracy"]
        and result["samples"] >= GOAL["min_samples"]
    )
    return result


def main() -> int:
    from app import config
    config.setup_console()      # cp949 콘솔에서 출력이 깨져 죽는 것을 막는다

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="JSON 한 줄로 출력")
    args = p.parse_args()

    comments = load_labeled()
    if not comments:
        print("라벨된 표본이 없다. fixtures/ 를 확인해라.", file=sys.stderr)
        return 2

    r = score(comments)

    if args.json:
        print(json.dumps({k: v for k, v in r.items() if k != "wrong"}, ensure_ascii=False))
        return 0 if r["goal_met"] else 1

    print(f"표본 {r['samples']}건")
    print(f"  정확도       {r['accuracy']:.1%}")
    print(f"  오탐         {r['false_drop']}  (정상 댓글을 버림 — 목표 {GOAL['false_drop']})")
    print(f"  미탐         {r['missed']}  (홍보·선점을 통과시킴)")
    print(f"  LLM 호출     {r['llm_batches']}묶음 ({r['llm_comments']}건)")
    if r["wrong"]:
        print(f"\n틀린 {len(r['wrong'])}건")
        for w in r["wrong"]:
            mark = "오탐" if w["got"] in DROPPING and w["want"] not in DROPPING else "  "
            print(f"  {mark} [{w['want']} → {w['got']}] {w['text']}")
            if w["why"]:
                print(f"       기대 이유: {w['why']}")
    print(f"\n목표 {'달성' if r['goal_met'] else '미달'}"
          f"  (오탐 0 · 정확도 100% · 표본 {GOAL['min_samples']}건 이상)")
    return 0 if r["goal_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
