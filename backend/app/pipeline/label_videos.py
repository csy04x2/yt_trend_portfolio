"""3단계 영상 유형 — 제목을 보내 체계를 세우고 라벨을 붙이는 경로.

`classify_videos` 는 검증·저장·집계만 갖고 있었다. 판정을 **누가 어떻게
받아오는가**가 비어 있어서 `video_label`(topics-v1) 과
`taxonomy_propose`(taxonomy-v1) 두 프롬프트가 파일로만 있고 아무도 읽지
않았다. 그 구멍을 여기서 메운다.

    오프라인   export()  → 사람이 Claude Code 에 붙여넣음 → .result.json → 검증 → DB
    API 경로   titles_body() → client.judge()            → dict         → 검증 → DB
                              ~~~~~~~~~~~~~~~~ 여기만 다르다

`offline_llm` 이 댓글에서 지키는 것과 같은 불변식이다. 두 경로가 **같은
프롬프트 전문과 같은 묶음 본문**을 보낸다. 오프라인에서 프롬프트를 다듬어
놓고 API 에 다른 문자열을 보내면 오프라인에서 잰 정확도가 아무 의미가 없다.

## 왜 체계를 먼저 한 번만 받는가

제목이 많아 한 번에 안 들어가면 나눠 보내야 하는데, `video_label` 의 출력은
`types`(체계) 와 `labels`(라벨) 를 함께 들고 온다. 묶음마다 체계를 새로
받으면 **한 채널에 체계가 여러 벌 생긴다.** 코드 이름이 같아도 같은 자가
아니다 — 2묶음의 T_BIZ 는 2묶음의 제목들만 보고 그은 선이다. 그 라벨을 한
표에 모아 유형별 성과를 내면, 서로 다른 자로 잰 값을 비교하게 된다.

그래서 순서를 고정한다. **체계는 한 번의 호출에서만 나온다.** 나눠 보낼
때는 첫 호출의 `types` 를 확정하고, 이후 묶음에는 그 체계를 본문에 적어
주고 라벨만 받는다. 이후 묶음이 돌려준 `types` 는 버린다.

## 체계 제안은 저장하지 않는다

`taxonomy_propose` 의 결과는 **제안**이다. 이 모듈은 그것을 찍어 주고 파일로
남기기만 한다. 사람이 보고 확정해야 라벨이 그 위에 걸린다 —
`cli import-taxonomy --confirm` 이 그 자리다. 자동으로 저장하면, 아무도 보지
않은 자에 300편이 매달린 채로 리포트까지 흘러간다.
"""

from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, field

from app.pipeline import classify_videos as cv
from app.pipeline.offline_llm import _mapping_block
from app.prompts.registry import get as get_prompt

# 제목 묶음 크기. 댓글(20)보다 큰 것은 제목이 짧아서다. 상한을 정하는 것은
# 입력이 아니라 출력이다 — 라벨 한 줄이 대략 25토큰이라 max_tokens 8000 에
# 300편을 한 번에 받으면 잘린다. 잘린 JSON 은 살려 쓰지 않는다(claude.py).
TITLE_BATCH = 120

# 길이 축을 한 글자로. 제목 옆에 붙여 판정자에게 준다.
LENGTH_MARK = {"shorts": "S", "standard": "M", "long": "L"}

PROMPT_TYPES = "video_label"
PROMPT_TAXONOMY = "taxonomy_propose"


@dataclass
class Progress:
    batches: int = 0
    done: int = 0
    labeled: int = 0
    types: dict = field(default_factory=dict)
    taxonomy_id: int | None = None
    proposal: dict | None = None        # taxonomy_propose 는 저장하지 않는다
    failed: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# 대상 고르기
# --------------------------------------------------------------------------

def titles(conn, channel_id: str, limit: int | None = None) -> list[dict]:
    """채널의 영상 제목 전부. 체계를 제안받을 때 쓴다.

    라벨 유무로 거르지 않는다 — 체계는 채널이 실제로 만드는 것들의 모양에서
    나와야 하고, 이미 라벨된 편도 그 모양의 일부다.
    """
    sql = ("SELECT video_id, title, length_axis, published_at FROM videos "
           "WHERE channel_id=? ORDER BY published_at DESC")
    params: list = [channel_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def pending(conn, channel_id: str, prompt_version: str, model: str,
            limit: int | None = None) -> list[dict]:
    """아직 그 (버전, 모델) 로 유형 라벨이 없는 영상들.

    모델을 바꾸면 같은 영상이 다시 대상이 된다. 덮어쓰기가 아니라 새 행이라
    그게 맞다 — 두 모델의 라벨을 나란히 놓고 비교하려고 키에 모델이 있다.
    """
    sql = """
        SELECT v.video_id, v.title, v.length_axis, v.published_at
        FROM videos v
        LEFT JOIN video_type_labels l
               ON l.video_id = v.video_id
              AND l.prompt_version = ? AND l.model = ?
        WHERE v.channel_id = ? AND l.video_id IS NULL
        ORDER BY v.published_at DESC
    """
    params: list = [prompt_version, model, channel_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def chunk(rows: list[dict], size: int = TITLE_BATCH) -> list[list[dict]]:
    """그냥 순서대로 자른다.

    댓글과 달리 영상 경계를 지킬 일이 없다 — 여기서는 영상 자체가 단위다.
    다만 published_at 역순을 유지한다. 한 묶음에 비슷한 시기의 제목이 모여
    있으면 판정자가 그 시기의 시리즈를 알아본다.
    """
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def estimate(rows: list[dict], size: int = TITLE_BATCH) -> dict:
    """보내기 전에 규모를 알려준다. 사람이 멈출 기회를 준다."""
    return {
        "videos": len(rows),
        "batches": math.ceil(len(rows) / size) if rows else 0,
        "chars": sum(len(r.get("title") or "") for r in rows),
    }


# --------------------------------------------------------------------------
# 묶음 본문 — 오프라인과 API 가 함께 쓴다
# --------------------------------------------------------------------------

def titles_body(rows: list[dict], batch_id: str,
                channel_title: str) -> tuple[str, dict[str, str]]:
    """판정할 제목 묶음과 번호↔video_id 대응표.

    **길이 축을 대괄호로 함께 준다.** 같은 낱말이라도 쇼츠 제목과 롱폼
    제목은 다른 물건이다 — 쇼츠는 한 장면을 낚아채는 말이고 롱폼은 다룰
    범위를 예고하는 말이라, 축을 모르면 「충격」 하나에 끌려간다. 판정자가
    보는 재료는 제목뿐이므로(video_label 의 「제목뿐이다」) 제목 옆에
    붙여 줄 수 있는 사실은 이것 하나다.

    video_id 대신 묶음 안 1~N 번호를 쓰는 이유는 댓글과 같다 — 긴 ID 를
    되돌려 받으면 출력 토큰이 늘고 잘못 옮겨 적을 여지가 생긴다.
    """
    mapping = {str(i): r["video_id"] for i, r in enumerate(rows, 1)}
    lines = [
        "# 이 묶음",
        "",
        f"- batch: `{batch_id}`",
        f"- 채널: **{channel_title}**",
        f"- 영상 {len(rows)}편",
        "",
        "## 분류할 제목",
        "",
        "대괄호는 길이 축이다 — `S` 쇼츠 · `M` 일반 · `L` 롱폼 "
        "(`?` 는 아직 판정되지 않은 것).",
        "",
    ]
    for i, r in enumerate(rows, 1):
        mark = LENGTH_MARK.get(r.get("length_axis") or "", "?")
        # 제목 안의 줄바꿈은 기호로 바꾼다. 그대로 두면 번호 매긴 목록이
        # 끊겨 판정자가 한 편을 둘로 읽는다.
        title = (r.get("title") or "").replace("\n", " ⏎ ")
        lines.append(f"{i}.[{mark}] {title}")
    return "\n".join(lines), mapping


def _fixed_taxonomy_block(types: dict[str, str]) -> str:
    """이후 묶음에 붙이는 확정 체계.

    첫 호출이 그은 자를 그대로 쓰라고 말한다. 이 블록이 없으면 묶음마다
    체계가 새로 나오고, 코드 이름이 같아도 같은 자가 아니게 된다.
    """
    rows = "\n".join(f"- `{code}` {name}" for code, name in types.items())
    return "\n".join([
        "## 이미 확정된 유형 체계 (새로 만들지 말 것)",
        "",
        "앞 묶음에서 정한 체계다. `types` 는 아래 그대로 돌려주고,",
        "라벨은 이 코드 안에서만 고른다. 새 코드를 만들면 그 라벨은 버려진다.",
        "",
        rows,
    ])


# --------------------------------------------------------------------------
# 오프라인 경로
# --------------------------------------------------------------------------

def export(conn, channel_id: str, prompt_name: str, batch_id: str,
           out_dir: pathlib.Path, rows: list[dict] | None = None,
           channel_title: str | None = None) -> pathlib.Path:
    """제목 묶음을 판정용 파일 하나로 내보낸다.

    파일 하나에 **프롬프트 전문 + 묶음 본문 + 대응표**를 담는다. 셋을
    나눠 두면 사람이 셋을 다 붙여넣어야 하고, 하나를 빠뜨린 채 판정한
    결과가 조용히 들어온다.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if rows is None:
        rows = titles(conn, channel_id)
    if channel_title is None:
        row = conn.execute("SELECT title FROM channels WHERE channel_id=?",
                           (channel_id,)).fetchone()
        channel_title = row["title"] if row else "(채널 이름 없음)"

    prompt = get_prompt(prompt_name)
    body, mapping = titles_body(rows, batch_id, channel_title)
    sep = "\n\n---\n\n"
    # full_text 는 헤더까지 붙은 파일 전문이다. 판정자가 버전과 이력을
    # 함께 봐야 어느 자로 잰 것인지 나중에 되짚을 수 있다.
    text = prompt.full_text + sep + body + sep + _mapping_block(mapping)

    path = out_dir / f"{batch_id}.md"
    path.write_text(text, encoding="utf-8")
    (out_dir / f"{batch_id}.map.json").write_text(
        json.dumps({"batch": batch_id, "channel_id": channel_id,
                    "channel_title": channel_title, "prompt": prompt.name,
                    "prompt_version": prompt.version, "map": mapping},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return path


def save_result(conn, channel_id: str, payload: dict, mapping: dict[str, str],
                model: str, prompt_version: str | None = None) -> tuple[int, int, list]:
    """`video_label` 결과를 검증해 체계와 라벨을 함께 넣는다.

    오프라인 import 와 API 경로가 함께 쓴다. 체계와 라벨을 한 함수에 둔
    것은 둘을 따로 저장할 방법이 없어야 하기 때문이다 — 라벨은 자기가
    걸린 자(taxonomy_id)를 갖고, 그 자 없이 라벨만 들어가면 나중에 어느
    체계로 읽어야 할지 알 수 없다.
    """
    rows = cv.validate(payload, mapping)          # 검증기는 그대로 쓴다

    # **판정 파일이 정하는 것은 체계의 이름이지 프롬프트의 버전이 아니다.**
    # payload 의 taxonomy_version 을 prompt_version 으로 쓰던 것을 고쳤다 —
    # 그러면 채널마다 다른 이름이 프롬프트 버전 칸에 들어가 대조기가
    # "그 버전의 원문이 없다"고 잡는다. 실제로 잡혔고, 옳은 경고였다.
    version = prompt_version or get_prompt(PROMPT_TYPES).version
    label = payload.get("taxonomy_version", "")

    tid = cv.save_taxonomy(conn, channel_id, payload["types"], model, version,
                           axis="topic", label=label)
    n = cv.save_labels(conn, tid, rows, version, model)
    return tid, n, rows


# --------------------------------------------------------------------------
# API 경로
# --------------------------------------------------------------------------

def run(conn, client, channel_id: str, *, prompt_name: str = PROMPT_TYPES,
        model: str | None = None, limit: int | None = None,
        size: int = TITLE_BATCH, dry_run: bool = False,
        out_dir: pathlib.Path | None = None, log=print) -> Progress:
    """제목을 API 로 보내 유형 체계나 유형 라벨을 받는다.

    prompt_name 이 둘 중 무엇이냐에 따라 하는 일이 다르다.

        video_label       체계 + 라벨을 받아 **저장한다**
        taxonomy_propose  체계 제안을 받아 **찍고 파일로만 남긴다**

    저장 여부가 갈리는 이유는 위 「체계 제안은 저장하지 않는다」에 있다.
    """
    if prompt_name == PROMPT_TAXONOMY:
        return propose(conn, client, channel_id, model=model, limit=limit,
                       dry_run=dry_run, out_dir=out_dir, log=log)
    return label(conn, client, channel_id, model=model, limit=limit,
                 size=size, dry_run=dry_run, log=log)


def _channel_title(conn, channel_id: str) -> str:
    row = conn.execute("SELECT title FROM channels WHERE channel_id=?",
                       (channel_id,)).fetchone()
    return row["title"] if row else "(채널 이름 없음)"


def propose(conn, client, channel_id: str, *, model: str | None = None,
            limit: int | None = None, dry_run: bool = False,
            out_dir: pathlib.Path | None = None, log=print) -> Progress:
    """채널에 맞는 유형 체계를 제안받는다. **한 번의 호출이다.**

    나눠 물으면 나눈 만큼의 체계가 나온다. 제안은 전체 제목의 모양을
    보고 나오는 것이라 묶음으로 쪼개면 질문 자체가 성립하지 않는다.
    """
    prompt = get_prompt(PROMPT_TAXONOMY)
    mdl = model or client.model
    rows = titles(conn, channel_id, limit)
    p = Progress(batches=1 if rows else 0)

    log(f"[체계 제안] 제목 {len(rows)}편 · 한 번에 보낸다 · "
        f"프롬프트 {prompt.name}({prompt.version}) · 모델 {mdl}")
    if not rows:
        log("  영상이 없다 — 먼저 collect 를 돌려라")
        p.batches = 0
        return p
    if dry_run:
        log("  --dry-run 이라 호출하지 않았다")
        return p

    batch_id = f"api_{channel_id[-6:]}_taxonomy"
    body, _ = titles_body(rows, batch_id, _channel_title(conn, channel_id))
    try:
        data = client.judge(prompt, body)
    except Exception as e:
        p.failed.append((batch_id, f"{type(e).__name__}: {e}"))
        log(f"  {type(e).__name__} — 제안을 받지 못했다")
        return p

    p.done = 1
    p.proposal = data
    p.types = data.get("types") or {}
    describe(data, log=log)

    if out_dir:
        out_dir = pathlib.Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{batch_id}.result.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        log(f"  제안을 남겼다: {path}")
        log(f"  다음: python -m app.cli import-taxonomy {batch_id} "
            f"--out {out_dir} --confirm")
    log("  저장하지 않았다 — 체계는 사람이 확정한 뒤에야 라벨이 걸린다")
    log("  " + client.usage.describe(mdl))
    return p


def label(conn, client, channel_id: str, *, model: str | None = None,
          limit: int | None = None, size: int = TITLE_BATCH,
          dry_run: bool = False, log=print) -> Progress:
    """제목에 유형 라벨을 붙여 video_type_labels 에 넣는다.

    한 묶음에 다 들어가면 한 번 부르고 끝난다. 나눠야 하면 **첫 묶음이
    체계를 확정하고**, 나머지 묶음에는 그 체계를 본문에 적어 주고 라벨만
    받는다 — 위 「왜 체계를 먼저 한 번만 받는가」.
    """
    prompt = get_prompt(PROMPT_TYPES)
    mdl = model or client.model
    rows = pending(conn, channel_id, prompt.version, mdl, limit)
    batches = chunk(rows, size)
    p = Progress(batches=len(batches))

    est = estimate(rows, size)
    log(f"[유형] 대상 {est['videos']}편 · {est['batches']}묶음 · "
        f"프롬프트 {prompt.name}({prompt.version}) · 모델 {mdl}")
    if dry_run or not batches:
        if not batches:
            log("  라벨할 것이 없다 — 이 (버전, 모델) 로 전부 라벨돼 있다")
        else:
            log("  --dry-run 이라 호출하지 않았다")
        return p

    title = _channel_title(conn, channel_id)
    for i, group in enumerate(batches, 1):
        batch_id = f"api_{channel_id[-6:]}_{i:03d}"
        body, mapping = titles_body(group, batch_id, title)
        if p.types:
            # 두 번째 묶음부터는 확정된 자를 함께 보낸다
            body = body + "\n\n" + _fixed_taxonomy_block(p.types)
        try:
            data = client.judge(prompt, body)
            if p.types:
                # 이후 묶음이 돌려준 types 는 버린다. 자는 하나여야 한다.
                data = {**data, "types": p.types}
            rows_ok = cv.validate(data, mapping)
        except cv.ValidationError as e:
            p.failed.append((batch_id, f"검증 실패: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} 검증 실패 — 건너뛴다")
            continue
        except Exception as e:
            p.failed.append((batch_id, f"{type(e).__name__}: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} {type(e).__name__} — 건너뛴다")
            continue

        if not p.types:
            p.types = data["types"]
            p.taxonomy_id = cv.save_taxonomy(conn, channel_id, p.types, mdl,
                                             prompt.version, axis="topic")
            log(f"  체계 확정: 유형 {len(p.types)}종 (taxonomy_id={p.taxonomy_id})")

        # 묶음마다 커밋한다. 중간에 죽어도 여기까지는 남는다.
        p.labeled += cv.save_labels(conn, p.taxonomy_id, rows_ok,
                                    prompt.version, mdl)
        p.done += 1
        log(f"  [{i}/{len(batches)}] 누적 {p.labeled}편")

    log(f"[유형] {p.done}/{p.batches}묶음 성공 · {p.labeled}편 저장")
    if p.failed:
        log(f"  실패 {len(p.failed)}묶음 — 그 영상은 라벨 없이 남는다. "
            f"다시 실행하면 그것부터 집는다")
    log("  " + client.usage.describe(mdl))
    return p


# --------------------------------------------------------------------------
# 제안을 사람이 읽을 모양으로
# --------------------------------------------------------------------------

def describe(proposal: dict, counts: dict[str, int] | None = None, log=print) -> None:
    """제안된 체계를 찍는다. 편수는 **셀 수 있을 때만** 적는다.

    체계 제안에는 라벨이 없다. 따라서 유형별 편수는 아직 없는 값이지,
    0 이 아니다 — 0 을 찍으면 "이 유형은 비었다"는 다른 말이 된다.
    이 저장소가 조회 배수에 값 대신 근거를 남기는 것과 같은 규칙이다.
    """
    types = proposal.get("types") or {}
    defs = proposal.get("definitions") or {}
    log(f"\n제안된 유형 {len(types)}종  (taxonomy_version="
        f"{proposal.get('taxonomy_version', '?')})\n")
    for code, name in types.items():
        n = "—" if counts is None else str(counts.get(code, 0))
        log(f"  {code:<10} {name:<18} {n:>5}편")
        if defs.get(code):
            log(f"             {defs[code]}")
    if counts is None:
        log("\n  편수가 비어 있는 것은 아직 라벨이 없어서다 — 체계만 나온 단계다.")
        log("  확정한 뒤 export-titles --for types 로 라벨을 붙이면 채워진다.")
    if proposal.get("rationale"):
        log(f"\n  근거: {proposal['rationale']}")
