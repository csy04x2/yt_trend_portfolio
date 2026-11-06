"""Reaction Phase 3 — 댓글 Reaction·Target AI 판정기.

기준은 사람이 확정한 두 문서다. 이 모듈은 기준을 **만들지 않고 지킨다.**

    docs/reaction-phase1-checkpoint.md          Reaction·Target 정의, H1–H4
    docs/reaction-track-closeout-2026-09-17.md  Final vNext (R9 행동 지향), 재개 결정

프롬프트는 `prompts/comment_reaction.md` 하나다. 감성·주제 라벨링
(`label_comments`) 과 같은 모양으로 두 경로가 **같은 프롬프트, 같은 묶음 본문,
같은 검증기**를 쓴다.

    오프라인   export() → 사람이 Claude Code 에 읽힘 → .result.json → validate_reactions → 저장
    API 경로   batch_body() → client.judge()               → dict         → validate_reactions → 저장

## 검증이 이 모듈의 핵심이다

스키마(형·허용값)는 `registry.check` 가 본다. 여기서는 스키마로 말할 수 없는
**관계 규칙**을 본다. 하나라도 어기면 그 묶음 전체를 버린다 — 일부만 살려
저장하면 「어느 댓글이 빠졌는지」 를 아무도 모르게 된다.

- 없는 코드 (R11, T6, "None" 같은 문자열) → 거부
- Reaction=None 은 `[]` 이다. `["UNKNOWN"]` 은 판정 불가다. **둘은 다르다.**
- UNKNOWN 은 혼자만 온다. R·T 코드와 섞이면 거부
- Reaction 이 있는데 Target 이 비었으면 거부 (모르면 `["UNKNOWN"]`)
- timestamp 는 원문에 **글자 그대로 있는 것만**. 원문에 없는 값이 하나라도
  오면 거부한다 (H2 — AI 가 장면·시각을 추정하지 않는다)
- review_flag 가 false 면 review_reason 은 null, true 면 세 사유 중 하나

## 분석 대상 (H3)

댓글에 `analysis_eligible` 상태가 있으면 **제외(0/false)로 확정된 것만** 빼고
보낸다. 상태가 없거나 아직 정해지지 않았으면(NULL) 보내고, 거르는 일은 집계에
맡긴다. 채널 본인 댓글 제외도 집계의 일이다.

## 결과의 지위

독립 fresh 표본으로 사람 판정과 대조해 통과하기 전까지 여기서 나온 값은 전부
**「검증 전 AI 판정」** 이다. Phase 2 200개는 R9 수정에 쓰였으므로 개발·보정용일
뿐 검증 증거가 아니다 (`docs/data-ledger.md` I 항목).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import re
from dataclasses import dataclass, field

from app.pipeline.offline_llm import BATCH_SIZE, _mapping_block
from app.prompts.registry import get as get_prompt

PROMPT_NAME = "comment_reaction"
LABEL_FORMAT = "reaction-labels-v1"

UNKNOWN = "UNKNOWN"
REACTIONS = tuple(f"R{i}" for i in range(1, 11))
TARGETS = tuple(f"T{i}" for i in range(1, 6))
REVIEW_REASONS = ("APPLICATION_ERROR", "DEFINITION_BOUNDARY", "STRUCTURE_CANDIDATE")

REACTION_NAMES = {
    "R1": "평가·칭찬", "R2": "관계·정서", "R3": "즐거움·놀이", "R4": "비판·불만",
    "R5": "시청 어려움·회피", "R6": "당혹·의문", "R7": "내용 참여",
    "R8": "요청·제안", "R9": "행동 지향", "R10": "성과 참여",
}
TARGET_NAMES = {
    "T1": "콘텐츠 전체", "T2": "내용·소재", "T3": "인물", "T4": "제작·표현",
    "T5": "채널·커뮤니티", UNKNOWN: "판정 불가",
}

# 원문을 담는 산출물(묶음 파일·사람 판정 시트·근거 문장이 든 라벨 파일)은
# gitignored 인 backend/data/ 아래에만 쓴다.
DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "data"

# observable.timestamps 와 같은 모양. 여기서는 초로 바꾸지 않고 **원문 문자열**을
# 남긴다 — H2 가 보존하라는 것은 원문에 적힌 그 값이다.
_TS = re.compile(r"(?<![\d:])(\d{1,3}:\d{2}(?::\d{2})?)(?![\d:])")


class ValidationError(ValueError):
    pass


class UnsafePath(ValueError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def ensure_private_path(path, base: pathlib.Path = DATA_DIR) -> pathlib.Path:
    """원문이 들어갈 파일은 gitignored 디렉터리 아래에만 쓴다. 아니면 막는다.

    경고로 두지 않는다. 한 번 커밋된 댓글 원문은 이력에서 지우기 어렵다.
    """
    p = pathlib.Path(path).resolve()
    b = pathlib.Path(base).resolve()
    if p != b and b not in p.parents:
        raise UnsafePath(
            f"{p} 는 {b} 밖이다. 댓글 원문이 들어가는 파일은 gitignored 인 "
            f"backend/data/ 아래에만 쓴다")
    return p


# --------------------------------------------------------------------------
# timestamp — 원문에 있는 것만
# --------------------------------------------------------------------------

def literal_timestamps(text: str) -> list[str]:
    """원문에 적힌 m:ss / h:mm:ss 꼴 문자열. 나타난 순서, 중복 제거."""
    out: list[str] = []
    for m in _TS.finditer(text or ""):
        parts = [int(x) for x in m.group(1).split(":")]
        if parts[-1] >= 60 or (len(parts) == 3 and parts[1] >= 60):
            continue
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


# --------------------------------------------------------------------------
# 한 댓글의 판정 검증 — AI·사람·평가 도구가 함께 쓴다
# --------------------------------------------------------------------------

def _codes(value, allowed: tuple, axis: str, problems: list[str], where: str) -> list[str]:
    if not isinstance(value, list):
        problems.append(f"{where}: {axis} 는 배열이어야 한다 "
                        f"(None 은 null 이 아니라 [] 로 쓴다)")
        return []
    order = {c: i for i, c in enumerate(allowed + (UNKNOWN,))}
    seen: list[str] = []
    for c in value:
        if not isinstance(c, str) or c not in order:
            hint = " — Reaction=None 은 [] 로 쓴다" if str(c).lower() in ("none", "null") else ""
            problems.append(f"{where}: {axis} 에 없는 코드 {c!r}{hint}")
            continue
        if c in seen:
            problems.append(f"{where}: {axis} 에 {c} 가 두 번 있다")
            continue
        seen.append(c)
    if UNKNOWN in seen and len(seen) > 1:
        problems.append(f"{where}: {axis} 의 UNKNOWN 은 다른 코드와 섞을 수 없다 ({seen})")
    return sorted(seen, key=order.__getitem__)


def check_label(label: dict, *, text: str | None = None, where: str = "",
                strict: bool = True) -> tuple[dict, list[str]]:
    """판정 하나를 검사하고 정규화한다. (정규화된 판정, 문제 목록).

    strict=True  (AI 출력) — 모든 칸이 있어야 하고 rationale 이 비면 안 된다.
    strict=False (사람 판정·평가 입력) — review·timestamp·rationale 칸이 없으면
                 기본값으로 채운다. **코드 규칙은 똑같이 엄격하다.**

    text 를 주면 timestamp 가 원문에 글자 그대로 있는지 대조하고, 원문에 있는데
    빠진 timestamp 는 결정적 추출값으로 채운다. 채우는 것은 원문에 있는 값이라
    H2 를 어기지 않는다. 원문에 없는 값은 채우지도 받지도 않는다.
    """
    problems: list[str] = []
    if not isinstance(label, dict):
        return {}, [f"{where}: 판정이 객체가 아니다"]

    for k in ("reactions", "targets"):
        if k not in label:
            problems.append(f"{where}: 필수 항목 '{k}' 이 없다")
    if strict:
        for k in ("explicit_timestamps", "review_flag", "review_reason", "rationale"):
            if k not in label:
                problems.append(f"{where}: 필수 항목 '{k}' 이 없다")

    reactions = _codes(label.get("reactions", []), REACTIONS, "reactions", problems, where)
    targets = _codes(label.get("targets", []), TARGETS, "targets", problems, where)
    if reactions and not targets:
        problems.append(f"{where}: Reaction 이 있는데 targets 가 비었다 "
                        f"(대상을 모르면 [\"UNKNOWN\"])")

    ts = label.get("explicit_timestamps", [])
    stamps: list[str] = []
    if not isinstance(ts, list):
        problems.append(f"{where}: explicit_timestamps 는 배열이어야 한다")
    else:
        for t in ts:
            if not isinstance(t, str) or not t.strip() or not re.search(r"\d", t):
                problems.append(f"{where}: timestamp {t!r} 는 숫자가 든 문자열이 아니다")
                continue
            t = t.strip()
            if text is not None and t not in text:
                problems.append(f"{where}: timestamp {t!r} 가 원문에 없다 — "
                                f"추정한 timestamp 는 받지 않는다 (H2)")
                continue
            if t not in stamps:
                stamps.append(t)
        if text is not None:
            for t in literal_timestamps(text):
                if t not in stamps:
                    stamps.append(t)
            stamps.sort(key=lambda s: text.find(s))

    flag = label.get("review_flag", False)
    reason = label.get("review_reason")
    if not isinstance(flag, bool):
        problems.append(f"{where}: review_flag 는 true/false 여야 한다 ({flag!r})")
        flag = bool(flag)
    if flag and reason not in REVIEW_REASONS:
        problems.append(f"{where}: review_flag 가 true 인데 review_reason {reason!r} 가 "
                        f"{list(REVIEW_REASONS)} 중 하나가 아니다")
    if not flag and reason is not None:
        problems.append(f"{where}: review_flag 가 false 인데 review_reason 이 "
                        f"{reason!r} 이다 (null 이어야 한다)")

    rationale = label.get("rationale")
    if rationale is None and not strict:
        rationale = ""
    if not isinstance(rationale, str):
        problems.append(f"{where}: rationale 은 문자열이어야 한다")
        rationale = ""
    elif strict and not rationale.strip():
        problems.append(f"{where}: rationale 이 비었다")

    return {
        "reactions": reactions,
        "targets": targets,
        "explicit_timestamps": stamps,
        "review_flag": flag,
        "review_reason": reason if flag else None,
        "rationale": rationale.strip(),
    }, problems


def validate_reactions(result: dict, mapping: dict[str, str],
                       texts: dict[str, str] | None = None) -> list[dict]:
    """묶음 판정 결과를 검증한다. 통과하면 comment_id 가 붙은 행들을 돌려준다.

    texts 는 comment_id → 원문. timestamp 대조에 쓴다. 틀린 것은 전부 모아
    한 번에 알려준다 — 무엇이 어떻게 어긋났는지가 프롬프트를 고치는 재료다.
    """
    problems: list[str] = []
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise ValidationError("results 가 배열이 아니다")

    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        idx = str(r.get("idx")) if isinstance(r, dict) else "?"
        if idx not in mapping:
            problems.append(f"입력에 없는 번호 {idx}")
            continue
        if idx in seen:
            problems.append(f"번호 {idx} 중복")
            continue
        seen.add(idx)
        cid = mapping[idx]
        text = (texts or {}).get(cid)
        label, bad = check_label(r, text=text, where=idx, strict=True)
        problems += bad
        out.append({"comment_id": cid, "idx": int(idx), **label})

    missing = sorted(set(mapping) - seen, key=int)
    if missing:
        problems.append(f"빠진 번호 {missing}")
    if problems:
        raise ValidationError("\n  - ".join(["판정 결과가 규칙에 맞지 않는다:"] + problems))
    return out


# --------------------------------------------------------------------------
# 입력 — DB 또는 raw JSON
# --------------------------------------------------------------------------

def _eligible(value) -> bool:
    """제외로 **확정된** 것만 False. 상태가 없거나 미정이면 보낸다."""
    return not (value is False or value == 0 or value == "0")


def load_raw_comments(path) -> tuple[list[dict], int]:
    """raw 수집 JSON 에서 판정할 댓글을 읽는다. (대상, 제외된 건수).

    `{"comments": [...]}` 또는 배열. 각 행에 comment_id·text 가 필요하고
    video_id·video_title·channel_name 은 있으면 맥락으로 쓴다.
    `analysis_eligible` 이 false 인 행은 뺀다 (H3).
    """
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = data.get("comments") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("raw JSON 에서 comments 배열을 찾지 못했다")
    out, skipped = [], 0
    for r in rows:
        if "comment_id" not in r or "text" not in r:
            raise ValueError("raw 행에 comment_id 또는 text 가 없다")
        if not _eligible(r.get("analysis_eligible")):
            skipped += 1
            continue
        out.append({
            "comment_id": r["comment_id"],
            "video_id": r.get("video_id") or "?",
            "video_title": r.get("video_title") or "(제목 없음)",
            "channel_name": r.get("channel_name") or "(채널 이름 없음)",
            "text": r["text"],
        })
    return out, skipped


def pending(conn, prompt_version: str, model: str,
            video_id: str | None = None, limit: int | None = None) -> list[dict]:
    """아직 이 (버전, 모델) 로 판정되지 않은 댓글. 영상별로 모아 돌려준다.

    comments 에 analysis_eligible 열이 있으면 0 으로 확정된 것만 뺀다.
    열이 없으면 전부 보낸다 — 거르는 일은 집계에 맡긴다.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comments)")}
    sql = """
        SELECT c.comment_id, c.video_id, c.text, v.title AS video_title,
               COALESCE(ch.title, '(채널 이름 없음)') AS channel_name
        FROM comments c
        JOIN videos v ON v.video_id = c.video_id
        LEFT JOIN channels ch ON ch.channel_id = v.channel_id
        LEFT JOIN comment_reactions l
               ON l.comment_id = c.comment_id
              AND l.prompt_version = ? AND l.model = ?
        WHERE l.comment_id IS NULL
    """
    params: list = [prompt_version, model]
    if "analysis_eligible" in cols:
        sql += " AND (c.analysis_eligible IS NULL OR c.analysis_eligible != 0)"
    if video_id:
        sql += " AND c.video_id = ?"
        params.append(video_id)
    sql += " ORDER BY c.video_id, c.published_at"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def chunk(rows: list[dict], size: int = BATCH_SIZE) -> list[list[dict]]:
    """영상 경계를 넘지 않게 자른다. 묶음 본문이 영상 제목을 맥락으로 준다."""
    by_video: dict[str, list[dict]] = {}
    for r in rows:
        by_video.setdefault(r.get("video_id") or "?", []).append(r)
    return [rs[i:i + size] for rs in by_video.values() for i in range(0, len(rs), size)]


def estimate(rows: list[dict], size: int = BATCH_SIZE) -> dict:
    """보내기 전에 규모를 알려준다. 사람이 멈출 기회를 준다."""
    by_video: dict[str, int] = {}
    for r in rows:
        k = r.get("video_id") or "?"
        by_video[k] = by_video.get(k, 0) + 1
    return {"comments": len(rows),
            "batches": sum(math.ceil(n / size) for n in by_video.values()),
            "chars": sum(len(r.get("text") or "") for r in rows)}


# --------------------------------------------------------------------------
# 묶음 본문 — 오프라인·API 가 함께 쓴다
# --------------------------------------------------------------------------

def batch_body(comments: list[dict], batch_id: str) -> tuple[str, dict[str, str]]:
    """판정할 묶음 본문과 번호↔ID 대응표.

    `offline_llm.batch_body` 와 같은 모양이지만 채널 이름을 더하고 좋아요 수를
    뺀다. Reaction 정의에 좋아요 수가 들어가는 곳이 없고, 숫자를 보여주면
    R10(성과 참여)을 「성과가 높은 댓글」로 오해할 여지만 생긴다.
    """
    first = comments[0] if comments else {}
    mapping = {str(i): c["comment_id"] for i, c in enumerate(comments, 1)}
    lines = [
        "# 이 묶음",
        "",
        f"- batch: `{batch_id}`",
        f"- 채널 (맥락으로만): **{first.get('channel_name') or '(채널 이름 없음)'}**",
        f"- 영상 제목 (맥락으로만): **{first.get('video_title') or '(제목 없음)'}**",
        f"- 댓글 {len(comments)}건",
        "",
        "## 판정할 댓글",
        "",
    ]
    for i, c in enumerate(comments, 1):
        text = (c.get("text") or "").replace("\n", " ⏎ ")
        lines.append(f"{i}. {text}")
    return "\n".join(lines), mapping


def export(comments: list[dict], batch_id: str, out_dir,
           *, base: pathlib.Path = DATA_DIR) -> pathlib.Path:
    """댓글 묶음을 판정용 파일 하나로 내보낸다 (오프라인 경로, 금전 비용 0).

    대응표 파일에 원문도 함께 남긴다 — import 때 timestamp 가 원문에 있는지
    대조해야 하기 때문이다. 그래서 이 파일들은 backend/data/ 아래에만 쓴다.
    """
    out_dir = ensure_private_path(out_dir, base)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = get_prompt(PROMPT_NAME)
    body, mapping = batch_body(comments, batch_id)
    sep = "\n\n---\n\n"
    path = out_dir / f"{batch_id}.md"
    path.write_text(prompt.full_text + sep + body + sep + _mapping_block(mapping),
                    encoding="utf-8")
    (out_dir / f"{batch_id}.map.json").write_text(
        json.dumps({"batch": batch_id, "prompt": prompt.name,
                    "prompt_version": prompt.version, "map": mapping,
                    "texts": {c["comment_id"]: c.get("text") or "" for c in comments},
                    "contains_raw_text": True},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# 저장 — DB 또는 라벨 파일
# --------------------------------------------------------------------------

def save_reactions(conn, rows: list[dict], prompt_version: str, model: str,
                   log=None) -> int:
    """검증을 통과한 판정을 comment_reactions 에 넣는다.

    (comment_id, 버전, 모델) 이 PK 라 같은 묶음을 다시 돌려도 덮어쓰기만 된다.
    """
    written = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO comment_reactions (comment_id, prompt_version, model,
                       reactions_json, targets_json, timestamps_json,
                       review_flag, review_reason, rationale, labeled_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       reactions_json=excluded.reactions_json,
                       targets_json=excluded.targets_json,
                       timestamps_json=excluded.timestamps_json,
                       review_flag=excluded.review_flag,
                       review_reason=excluded.review_reason,
                       rationale=excluded.rationale,
                       labeled_at=excluded.labeled_at""",
                (r["comment_id"], prompt_version, model,
                 json.dumps(r["reactions"]), json.dumps(r["targets"]),
                 json.dumps(r["explicit_timestamps"], ensure_ascii=False),
                 int(r["review_flag"]), r["review_reason"], r["rationale"], _now()))
            written += 1
        except Exception as e:   # 표본에서 온 comment_id 는 DB 에 없을 수 있다
            if log:
                log(f"  건너뜀 {r['comment_id']}: {e}")
    return written


def _label_entry(r: dict) -> dict:
    return {k: r[k] for k in ("comment_id", "reactions", "targets", "explicit_timestamps",
                              "review_flag", "review_reason", "rationale")}


def label_file(rows: list[dict], *, labeler: str, prompt_version: str | None = None,
               model: str | None = None) -> dict:
    """평가 도구가 읽는 라벨 파일. 원문은 싣지 않는다 (rationale 은 싣는다)."""
    return {
        "format": LABEL_FORMAT,
        "labeler": labeler,
        "prompt_version": prompt_version,
        "model": model,
        "status": "검증 전 AI 판정" if labeler.startswith("ai:") else "사람 판정",
        "created_at": _now(),
        "labels": [_label_entry(r) for r in sorted(rows, key=lambda x: x["comment_id"])],
    }


def merge_into_label_file(path, rows: list[dict], *, prompt_version: str, model: str,
                          base: pathlib.Path = DATA_DIR) -> int:
    """라벨 파일에 판정을 더한다 (같은 comment_id 는 덮어쓴다). 전체 건수를 돌려준다.

    DB 에 없는 댓글(raw JSON 에서 온 fresh 표본)을 판정할 때 쓴다. rationale 이
    원문을 인용할 수 있어 backend/data/ 아래에만 쓴다.
    """
    p = ensure_private_path(path, base)
    have: dict[str, dict] = {}
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        if old.get("prompt_version") not in (None, prompt_version) or \
                old.get("model") not in (None, model):
            raise ValueError(f"{p} 는 다른 (버전, 모델) 의 라벨 파일이다 "
                             f"({old.get('prompt_version')}, {old.get('model')})")
        have = {x["comment_id"]: x for x in old.get("labels", [])}
    for r in rows:
        have[r["comment_id"]] = _label_entry(r)
    data = label_file(list(have.values()), labeler=f"ai:{model}",
                      prompt_version=prompt_version, model=model)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data["labels"])


def labels_from_db(conn, prompt_version: str, model: str) -> dict:
    """DB 의 판정을 평가 도구용 라벨 파일 모양으로."""
    rows = []
    for r in conn.execute(
            """SELECT comment_id, reactions_json, targets_json, timestamps_json,
                      review_flag, review_reason, rationale
               FROM comment_reactions WHERE prompt_version=? AND model=?
               ORDER BY comment_id""", (prompt_version, model)):
        rows.append({
            "comment_id": r["comment_id"],
            "reactions": json.loads(r["reactions_json"]),
            "targets": json.loads(r["targets_json"]),
            "explicit_timestamps": json.loads(r["timestamps_json"]),
            "review_flag": bool(r["review_flag"]),
            "review_reason": r["review_reason"],
            "rationale": r["rationale"] or "",
        })
    return label_file(rows, labeler=f"ai:{model}", prompt_version=prompt_version,
                      model=model)


# --------------------------------------------------------------------------
# API 경로
# --------------------------------------------------------------------------

@dataclass
class Progress:
    batches: int = 0
    done: int = 0
    labeled: int = 0
    flagged: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def run(client, rows: list[dict], *, conn=None, labels_out=None,
        model: str | None = None, size: int = BATCH_SIZE,
        dry_run: bool = False, log=print, base: pathlib.Path = DATA_DIR) -> Progress:
    """댓글을 API 로 판정해 DB(conn) 또는 라벨 파일(labels_out) 에 넣는다.

    **금전 비용이 나가는 경로다.** 대상 건수와 묶음 수를 먼저 찍는다.
    한 묶음이 검증에 걸려도 나머지는 계속 간다. 실패한 묶음의 댓글은 판정
    없이 남고, 다음 실행이 다시 집는다(DB 경로).
    """
    if not dry_run and (conn is None) == (labels_out is None):
        raise ValueError("conn 과 labels_out 중 정확히 하나에 저장한다")
    if labels_out is not None:
        # 돈을 쓰기 전에 막는다. 호출을 다 하고 저장에서 거부되면 판정이 버려진다.
        ensure_private_path(labels_out, base)
    prompt = get_prompt(PROMPT_NAME)
    mdl = model or client.model
    batches = chunk(rows, size)
    p = Progress(batches=len(batches))

    est = estimate(rows, size)
    log(f"[Reaction] 대상 {est['comments']}건 · {est['batches']}묶음 · "
        f"프롬프트 {prompt.name}({prompt.version}) · 모델 {mdl} · 검증 전 AI 판정")
    if dry_run or not batches:
        log("  판정할 것이 없다" if not batches else "  --dry-run 이라 호출하지 않았다")
        return p

    for i, group in enumerate(batches, 1):
        batch_id = f"api_{group[0].get('video_id') or 'x'}_r{i:03d}"
        body, mapping = batch_body(group, batch_id)
        texts = {c["comment_id"]: c.get("text") or "" for c in group}
        try:
            data = client.judge(prompt, body)
            judged = validate_reactions(data, mapping, texts)
        except ValidationError as e:
            p.failed.append((batch_id, f"검증 실패: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} 검증 실패 — 건너뛴다")
            continue
        except Exception as e:
            p.failed.append((batch_id, f"{type(e).__name__}: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} {type(e).__name__} — 건너뛴다")
            continue

        if conn is not None:
            p.labeled += save_reactions(conn, judged, prompt.version, mdl, log=log)
        else:
            merge_into_label_file(labels_out, judged, prompt_version=prompt.version,
                                  model=mdl, base=base)
            p.labeled += len(judged)
        p.flagged += sum(1 for r in judged if r["review_flag"])
        p.done += 1
        if i % 10 == 0 or i == len(batches):
            log(f"  [{i}/{len(batches)}] 누적 {p.labeled}건 (review_flag {p.flagged})")

    log(f"[Reaction] {p.done}/{p.batches}묶음 성공 · {p.labeled}건 저장")
    if p.failed:
        log(f"  실패 {len(p.failed)}묶음 — 그 댓글은 판정 없이 남는다")
    log("  " + client.usage.describe(mdl))
    return p
