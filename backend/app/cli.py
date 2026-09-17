"""프로토타입 CLI.

돈이 나가는 명령은 `label` 과 `screen` 둘뿐이다. 나머지는 전부 금전 비용 0이다.

    collect        채널 URL → SQLite (YouTube 키 필요)
    collect-video  영상 URL 하나만 → SQLite (약 5유닛)
    engagement     댓글 참여가 호응인지 논쟁인지 가른다 (라벨 필요)
    rules          쌓인 댓글에 규칙을 적용하고 무엇이 걸렸는지 본다
    export-batch   댓글 묶음을 판정용 파일로 (Claude Code 가 판정)
    import-batch   판정 결과를 검증하고 저장
    label          댓글 감성·주제를 API 로 판정 (돈이 나간다)
    export-titles  영상 제목 묶음을 유형 판정용 파일로 (Claude Code 가 판정)
    import-titles  유형 라벨 결과를 검증하고 체계와 함께 저장
    import-taxonomy  제안된 유형 체계를 보고 --confirm 일 때만 저장
    export-screen-batch  댓글 묶음을 선별용 파일로 (Claude Code 가 판정)
    import-screen-batch  선별 결과를 검증하고 저장
    screen         규칙을 통과한 댓글을 API 로 다시 선별 (돈이 나간다)
    report         6단계 집계와 결론 문장 — 쇼츠/롱폼/합침 세 판
    prompts        프롬프트 파일과 DB 버전 대조
    stats          수집 현황과 설정 상태

Reaction Phase 3 (결과는 전부 「검증 전 AI 판정」 — docs/design/reaction-classifier-phase3.md)

    export-reaction-batch  Reaction·Target 판정용 묶음 파일 (Claude Code 가 판정, 비용 0)
    import-reaction-batch  판정 결과를 검증하고 DB 또는 라벨 파일에 저장
    label-reactions        Reaction·Target 을 API 로 판정 (돈이 나간다)
    export-reactions       DB 의 Reaction 판정을 평가용 라벨 파일로
    reaction-sheet         사람 판정 시트 HTML 생성 (원문이 들어가 backend/data/ 에만)
    reaction-eval          두 라벨 파일의 일치도 (숫자와 comment_id 만 출력)

지금 답이 필요한 질문 — 규칙이 무엇을 잘못 버리는가 — 은 `rules`만으로
답할 수 있다. 그 답을 모델과 대조하려면 `export-screen-batch` 로 비용 없이
먼저 재 보고, 프롬프트가 쓸 만해진 뒤에 `screen` 을 켠다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.clients.youtube import (  # noqa: E402
    ChannelNotFound,
    QuotaExhausted,
    YouTubeClient,
)
from app import exports  # noqa: E402
from app.clients import claude  # noqa: E402
from app.prompts import registry  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.pipeline.collect import collect_channel, collect_video  # noqa: E402
from app.pipeline import classify_videos as cv  # noqa: E402
from app.pipeline import aggregate  # noqa: E402
from app.pipeline import label_comments  # noqa: E402
from app.pipeline import label_videos as lv  # noqa: E402
from app.pipeline import label_reactions as lr  # noqa: E402
from app.pipeline import reaction_eval  # noqa: E402
from app.pipeline import reaction_sheet  # noqa: E402
from app.pipeline import screen_comments as sc  # noqa: E402
from app.pipeline import segments as sg  # noqa: E402
from app.pipeline.eligibility import apply_screen_exclusions  # noqa: E402
from app.pipeline.engagement import run as engagement_run  # noqa: E402
from app.pipeline.normalize import run as normalize_run  # noqa: E402
from app.pipeline.offline_llm import (  # noqa: E402
    ValidationError,
    export_batch,
    validate_result,
)
from app.pipeline.rules import (  # noqa: E402
    DEFAULT_CONFIG,
    MODEL_RULE,
    screen_comments,
    summarize,
)

RULES_VERSION = "rules-v1"
DEFAULT_DB = "./data/yt_trend.db"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# collect / collect-video
# --------------------------------------------------------------------------

def _client(args) -> tuple:
    key = config.require(
        "YOUTUBE_API_KEY",
        "Google Cloud Console에서 YouTube Data API v3를 켜고 API 키를 발급받는다.",
    )
    conn = connect(args.db)
    yt = YouTubeClient(api_key=key, daily_quota=int(config.get("YOUTUBE_DAILY_QUOTA")))
    return conn, yt, uuid.uuid4().hex[:12]


def _report(yt, db) -> None:
    print(f"\n할당량 {yt.units_used}유닛 사용 (한도 {yt.daily_quota}) · 금전 비용 0")
    print(f"DB: {db}")


def cmd_collect(args) -> int:
    conn, yt, run_id = _client(args)
    try:
        collect_channel(conn, yt, args.url, run_id, args.max_videos,
                        args.max_comments, with_comments=not args.no_comments)
    except ChannelNotFound as e:
        print(f"채널을 찾을 수 없다: {e}", file=sys.stderr)
        return 1
    _report(yt, args.db)
    return 0


def cmd_collect_video(args) -> int:
    """영상 하나만 받는다. 실험할 때 채널 전체를 받을 이유가 없다."""
    conn, yt, run_id = _client(args)
    try:
        collect_video(conn, yt, args.url, run_id, args.max_comments)
    except ValueError as e:
        print(f"{e}", file=sys.stderr)
        return 1
    except ChannelNotFound as e:
        print(f"채널을 찾을 수 없다: {e}", file=sys.stderr)
        return 1
    except QuotaExhausted as e:
        print(f"[중단] 할당량 소진 — {e}", file=sys.stderr)
        print("여기까지 저장한 것은 그대로 남는다. 다시 실행하면 이어받는다.")
        _report(yt, args.db)
        return 1
    _report(yt, args.db)
    return 0


# --------------------------------------------------------------------------
# normalize
# --------------------------------------------------------------------------

def cmd_normalize(args) -> int:
    conn = connect(args.db)
    run_id = uuid.uuid4().hex[:12]
    channels = [r["channel_id"] for r in conn.execute("SELECT channel_id FROM channels")]
    if not channels:
        print("채널이 없다. 먼저 collect 를 돌려라.", file=sys.stderr)
        return 1

    for cid in channels:
        rows = normalize_run(conn, cid, run_id)
        if not rows:
            continue
        title = conn.execute("SELECT title FROM channels WHERE channel_id=?",
                             (cid,)).fetchone()["title"]
        print(f"[{title}]  영상 {len(rows)}개\n")
        print(f"  {'영상':<34}{'축':<10}{'조회':>10}{'좋아요율':>10}{'댓글율':>10}"
              f"{'조회배수':>10}{'댓글배수':>10}")
        print("  " + "-" * 96)
        for m in sorted(rows, key=lambda r: -(r["view_count"] or 0)):
            lr = f"{m['like_rate']*100:.2f}%" if m["like_rate"] is not None else "비공개"
            cr = f"{m['comment_rate']*100:.3f}%" if m["comment_rate"] is not None else "-"
            mult = f"{m['view_multiple']:.2f}" if m["view_multiple"] is not None else "—"
            cmult = (f"{m['comment_rate_multiple']:.2f}"
                     if m["comment_rate_multiple"] is not None else "—")
            print(f"  {m['title'][:32]:<34}{m['length_axis']:<10}"
                  f"{m['view_count']:>10,}{lr:>10}{cr:>10}{mult:>10}{cmult:>10}")

        # 두 배수 모두 "왜 비었는지"를 말해야 한다. 조회 배수만 근거를 찍고
        # 댓글율 배수는 빈칸으로 두면 리포트가 반쪽이 된다.
        for label, key, basis_key in (
            ("조회 배수", "view_multiple", "view_multiple_basis"),
            ("댓글율 배수", "comment_rate_multiple", "comment_rate_multiple_basis"),
        ):
            missing = [m for m in rows if m[key] is None]
            if missing:
                print(f"\n  {label} 없음 {len(missing)}건 — 근거:")
                for m in missing[: args.show]:
                    print(f"    {m['title'][:30]:<32} {m[basis_key]}")

        print("\n  댓글율·댓글율 배수는 '댓글이 많다'까지만 말한다.")
        print("  그 댓글이 호응이냐 논쟁이냐는 `engagement` 가 라벨을 보고 가른다.")
    print(f"\nvideo_metrics 갱신 (run_id={run_id})")
    return 0


# --------------------------------------------------------------------------
# engagement
# --------------------------------------------------------------------------

def cmd_engagement(args) -> int:
    """댓글율이 높은 이유가 호응인지 논쟁인지 본다.

    댓글율은 긍정과 부정을 똑같이 올린다. 여기서 5단계 감성 라벨을 영상
    단위로 접어 approval(어느 쪽으로 기울었나)과 contention(갈렸나)으로 나눈다.
    """
    conn = connect(args.db)
    run_id = uuid.uuid4().hex[:12]
    rows = engagement_run(conn, run_id, args.prompt_version, args.model)
    if not rows:
        print("라벨된 댓글이 없다. import-batch 로 감성 라벨을 먼저 채워라.",
              file=sys.stderr)
        return 1

    # 댓글율·댓글율 배수는 2단계가 낸 값이다. 영상마다 가장 최근 실행 것을 쓴다.
    metrics = {
        r["video_id"]: r
        for r in conn.execute(
            """SELECT m.* FROM video_metrics m
               WHERE m.computed_at = (SELECT MAX(computed_at) FROM video_metrics
                                      WHERE video_id = m.video_id)"""
        )
    }

    by_version: dict[tuple[str, str], list[dict]] = {}
    for e in rows:
        by_version.setdefault((e["prompt_version"], e["model"]), []).append(e)

    for (pv, mdl), group in by_version.items():
        print(f"[prompt_version={pv} · model={mdl}]  댓글이 있는 영상 {len(group)}개\n")
        print(f"  {'영상':<34}{'댓글율':>9}{'댓글배수':>10}{'호응':>8}{'논쟁':>8}"
              f"{'라벨비율':>10}{'긍/부/중':>14}")
        print("  " + "-" * 96)
        for e in sorted(group, key=lambda r: -(r["comment_count_collected"] or 0)):
            m = metrics.get(e["video_id"])
            cr = (f"{m['comment_rate']*100:.3f}%"
                  if m is not None and m["comment_rate"] is not None else "-")
            cmult = (f"{m['comment_rate_multiple']:.2f}"
                     if m is not None and m["comment_rate_multiple"] is not None
                     else "—")
            ap = f"{e['approval']:.2f}" if e["approval"] is not None else "—"
            ct = f"{e['contention']:.2f}" if e["contention"] is not None else "—"
            lr = (f"{e['labeled_ratio']*100:.0f}%"
                  if e["labeled_ratio"] is not None else "—")
            mix = f"{e['positive']}/{e['negative']}/{e['neutral']}"
            print(f"  {e['title'][:32]:<34}{cr:>9}{cmult:>10}{ap:>8}{ct:>8}"
                  f"{lr:>10}{mix:>14}")

        missing = [e for e in group if e["approval"] is None]
        if missing:
            print(f"\n  호응·논쟁 없음 {len(missing)}건 — 근거:")
            for e in missing[: args.show]:
                print(f"    {e['title'][:30]:<32} {e['basis']}")
        print()

    print("  호응(approval)   = 긍정 ÷ (긍정+부정).  0 전부 부정 ~ 1 전부 긍정")
    print("  논쟁(contention) = 2·min(긍정,부정) ÷ (긍정+부정).  0 쏠림 ~ 1 반반")
    print("  neutral 은 두 값의 분모에서 뺀다. 라벨비율이 낮으면 그만큼만 믿는다.")
    print(f"\ncomment_engagement 갱신 (run_id={run_id})")
    return 0



# --------------------------------------------------------------------------
# types  (3단계 영상 유형)
# --------------------------------------------------------------------------

AXIS_LABEL = {"shorts": "쇼츠", "longform": "롱폼", "all": "합침"}


def cmd_segments(args) -> int:
    """채널 재생목록에서 코너를 읽어 두 번째 유형 축으로 넣는다.

    주제(topic)는 LLM 판단이지만 코너는 채널이 선언한 사실이다.
    추측할 이유가 없으므로 규칙으로만 뽑는다.
    """
    conn, yt, _ = _client(args)
    ch = conn.execute("SELECT channel_id, title FROM channels LIMIT 1").fetchone()
    if not ch:
        print("채널이 없다. 먼저 collect 를 돌려라.", file=sys.stderr)
        return 1

    playlists, membership = sg.fetch(yt, ch["channel_id"])
    total = yt.resolve_channel(
        f"https://www.youtube.com/channel/{ch['channel_id']}").get("video_count") or 0
    segs = sg.pick_segments(playlists, total)
    sizes = {p["id"]: p["item_count"] for p in playlists}
    ours = {r["video_id"] for r in conn.execute(
        "SELECT video_id FROM videos WHERE channel_id=?", (ch["channel_id"],))}

    # 채널 전체 기준 비율만으로는 큰 채널에서 서랍이 새어 나간다. 우리가
    # 받은 영상을 기준으로 한 번 더 거른다 — segments.drop_broad 를 볼 것.
    before, segs = segs, sg.drop_broad(
        {v: pls for v, pls in membership.items() if v in ours}, segs, len(ours))
    for pid in set(before) - set(segs):
        print(f"[서랍] 「{before[pid]}」 — 받은 영상의 40% 이상을 덮어 코너에서 뺐다")

    picked = sg.assign(membership, segs, sizes)
    rows = [{"video_id": v, "type_code": p} for v, p in picked.items() if v in ours]
    used = {r["type_code"] for r in rows}
    types = {pid: name for pid, name in segs.items() if pid in used}

    tid = cv.save_taxonomy(conn, ch["channel_id"], types, "playlist", "seg-v1",
                           axis="segment")
    cv.save_labels(conn, tid, rows, "seg-v1", "playlist")
    print()
    print(f"코너 {len(types)}개 · 우리 영상 {len(rows)}/{len(ours)}편에 배정 "
          f"({len(rows)/max(len(ours),1)*100:.0f}%)")
    print(f"코너 없음 {len(ours)-len(rows)}편 — 이 채널은 쇼츠를 재생목록으로 관리하지 않는다")
    _report(yt, args.db)
    return 0


def cmd_types(args) -> int:
    conn = connect(args.db)
    ch = conn.execute("SELECT channel_id, title FROM channels LIMIT 1").fetchone()
    if not ch:
        print("채널이 없다. 먼저 collect 를 돌려라.", file=sys.stderr)
        return 1

    if args.load:
        payload = json.loads(pathlib.Path(args.load).read_text(encoding="utf-8"))
        idx = json.loads(pathlib.Path(args.map).read_text(encoding="utf-8"))["map"]
        try:
            # import-titles 와 같은 함수를 쓴다. 검증·체계·라벨을 한 자리에
            # 두지 않으면 두 명령이 조금씩 다르게 저장하게 된다.
            tid, n, _ = lv.save_result(conn, ch["channel_id"], payload, idx, args.model)
        except cv.ValidationError as e:
            print("검증 실패 — 저장하지 않았다.", file=sys.stderr)
            print(f"  {e}", file=sys.stderr)
            return 1
        print(f"검증 통과: 유형 {len(payload['types'])}종 · 라벨 {n}건 저장 (taxonomy_id={tid})")

    tax = cv.active_taxonomy(conn, ch["channel_id"], getattr(args, "axis", "topic"))
    if not tax:
        print("유형 체계가 없다. --load 로 먼저 넣어라.", file=sys.stderr)
        return 1
    names = json.loads(tax["types_json"])
    run_id = uuid.uuid4().hex[:12]
    # 라벨을 넣을 때 쓴 모델 이름은 체계의 source 와 같다 (topic 은
    # claude-code-offline, segment 는 playlist). args.model 을 그대로 쓰면
    # 축을 바꿨을 때 아무것도 못 찾는다.
    mets = cv.aggregate(conn, ch["channel_id"], run_id, tax["taxonomy_id"],
                        tax["prompt_version"], tax["source"])
    if not mets:
        print("집계할 것이 없다. normalize 를 먼저 돌렸는지 확인해라.", file=sys.stderr)
        return 1

    print()
    print(f"[{ch['title']}] 유형별 성과 · taxonomy v{tax['version']}")
    for axis in ("shorts", "longform", "all"):
        g = sorted([m for m in mets if m["length_axis"] == axis],
                   key=lambda m: -(m["med_view_multiple"] or 0))
        if not g:
            continue
        print()
        print(f"── {AXIS_LABEL[axis]} ──")
        print(f"  {'유형':<12}{'편수':>5}{'조회중앙':>11}{'좋아요율':>9}"
              f"{'댓글율':>9}{'조회배수':>9}{'댓글배수':>9}")
        print("  " + "-" * 66)
        for m in g:
            def f(k, p=2, pc=False):
                v = m.get(k)
                if v is None:
                    return "—"
                return f"{v*100:.{p}f}%" if pc else f"{v:.{p}f}"
            print(f"  {names.get(m['type_code'], m['type_code']):<12}{m['video_count']:>5}"
                  f"{(m['med_view_count'] or 0):>11,.0f}{f('med_like_rate',2,True):>9}"
                  f"{f('med_comment_rate',3,True):>9}"
                  f"{f('med_view_multiple'):>9}{f('med_comment_rate_multiple'):>9}")

    masked = cv.masked_types(mets)
    if masked:
        print()
        print(f"  [주의] 합침이 가리고 있는 유형 {len(masked)}개 — "
              "쇼츠와 롱폼이 반대로 움직인다")
        for m in masked:
            print(f"    {names.get(m['type_code'], m['type_code']):<12}"
                  f"쇼츠 {m['shorts']:.2f}  vs  롱폼 {m['longform']:.2f}")
        print("    이 유형은 합침 줄을 믿지 말고 위 두 판을 봐라.")
    print()
    print(f"type_metrics 갱신 (run_id={run_id})")
    return 0


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _load_comments(args) -> tuple[list[dict], str]:
    if args.fixture:
        data = json.loads(pathlib.Path(args.fixture).read_text(encoding="utf-8"))
        return data["comments"], f"표본 {args.fixture}"
    conn = connect(args.db)
    q = ("SELECT comment_id, video_id, author_channel_id, text, like_count,"
         " analysis_eligible, exclusion_reason FROM comments")
    params: tuple = ()
    if args.video_id:
        q += " WHERE video_id=?"
        params = (args.video_id,)
    q += " ORDER BY published_at DESC"
    if args.limit:
        q += f" LIMIT {int(args.limit)}"
    return [dict(r) for r in conn.execute(q, params)], f"DB {args.db}"


def cmd_rules(args) -> int:
    comments, source = _load_comments(args)
    if not comments:
        print("댓글이 없다. 먼저 collect 를 돌리거나 --fixture 를 써라.", file=sys.stderr)
        return 1

    screens = screen_comments(comments, DEFAULT_CONFIG)
    by_id = {c["comment_id"]: c for c in comments}
    counts = summarize(screens)

    print(f"출처: {source}   댓글 {len(comments)}개\n")
    print("verdict 분포")
    for k in ("keep", "suspect_repeat", "irrelevant", "promo"):
        n = counts.get(k, 0)
        pct = n / len(comments) * 100
        print(f"  {k:<16} {n:>5}  {pct:5.1f}%  {'█' * int(pct / 2)}")

    dropped = [s for s in screens if s.verdict in ("promo", "irrelevant")]
    print(f"\n규칙이 확정 제외한 것 {len(dropped)}건 — 오탐이 있는지 눈으로 본다")
    for s in dropped[: args.show]:
        t = by_id[s.comment_id]["text"].replace("\n", " ")[:64]
        print(f"  [{s.verdict:<10}] {','.join(s.rule_flags):<24} {t}")

    flagged = [s for s in screens if s.verdict == "keep" and s.rule_flags]
    print(f"\n통과했지만 표시가 붙은 것 {len(flagged)}건 — 버리지 않고 LLM으로 간다")
    for s in flagged[: args.show]:
        t = by_id[s.comment_id]["text"].replace("\n", " ")[:64]
        print(f"  [{','.join(s.rule_flags):<12}] {t}")

    to_llm = sum(1 for s in screens if s.needs_llm)
    print(f"\nLLM으로 보낼 댓글 {to_llm}건 = 묶음 {-(-to_llm // 20)}회 호출")
    print("(규칙은 감성을 판단하지 않는다. 이모지만 있는 댓글도 여기 포함된다)")

    if args.save:
        conn = connect(args.db)
        for s in screens:
            conn.execute(
                """INSERT INTO comment_screens
                       (comment_id, prompt_version, model, rule_flags_json, verdict, screened_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       verdict=excluded.verdict, rule_flags_json=excluded.rule_flags_json""",
                (s.comment_id, RULES_VERSION, MODEL_RULE,
                 json.dumps(s.rule_flags, ensure_ascii=False), s.verdict, now()),
            )
        print(f"\ncomment_screens 에 저장했다 (prompt_version={RULES_VERSION}, model={MODEL_RULE})")
        # 규칙이 확정한 홍보(promo)만 spam_confirmed 로 분석에서 뺀다. 원문은 남는다.
        # 의심(suspect_repeat)은 빼지 않는다 — docs/design/comment-eligibility.md
        n_spam = apply_screen_exclusions(conn)
        print(f"확정 스팸 표시 {n_spam}건 (analysis_eligible=0, 원문 보존)")
    return 0


# --------------------------------------------------------------------------
# export-batch / import-batch  (API 없이 Claude Code가 판정하는 경로)
# --------------------------------------------------------------------------

def cmd_export_batch(args) -> int:
    comments, source = _load_comments(args)
    screens = {s.comment_id: s for s in screen_comments(comments, DEFAULT_CONFIG)}
    # 규칙을 통과한 것만 LLM으로 간다 (keep, suspect_repeat)
    # 분석 대상이 아닌 댓글(채널 자신·잘못 들어온 데이터·확정 스팸)은 라벨하지 않는다.
    # 표본 파일에는 이 열이 없으니 포함으로 본다 (docs/design/comment-eligibility.md)
    target = [c for c in comments
              if screens[c["comment_id"]].verdict in ("keep", "suspect_repeat")
              and c.get("analysis_eligible", 1)]
    if not target:
        print("판정할 댓글이 없다.", file=sys.stderr)
        return 1
    if args.all:
        # 영상마다 따로 묶는다. 판정에 영상 제목이 맥락으로 들어가므로
        # 한 묶음에 여러 영상의 댓글이 섞이면 그 맥락이 틀어진다.
        by_video: dict[str, list] = {}
        for c in target:
            by_video.setdefault(c.get("video_id") or "?", []).append(c)

        conn = connect(args.db)
        titles = {r["video_id"]: r["title"]
                  for r in conn.execute("SELECT video_id, title FROM videos")}
        out_dir = pathlib.Path(args.out)
        n = 0
        for vid, group in by_video.items():
            for i in range(0, len(group), args.size):
                n += 1
                chunk = group[i:i + args.size]
                bid = f"{args.batch_id}_{n:03d}"
                export_batch(chunk, titles.get(vid, "(제목 없음)"), bid, out_dir)
        print(f"출처: {source}")
        print(f"{len(target)}건을 {n}묶음으로 내보냈다 → {out_dir}")
        print(f"\n다음: 각 묶음의 .md 를 읽고 판정해 <batch>.result.json 으로 저장한 뒤")
        print(f"      python -m app.cli import-batch {args.batch_id}_001 --out {args.out}")
        return 0

    target = target[: args.size]

    title = args.video_title
    if not title and not args.fixture:
        row = connect(args.db).execute(
            "SELECT title FROM videos WHERE video_id=?", (target[0].get("video_id"),)
        ).fetchone()
        title = row["title"] if row else "(제목 없음)"
    if not title:
        data = json.loads(pathlib.Path(args.fixture).read_text(encoding="utf-8"))
        title = data.get("_video_title", "(제목 없음)")

    out_dir = pathlib.Path(args.out)
    path = export_batch(target, title, args.batch_id, out_dir)
    print(f"출처: {source}")
    print(f"내보냈다: {path}   (댓글 {len(target)}건)")
    print(f"\n다음: 이 파일을 Claude Code에 읽히고, 판정 결과를")
    print(f"      {out_dir / (args.batch_id + '.result.json')} 로 저장한 뒤")
    print(f"      python -m app.cli import-batch {args.batch_id} --out {args.out}")
    return 0


def cmd_import_batch(args) -> int:
    out_dir = pathlib.Path(args.out)
    map_path = out_dir / f"{args.batch_id}.map.json"
    res_path = out_dir / f"{args.batch_id}.result.json"
    for p in (map_path, res_path):
        if not p.exists():
            print(f"없다: {p}", file=sys.stderr)
            return 1

    mapping = json.loads(map_path.read_text(encoding="utf-8"))["map"]
    result = json.loads(res_path.read_text(encoding="utf-8"))
    try:
        rows = validate_result(result, mapping)
    except ValidationError as e:
        print(f"검증 실패 — 저장하지 않았다.\n  {e}", file=sys.stderr)
        return 1

    version = result.get("prompt_version", "v1")
    model = result.get("model", "claude-code-offline")
    print(f"검증 통과: {len(rows)}건  (prompt_version={version}, model={model})")

    if args.dry_run:
        for r in rows[: args.show]:
            print(f"  {r['idx']:>3}. {r['sentiment']:<9} conf={r['confidence']} "
                  f"{'[반어의심]' if r['sarcasm_suspect'] else '':<10} {','.join(r['topics'])}")
        print("\n--dry-run 이라 DB에 쓰지 않았다.")
        return 0

    conn = connect(args.db)
    written = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO comment_labels (comment_id, prompt_version, model,
                       sentiment, sentiment_confidence, is_sarcasm_suspect,
                       topics_json, labeled_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       sentiment=excluded.sentiment,
                       sentiment_confidence=excluded.sentiment_confidence,
                       is_sarcasm_suspect=excluded.is_sarcasm_suspect,
                       topics_json=excluded.topics_json,
                       labeled_at=excluded.labeled_at""",
                (r["comment_id"], version, model, r["sentiment"], r["confidence"],
                 int(r["sarcasm_suspect"]),
                 json.dumps(r["topics"], ensure_ascii=False), now()),
            )
            written += 1
        except Exception as e:      # 표본에서 온 comment_id는 DB에 없을 수 있다
            print(f"  건너뜀 {r['comment_id']}: {e}", file=sys.stderr)
    print(f"comment_labels 에 {written}건 저장했다.")
    return 0


# --------------------------------------------------------------------------
# export-titles / import-titles / import-taxonomy
#   3단계를 API 없이 도는 경로. 댓글의 export-batch·import-batch 와 같은 모양이다.
# --------------------------------------------------------------------------

def _first_channel(conn):
    ch = conn.execute("SELECT channel_id, title FROM channels LIMIT 1").fetchone()
    if not ch:
        print("채널이 없다. 먼저 collect 를 돌려라.", file=sys.stderr)
    return ch


def cmd_export_titles(args) -> int:
    """영상 제목을 유형 판정용 파일 하나로 내보낸다.

    `--for taxonomy` 는 체계를 제안받는 자리(라벨은 아직 붙이지 않는다),
    `--for types` 는 그 체계로 라벨을 붙이는 자리다. 순서가 중요하다 —
    자를 먼저 만들고 그 자로 잰다.
    """
    conn = connect(args.db)
    ch = _first_channel(conn)
    if not ch:
        return 1

    name = lv.PROMPT_TAXONOMY if args.target == "taxonomy" else lv.PROMPT_TYPES
    prompt = registry.get(name)
    if args.target == "taxonomy":
        # 체계는 채널의 모양에서 나온다. 이미 라벨된 편도 그 모양의 일부라
        # 라벨 유무로 거르지 않는다.
        rows = lv.titles(conn, ch["channel_id"], args.limit)
    else:
        rows = lv.pending(conn, ch["channel_id"], prompt.version, args.model,
                          args.limit)
    if not rows:
        print(f"내보낼 제목이 없다 (프롬프트 {prompt.version} · 모델 {args.model} "
              f"로 이미 전부 라벨돼 있다). 다시 붙이려면 --model 에 다른 이름을 준다.",
              file=sys.stderr)
        return 1

    out_dir = pathlib.Path(args.out)
    path = lv.export(conn, ch["channel_id"], name, args.batch_id, out_dir,
                     rows=rows, channel_title=ch["title"])
    est = lv.estimate(rows)
    print(f"[{ch['title']}] 제목 {est['videos']}편 · {est['chars']:,}자")
    print(f"내보냈다: {path}   (프롬프트 {prompt.name} {prompt.version})")
    nxt = "import-taxonomy" if args.target == "taxonomy" else "import-titles"
    print()
    print("다음: 이 파일을 Claude Code 에 읽히고, 판정 결과를")
    print(f"      {out_dir / (args.batch_id + '.result.json')} 로 저장한 뒤")
    print(f"      python -m app.cli {nxt} {args.batch_id} --out {args.out}")
    print("금전 비용 0.")
    return 0


def _batch_files(out_dir: pathlib.Path, batch_id: str, need_map: bool):
    """(대응표, 결과) 를 읽는다. 없으면 무엇이 없는지 말하고 None."""
    res_path = out_dir / f"{batch_id}.result.json"
    map_path = out_dir / f"{batch_id}.map.json"
    for p in ([map_path, res_path] if need_map else [res_path]):
        if not p.exists():
            print(f"없다: {p}", file=sys.stderr)
            return None
    mapping = (json.loads(map_path.read_text(encoding="utf-8"))["map"]
               if need_map else {})
    return mapping, json.loads(res_path.read_text(encoding="utf-8"))


def cmd_import_titles(args) -> int:
    """`video_label` 결과를 검증해 체계와 라벨을 함께 저장한다.

    `types --load` 도 같은 일을 하지만 그쪽은 집계까지 이어 달리므로,
    normalize 를 아직 안 돌린 상태에서는 저장에 성공하고도 1 로 끝난다.
    저장만 하고 싶을 때가 이 명령의 자리다. 저장 함수는 하나를 공유한다.
    """
    conn = connect(args.db)
    ch = _first_channel(conn)
    if not ch:
        return 1
    got = _batch_files(pathlib.Path(args.out), args.batch_id, need_map=True)
    if not got:
        return 1
    mapping, payload = got

    prompt = registry.get(lv.PROMPT_TYPES)
    problems = registry.check(prompt, payload)
    if problems:
        print("스키마 검증 실패 — 저장하지 않았다.", file=sys.stderr)
        for m in problems:
            print(f"  - {m}", file=sys.stderr)
        return 1
    try:
        tid, n, rows = lv.save_result(conn, ch["channel_id"], payload, mapping,
                                      args.model)
    except cv.ValidationError as e:
        print("검증 실패 — 저장하지 않았다.", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        return 1

    from collections import Counter
    counts = Counter(r["type_code"] for r in rows)
    names = payload["types"]
    print(f"검증 통과: 유형 {len(names)}종 · 라벨 {n}편 저장 "
          f"(taxonomy_id={tid}, model={args.model})")
    for code, c in counts.most_common():
        print(f"  {code:<10} {names.get(code, code):<18} {c:>5}편")
    print("\n다음: python -m app.cli types  — 유형별 성과를 세 판으로 본다")
    return 0


def cmd_import_taxonomy(args) -> int:
    """제안된 유형 체계를 사람이 보고 확정한다.

    **`--confirm` 없이는 저장하지 않는다.** 제안은 제안일 뿐이라, 아무도
    보지 않은 자에 영상 300편이 매달리면 그 위의 리포트까지 전부 그 자를
    믿게 된다. 확정은 사람이 하는 일이다.
    """
    conn = connect(args.db)
    ch = _first_channel(conn)
    if not ch:
        return 1
    got = _batch_files(pathlib.Path(args.out), args.batch_id, need_map=False)
    if not got:
        return 1
    _, payload = got

    prompt = registry.get(lv.PROMPT_TAXONOMY)
    problems = registry.check(prompt, payload)
    if problems:
        print("스키마 검증 실패 — 저장하지 않았다.", file=sys.stderr)
        for m in problems:
            print(f"  - {m}", file=sys.stderr)
        return 1

    # 편수는 라벨이 있어야 셀 수 있다. 제안 단계에는 없으므로 0 을 찍지
    # 않고 비워 둔다 — 0 은 "이 유형은 비었다"는 다른 말이다.
    counts = None
    if isinstance(payload.get("labels"), dict):
        from collections import Counter
        counts = Counter(payload["labels"].values())
    lv.describe(payload, counts)

    if not args.confirm:
        print("\n--confirm 이 없어 저장하지 않았다.")
        print("  체계를 받아들이려면 같은 명령에 --confirm 을 붙인다.")
        print("  받아들이면 이 채널의 topic 축 이전 체계는 비활성이 된다.")
        return 0

    tid = cv.save_taxonomy(conn, ch["channel_id"], payload["types"], args.model,
                           payload["taxonomy_version"], axis="topic")
    print(f"\n체계를 확정했다 (taxonomy_id={tid}, "
          f"taxonomy_version={payload['taxonomy_version']})")
    print("  라벨은 아직 없다. export-titles --for types 로 제목을 내보내 붙인다.")
    return 0


# --------------------------------------------------------------------------
# export-screen-batch / import-screen-batch / screen
#   4단계의 Claude 절반. 규칙 행 옆에 모델 행이 나란히 앉는다.
# --------------------------------------------------------------------------

def cmd_export_screen_batch(args) -> int:
    """규칙을 통과한 댓글을 선별용 파일로 내보낸다. 금전 비용 0.

    `screen` 이 API 로 보낼 것과 **같은 대상, 같은 본문**이다. 라벨링이
    그랬듯 선별도 돈을 쓰기 전에 오프라인에서 정확도를 재고 프롬프트를
    고칠 수 있어야 한다.
    """
    conn = connect(args.db)
    prompt = registry.get(sc.PROMPT_NAME)
    rows = sc.pending(conn, prompt.version, args.model, args.video_id, args.limit)
    if not rows:
        print(f"내보낼 댓글이 없다 (규칙을 통과한 것이 없거나 {prompt.version} · "
              f"{args.model} 로 이미 전부 판정됐다).", file=sys.stderr)
        return 1

    batches = sc.chunk(rows, args.size)
    out_dir = pathlib.Path(args.out)
    ids = []
    for i, group in enumerate(batches, 1):
        bid = args.batch_id if len(batches) == 1 else f"{args.batch_id}_{i:03d}"
        sc.export(group, group[0]["video_title"], bid, out_dir)
        ids.append(bid)
    est = sc.estimate(rows, args.size)
    print(f"댓글 {est['comments']}건을 {len(batches)}묶음으로 내보냈다 → {out_dir}")
    print(f"  프롬프트 {prompt.name} {prompt.version} · 모델 칸에 적을 이름 {args.model}")
    print()
    print("다음: 각 묶음의 .md 를 읽고 판정해 <batch>.result.json 으로 저장한 뒤")
    print(f"      python -m app.cli import-screen-batch {ids[0]} --out {args.out}")
    print("금전 비용 0.")
    return 0


def cmd_import_screen_batch(args) -> int:
    """선별 결과를 검증하고 comment_screens 에 넣는다.

    규칙 행은 그대로 둔다 — model 이 달라 다른 행이다.
    """
    got = _batch_files(pathlib.Path(args.out), args.batch_id, need_map=True)
    if not got:
        return 1
    mapping, result = got

    try:
        # 결과가 버전을 적어 왔으면 파일의 버전과 대조한다. 다른 버전으로
        # 판정한 것을 이 버전으로 저장하면 재현할 수 없는 행이 생긴다.
        prompt = registry.get(sc.PROMPT_NAME, version=result.get("prompt_version"))
    except registry.PromptError as e:
        print(f"{e}", file=sys.stderr)
        return 1

    try:
        rows = sc.validate_screens(result, mapping)
    except sc.ValidationError as e:
        print(f"검증 실패 — 저장하지 않았다.\n  {e}", file=sys.stderr)
        return 1

    model = result.get("model", "claude-code-offline")
    kept = sum(1 for r in rows if r["verdict"] == "keep")
    print(f"검증 통과: {len(rows)}건 (통과 {kept} · 버림 {len(rows) - kept}) "
          f"(prompt_version={prompt.version}, model={model})")
    for r in [x for x in rows if x["verdict"] == "drop"][: args.show]:
        print(f"  {r['idx']:>3}. drop  {r['reason'] or '(이유 없음)'}")

    if args.dry_run:
        print("\n--dry-run 이라 DB에 쓰지 않았다.")
        return 0

    conn = connect(args.db)
    n = sc.save_screens(conn, rows, prompt.version, model,
                        log=lambda m: print(m, file=sys.stderr))
    print(f"comment_screens 에 {n}건 저장했다 (규칙 행은 그대로 남는다).")
    return 0


def cmd_screen(args) -> int:
    """규칙을 통과한 댓글을 Anthropic API 로 다시 선별한다.

    **`label` 과 함께 금전 비용이 나가는 명령이다.** 대상 건수와 묶음 수를
    먼저 찍고 시작한다. 비용 없이 먼저 재 보려면 export-screen-batch 를 쓴다.
    """
    conn = connect(args.db)
    if args.dry_run:
        # 건수를 세는 데 API 키가 필요하지 않다. 키를 요구하면 "얼마나
        # 나갈지 먼저 보자"는 것을 키 받아온 다음에야 할 수 있게 된다.
        client = claude.ClaudeClient(
            api_key="", model=args.model or config.get("ANTHROPIC_MODEL",
                                                       claude.DEFAULT_MODEL))
    else:
        client = claude.from_config(config, model=args.model)
    try:
        p = sc.run(conn, client, model=args.model, video_id=args.video_id,
                   limit=args.limit, size=args.size, dry_run=args.dry_run)
    except claude.MissingPackage as e:
        print(e, file=sys.stderr)
        return 1
    except claude.ClaudeError as e:
        print(f"[중단] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 1 if p.failed else 0


def cmd_export_labels(args) -> int:
    """라벨 결과를 사람이 검수할 수 있는 표로 내보낸다.

    DB 파일을 주고받는 대신 이걸 쓴다 — 검수자가 보려는 것은 표 하나다.
    """
    conn = connect(args.db)
    rows = exports.fetch(conn, args.prompt_version, args.model, args.video_id)
    if not rows:
        print("내보낼 라벨이 없다. 먼저 import-batch 를 돌려라.", file=sys.stderr)
        return 1

    base = pathlib.Path(args.out)
    meta = {
        "_note": "댓글 원문 + 규칙 판정 + 감성·주제 라벨. 검수용이다.",
        "_exported_at": now(),
        "_source": "backend/data/yt_trend.db (comment_labels + comments + comment_screens)",
    }
    made = []
    if args.format in ("csv", "both"):
        made.append(exports.to_csv(rows, base.with_suffix(".csv")))
    if args.format in ("json", "both"):
        made.append(exports.to_json(rows, base.with_suffix(".json"), meta))

    print(f"라벨 {len(rows)}건 내보냄")
    for p in made:
        print(f"  {p}  ({p.stat().st_size:,} bytes)")

    from collections import Counter
    sent = Counter(r["sentiment"] for r in rows)
    vids = Counter(r["video_title"][:30] for r in rows)
    print()
    print("  감성  " + " · ".join(f"{k} {v}" for k, v in sent.most_common()))
    print("  영상  " + " · ".join(f"{k}… {v}건" for k, v in vids.most_common()))
    print()
    print("  CSV 는 UTF-8 BOM 이라 엑셀에서 한글이 깨지지 않는다.")
    return 0


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------

def cmd_stats(args) -> int:
    print(f"설정: {config.describe()}")
    print()
    conn = connect(args.db)
    for label, sql in (
        ("채널", "SELECT COUNT(*) FROM channels"),
        ("영상", "SELECT COUNT(*) FROM videos"),
        ("댓글", "SELECT COUNT(*) FROM comments"),
        ("규칙 판정", "SELECT COUNT(*) FROM comment_screens"),
    ):
        print(f"  {label:<10} {conn.execute(sql).fetchone()[0]:>7}")
    rows = conn.execute(
        "SELECT title, comments_newest_at, comments_complete FROM videos LIMIT 5"
    ).fetchall()
    if rows:
        print("\n영상별 댓글 커서 (앞 5개)")
        for r in rows:
            print(f"  {r['title'][:38]:<40} newest={r['comments_newest_at']} "
                  f"complete={r['comments_complete']}")
    return 0


# --------------------------------------------------------------------------
# prompts — 프롬프트 파일과 DB 가 어긋나지 않았는지
# --------------------------------------------------------------------------

def cmd_prompts(args) -> int:
    """저장소의 프롬프트와 DB 에 쌓인 버전을 대조한다.

    라벨을 재현할 수 있는지를 보는 명령이다. DB 에 `topics-v1` 로 300건이
    쌓여 있는데 그 v1 의 원문이 저장소에 없으면, 그 라벨은 아무도 다시
    만들 수 없다.
    """
    prompts = registry.all_prompts()
    if not prompts:
        print("app/prompts/ 에 프롬프트 파일이 없다.", file=sys.stderr)
        return 1

    print(f"프롬프트 {len(prompts)}개\n")
    for name, p in prompts.items():
        mark = "스키마 O" if p.schema else "스키마 X"
        print(f"  {name:<20} {p.version:<16} {mark:<9} {p.stage}")
        if args.show:
            head = p.system.strip().splitlines()[:args.show]
            for line in head:
                print(f"      | {line}")
            print()

    conn = connect(args.db)
    problems = registry.check_against_db(conn)
    print()
    if problems:
        print("DB 대조 — 재현할 수 없는 라벨이 있다:")
        for m in problems:
            print(f"  ! {m}")
        return 1
    print("DB 대조: 쌓인 라벨의 버전이 전부 저장소의 파일과 맞는다.")
    return 0


# --------------------------------------------------------------------------
# label — 5단계를 API 로 (유일하게 돈이 나가는 명령)
# --------------------------------------------------------------------------

def cmd_label(args) -> int:
    """규칙을 통과한 댓글을 Anthropic API 로 판정한다.

    **`screen` 과 함께 금전 비용이 나가는 명령이다.** 기본은 --dry-run
    이 아니지만, 대상 건수와 묶음 수를 먼저 찍고 시작한다.
    """
    conn = connect(args.db)
    client = claude.from_config(config, model=args.model)
    try:
        p = label_comments.run(
            conn, client, model=args.model, video_id=args.video_id,
            limit=args.limit, size=args.size, dry_run=args.dry_run)
    except claude.MissingPackage as e:
        print(e, file=sys.stderr)
        return 1
    except claude.ClaudeError as e:
        print(f"[중단] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 1 if p.failed else 0


# --------------------------------------------------------------------------
# Reaction Phase 3 — Reaction·Target 판정기와 평가 도구
#   결과는 독립 fresh 표본 검증 전까지 전부 「검증 전 AI 판정」이다.
#   원문이 들어가는 산출물(묶음·시트·rationale 이 든 라벨 파일)은 backend/data/ 에만.
# --------------------------------------------------------------------------

def _reaction_rows(args) -> tuple[list[dict], str] | None:
    """--input(raw JSON) 이 있으면 그 파일에서, 없으면 DB 에서 판정 대상을 고른다."""
    prompt = registry.get(lr.PROMPT_NAME)
    if args.input:
        rows, skipped = lr.load_raw_comments(args.input)
        done: set[str] = set()
        out = getattr(args, "labels_out", None)
        if out and pathlib.Path(out).exists():
            done = {x["comment_id"] for x in
                    json.loads(pathlib.Path(out).read_text(encoding="utf-8")).get("labels", [])}
        rows = [r for r in rows if r["comment_id"] not in done]
        if args.video_id:
            rows = [r for r in rows if r["video_id"] == args.video_id]
        if args.limit:
            rows = rows[: args.limit]
        return rows, (f"raw {args.input} (분석 제외 {skipped}건 뺌, "
                      f"라벨 파일에 이미 있는 {len(done)}건 뺌)")
    conn = connect(args.db)
    model = args.model or config.get("ANTHROPIC_MODEL", claude.DEFAULT_MODEL)
    return (lr.pending(conn, prompt.version, model, args.video_id, args.limit),
            f"DB {args.db}")


def cmd_export_reaction_batch(args) -> int:
    """판정 대상을 Reaction 판정용 파일로 내보낸다. 금전 비용 0."""
    prompt = registry.get(lr.PROMPT_NAME)
    if not args.model:
        args.model = "claude-code-offline"
    rows, source = _reaction_rows(args)
    if not rows:
        print(f"내보낼 댓글이 없다 ({source}).", file=sys.stderr)
        return 1
    batches = lr.chunk(rows, args.size)
    ids = []
    try:
        for i, group in enumerate(batches, 1):
            bid = args.batch_id if len(batches) == 1 else f"{args.batch_id}_{i:03d}"
            lr.export(group, bid, args.out)
            ids.append(bid)
    except lr.UnsafePath as e:
        print(e, file=sys.stderr)
        return 1
    print(f"출처: {source}")
    print(f"댓글 {len(rows)}건을 {len(batches)}묶음으로 내보냈다 → {args.out}")
    print(f"  프롬프트 {prompt.name} {prompt.version} · 결과는 검증 전 AI 판정")
    print("\n다음: 각 묶음의 .md 를 읽고 판정해 <batch>.result.json 으로 저장한 뒤")
    print(f"      python -m app.cli import-reaction-batch {ids[0]} --out {args.out}")
    return 0


def cmd_import_reaction_batch(args) -> int:
    """판정 결과를 검증해 comment_reactions (또는 --labels-out 라벨 파일) 에 넣는다."""
    out_dir = pathlib.Path(args.out)
    map_path = out_dir / f"{args.batch_id}.map.json"
    res_path = out_dir / f"{args.batch_id}.result.json"
    for p in (map_path, res_path):
        if not p.exists():
            print(f"없다: {p}", file=sys.stderr)
            return 1
    meta = json.loads(map_path.read_text(encoding="utf-8"))
    result = json.loads(res_path.read_text(encoding="utf-8"))
    try:
        prompt = registry.get(lr.PROMPT_NAME, version=result.get("prompt_version"))
        rows = lr.validate_reactions(result, meta["map"], meta.get("texts"))
    except registry.PromptError as e:
        print(e, file=sys.stderr)
        return 1
    except lr.ValidationError as e:
        print(f"검증 실패 — 저장하지 않았다.\n  {e}", file=sys.stderr)
        return 1

    model = result.get("model", "claude-code-offline")
    flagged = sum(1 for r in rows if r["review_flag"])
    print(f"검증 통과: {len(rows)}건 · review_flag {flagged}건 "
          f"(prompt_version={prompt.version}, model={model}) · 검증 전 AI 판정")
    if args.dry_run:
        print("--dry-run 이라 저장하지 않았다.")
        return 0
    if args.labels_out:
        try:
            n = lr.merge_into_label_file(args.labels_out, rows,
                                         prompt_version=prompt.version, model=model)
        except (lr.UnsafePath, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
        print(f"라벨 파일 {args.labels_out} 에 반영했다 (누적 {n}건).")
        return 0
    n = lr.save_reactions(connect(args.db), rows, prompt.version, model,
                          log=lambda m: print(m, file=sys.stderr))
    print(f"comment_reactions 에 {n}건 저장했다.")
    return 0


def cmd_label_reactions(args) -> int:
    """Reaction·Target 을 Anthropic API 로 판정한다. **금전 비용이 나간다.**"""
    if args.dry_run:
        client = claude.ClaudeClient(
            api_key="", model=args.model or config.get("ANTHROPIC_MODEL", claude.DEFAULT_MODEL))
    else:
        client = claude.from_config(config, model=args.model)
    try:
        rows, source = _reaction_rows(args)
        print(f"출처: {source}")
        if args.labels_out:
            lr.ensure_private_path(args.labels_out)
        conn = None if (args.input or args.dry_run) else connect(args.db)
        if args.input and not args.labels_out and not args.dry_run:
            print("--input 으로 판정할 때는 --labels-out 이 필요하다 "
                  "(raw 댓글은 DB 에 없을 수 있다).", file=sys.stderr)
            return 1
        p = lr.run(client, rows, conn=conn,
                   labels_out=args.labels_out if args.input else None,
                   model=args.model, size=args.size, dry_run=args.dry_run)
    except lr.UnsafePath as e:
        print(e, file=sys.stderr)
        return 1
    except claude.MissingPackage as e:
        print(e, file=sys.stderr)
        return 1
    except claude.ClaudeError as e:
        print(f"[중단] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 1 if p.failed else 0


def cmd_export_reactions(args) -> int:
    """DB 의 판정을 평가 도구가 읽는 라벨 파일로. rationale 이 들어가 data/ 에만 쓴다."""
    try:
        out = lr.ensure_private_path(args.out)
    except lr.UnsafePath as e:
        print(e, file=sys.stderr)
        return 1
    prompt = registry.get(lr.PROMPT_NAME)
    version = args.prompt_version or prompt.version
    model = args.model or config.get("ANTHROPIC_MODEL", claude.DEFAULT_MODEL)
    data = lr.labels_from_db(connect(args.db), version, model)
    if not data["labels"]:
        print(f"({version}, {model}) 로 저장된 판정이 없다.", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(data['labels'])}건 → {out} (검증 전 AI 판정)")
    return 0


def cmd_reaction_sheet(args) -> int:
    """raw JSON → 사람 판정 시트 HTML. 원문이 들어가 backend/data/ 밖이면 거부한다."""
    try:
        info = reaction_sheet.write_sheet(args.raw, args.out)
    except lr.UnsafePath as e:
        print(e, file=sys.stderr)
        return 1
    print(f"시트 {info['path']}")
    print(f"  댓글 {info['comments']}건 (분석 제외로 뺀 것 {info['skipped_ineligible']}건) · "
          f"sheet_id {info['sheet_id']}")
    print("  브라우저로 열어 판정하고 「JSON 내보내기」 결과를 backend/data/ 아래에 둔다.")
    print("  이 HTML 에는 댓글 원문이 들어 있다 — 커밋하지 않는다.")
    return 0


def cmd_reaction_eval(args) -> int:
    """두 라벨 파일의 일치도. 출력은 숫자와 comment_id 뿐이다."""
    try:
        a, meta_a = reaction_eval.load_labels(args.a)
        b, meta_b = reaction_eval.load_labels(args.b)
    except lr.ValidationError as e:
        print(f"입력 검증 실패 — 계산하지 않았다.\n  {e}", file=sys.stderr)
        return 1
    report = reaction_eval.evaluate(a, b)
    if report["n_compared"] == 0:
        print("공통 comment_id 가 없다.", file=sys.stderr)
        return 1
    print(reaction_eval.render(report, meta_a, meta_b, max_ids=args.max_ids))
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"a": meta_a, "b": meta_b, **report},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON → {out}")
    return 0


# --------------------------------------------------------------------------
# report — 6단계 집계와 결론
# --------------------------------------------------------------------------

def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def cmd_report(args) -> int:
    conn = connect(args.db)
    ch = conn.execute("SELECT channel_id, title FROM channels LIMIT 1").fetchone()
    if not ch:
        print("채널이 없다. 먼저 collect 를 돌려라.", file=sys.stderr)
        return 1

    client = None
    if args.online:
        try:
            client = claude.from_config(config, model=args.model)
        except claude.MissingPackage as e:
            print(e, file=sys.stderr)
            return 1

    run_id = uuid.uuid4().hex[:12]
    reports = aggregate.run(conn, ch["channel_id"], run_id, client=client)
    if not reports:
        print("리포트를 만들 재료가 없다. normalize · types 를 먼저 돌려라.",
              file=sys.stderr)
        return 1

    print(f"\n{ch['title']} · run={run_id}")
    for r in reports:
        lab = aggregate.LENGTH_LABEL[r["length_axis"]]
        ax = aggregate.AXIS_LABEL[r["axis"]]
        print()
        print("=" * 74)
        print(f"[{lab}]  {ax} 축 · {r['completeness']} · 문장 출처 {r['conclusion_source']}")
        print(f"  {r['axis_reason']}")
        print()
        for line in _wrap(r["conclusion"], 70):
            print(f"  {line}")

        if args.verbose:
            cov = r["coverage"]
            print()
            print(f"  커버리지  주제 {cov['topic']:.0%} · 코너 {cov['segment']:.0%}")
            rvp = r["recent_vs_prior"]
            print(f"  전후 비교  {rvp['basis']}")
            nm = r["names"]
            for code, d in sorted(rvp["types"].items(),
                                  key=lambda kv: -abs(kv[1]["delta"]))[:5]:
                print(f"    {nm.get(code, code)[:20]:<22} {d['prior']:.2f} → "
                      f"{d['recent']:.2f}  ({d['delta']:+.2f})")
            rows = [c for c in r["comment_rows"] if c["valid_comment_count"]]
            if rows:
                print("  댓글이 있는 유형")
                for c in rows:
                    print(f"    {nm.get(c['type_code'], c['type_code'])[:20]:<22} "
                          f"긍정 {_pct(c['positive_ratio'])} · "
                          f"부정 {_pct(c['negative_ratio'])} · {c['basis']}")

    if client is not None:
        print()
        print("  " + client.usage.describe(client.model))
    print()
    print(f"reports · type_comment_metrics · video_comment_metrics 에 저장했다 (run={run_id})")
    return 0


def _wrap(text: str, width: int) -> list[str]:
    """한글 폭을 대충 맞춘 줄바꿈. 문장 단위로 끊는다."""
    out: list[str] = []
    line = ""
    for sentence in text.split(". "):
        s = sentence if sentence.endswith(".") else sentence + "."
        if len(line) + len(s) > width and line:
            out.append(line.strip())
            line = ""
        line += s + " "
    if line.strip():
        out.append(line.strip())
    return out


def main() -> int:
    config.setup_console()
    p = argparse.ArgumentParser(prog="yt-trend", description=__doc__)
    config.load_env()
    p.add_argument("--db", default=config.get("DB_PATH", DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="채널 URL → SQLite (비용 0, YouTube 키 필요)")
    c.add_argument("url")
    c.add_argument("--max-videos", type=int, default=50)
    c.add_argument("--max-comments", type=int, default=2000)
    c.add_argument("--no-comments", action="store_true",
                   help="영상 메타·통계만 받는다. 조회 배수의 분모를 만들 때 쓴다")
    c.set_defaults(fn=cmd_collect)

    v = sub.add_parser("collect-video", help="영상 URL 하나만 → SQLite (약 5유닛)")
    v.add_argument("url", help="watch?v=… / youtu.be/… / shorts/… / 맨 영상 ID")
    v.add_argument("--max-comments", type=int, default=2000)
    v.set_defaults(fn=cmd_collect_video)

    n = sub.add_parser("normalize",
                       help="길이 축·좋아요율·댓글율·조회 배수·댓글율 배수 (비용 0)")
    n.add_argument("--show", type=int, default=10)
    n.set_defaults(fn=cmd_normalize)

    g = sub.add_parser("engagement",
                       help="댓글 참여가 호응인지 논쟁인지 가른다 (라벨 필요, 비용 0)")
    g.add_argument("--prompt-version", help="특정 라벨 버전만. 없으면 DB의 전 조합")
    g.add_argument("--model", help="특정 모델만. 없으면 DB의 전 조합")
    g.add_argument("--show", type=int, default=10)
    g.set_defaults(fn=cmd_engagement)

    r = sub.add_parser("rules", help="규칙 필터를 돌려보고 무엇이 걸렸는지 본다 (비용 0)")
    r.add_argument("--fixture", help="DB 대신 표본 JSON 을 쓴다")
    r.add_argument("--video-id")
    r.add_argument("--limit", type=int)
    r.add_argument("--show", type=int, default=20, help="예시로 보여줄 건수")
    r.add_argument("--save", action="store_true", help="comment_screens 에 저장")
    r.set_defaults(fn=cmd_rules)

    e = sub.add_parser("export-batch", help="댓글 묶음을 판정용 파일로 (API 불필요)")
    e.add_argument("batch_id")
    e.add_argument("--fixture", help="DB 대신 표본 JSON 을 쓴다")
    e.add_argument("--video-id")
    e.add_argument("--video-title")
    e.add_argument("--limit", type=int)
    e.add_argument("--size", type=int, default=20, help="묶음 크기")
    e.add_argument("--out", default="./data/batches")
    e.add_argument("--all", action="store_true",
                   help="전체를 size 단위 묶음으로 쪼개 내보낸다 (영상별로 나눔)")
    e.set_defaults(fn=cmd_export_batch)

    i = sub.add_parser("import-batch", help="판정 결과를 검증하고 저장")
    i.add_argument("batch_id")
    i.add_argument("--out", default="./data/batches")
    i.add_argument("--dry-run", action="store_true", help="검증만 하고 DB에 안 씀")
    i.add_argument("--show", type=int, default=20)
    i.set_defaults(fn=cmd_import_batch)

    sg_p = sub.add_parser("segments", help="재생목록에서 코너를 읽어 유형 축으로 (YouTube 키 필요)")
    sg_p.set_defaults(fn=cmd_segments)

    ty = sub.add_parser("types", help="영상 유형별 성과 — 쇼츠/롱폼/합침 세 판")
    ty.add_argument("--axis", choices=("topic", "segment"), default="topic")
    ty.add_argument("--load", help="유형 라벨 JSON 을 검증해 넣는다")
    ty.add_argument("--map", help="번호→video_id 대응표 JSON")
    ty.add_argument("--model", default="claude-code-offline")
    ty.set_defaults(fn=cmd_types)

    et = sub.add_parser("export-titles",
                        help="영상 제목을 유형 판정용 파일로 (API 불필요, 비용 0)")
    et.add_argument("batch_id")
    et.add_argument("--for", dest="target", choices=("types", "taxonomy"),
                    default="types",
                    help="types 는 라벨을 붙일 묶음, taxonomy 는 체계를 제안받을 묶음")
    et.add_argument("--limit", type=int, help="이만큼만 (처음 볼 때 쓴다)")
    et.add_argument("--model", default="claude-code-offline",
                    help="types 일 때 '이 모델로 아직 라벨 안 된 것'을 고르는 기준")
    et.add_argument("--out", default="./data/batches/titles")
    et.set_defaults(fn=cmd_export_titles)

    it = sub.add_parser("import-titles",
                        help="유형 라벨 결과를 검증하고 체계와 함께 저장 (비용 0)")
    it.add_argument("batch_id")
    it.add_argument("--out", default="./data/batches/titles")
    it.add_argument("--model", default="claude-code-offline")
    it.set_defaults(fn=cmd_import_titles)

    itx = sub.add_parser("import-taxonomy",
                         help="제안된 유형 체계를 보고 --confirm 일 때만 저장 (비용 0)")
    itx.add_argument("batch_id")
    itx.add_argument("--out", default="./data/batches/titles")
    itx.add_argument("--model", default="claude-code-offline",
                     help="체계의 source 로 적을 이름")
    itx.add_argument("--confirm", action="store_true",
                     help="이것 없이는 저장하지 않는다. 체계는 사람이 확정한다")
    itx.set_defaults(fn=cmd_import_taxonomy)

    es = sub.add_parser("export-screen-batch",
                        help="댓글 묶음을 선별용 파일로 (API 불필요, 비용 0)")
    es.add_argument("batch_id")
    es.add_argument("--video-id")
    es.add_argument("--limit", type=int)
    es.add_argument("--size", type=int, default=20, help="묶음 크기")
    es.add_argument("--model", default="claude-code-offline",
                    help="'이 모델로 아직 선별 안 된 것'을 고르는 기준")
    es.add_argument("--out", default="./data/batches/screen")
    es.set_defaults(fn=cmd_export_screen_batch)

    isb = sub.add_parser("import-screen-batch", help="선별 결과를 검증하고 저장 (비용 0)")
    isb.add_argument("batch_id")
    isb.add_argument("--out", default="./data/batches/screen")
    isb.add_argument("--dry-run", action="store_true", help="검증만 하고 DB에 안 씀")
    isb.add_argument("--show", type=int, default=20, help="버린 것 중 보여줄 건수")
    isb.set_defaults(fn=cmd_import_screen_batch)

    sn = sub.add_parser("screen",
                        help="규칙을 통과한 댓글을 API 로 다시 선별 — 돈이 나간다")
    sn.add_argument("--video-id")
    sn.add_argument("--limit", type=int, help="이만큼만 (처음 붙일 때 쓴다)")
    sn.add_argument("--size", type=int, default=20, help="묶음 크기")
    sn.add_argument("--model", help="기본은 .env 의 ANTHROPIC_MODEL")
    sn.add_argument("--dry-run", action="store_true",
                    help="대상 건수와 묶음 수만 세고 호출하지 않는다 (키 없이도 돈다)")
    sn.set_defaults(fn=cmd_screen)

    x = sub.add_parser("export-labels", help="라벨 결과를 CSV/JSON 으로 (검수·공유용)")
    x.add_argument("--out", default="./exports/comment-labels",
                   help="확장자 없이. .csv / .json 이 붙는다")
    x.add_argument("--format", choices=("csv", "json", "both"), default="both")
    x.add_argument("--prompt-version")
    x.add_argument("--model")
    x.add_argument("--video-id")
    x.set_defaults(fn=cmd_export_labels)

    rp = sub.add_parser("report", help="6단계 집계와 결론 문장 — 쇼츠/롱폼/합침 세 판")
    rp.add_argument("--online", action="store_true",
                    help="결론 문장을 Claude 가 다듬는다 (ANTHROPIC_API_KEY 필요)")
    rp.add_argument("--model", help="--online 일 때 쓸 모델")
    rp.add_argument("-v", "--verbose", action="store_true",
                    help="커버리지·전후 비교·유형별 댓글까지")
    rp.set_defaults(fn=cmd_report)

    pr = sub.add_parser("prompts", help="프롬프트 파일과 DB 버전 대조 (비용 0)")
    pr.add_argument("--show", type=int, default=0, help="각 프롬프트 앞 N줄도 본다")
    pr.set_defaults(fn=cmd_prompts)

    lb = sub.add_parser("label",
                        help="댓글 감성·주제를 API 로 판정 — screen 과 함께 돈이 나간다")
    lb.add_argument("--video-id")
    lb.add_argument("--limit", type=int, help="이만큼만 (처음 붙일 때 쓴다)")
    lb.add_argument("--size", type=int, default=20, help="묶음 크기")
    lb.add_argument("--model", help="기본은 .env 의 ANTHROPIC_MODEL")
    lb.add_argument("--dry-run", action="store_true",
                    help="대상 건수와 묶음 수만 세고 호출하지 않는다")
    lb.set_defaults(fn=cmd_label)

    # -- Reaction Phase 3 -------------------------------------------------
    def reaction_source(sp, default_model=None):
        sp.add_argument("--input", help="raw 수집 JSON ({comments:[...]}). 없으면 DB")
        sp.add_argument("--video-id")
        sp.add_argument("--limit", type=int, help="이만큼만")
        sp.add_argument("--size", type=int, default=20, help="묶음 크기")
        sp.add_argument("--model", default=default_model,
                        help="'이 모델로 아직 판정 안 된 것'을 고르는 기준")

    erb = sub.add_parser("export-reaction-batch",
                         help="Reaction·Target 판정용 묶음 파일 (API 불필요, 비용 0)")
    erb.add_argument("batch_id")
    reaction_source(erb, "claude-code-offline")
    erb.add_argument("--out", default="./data/batches/reaction",
                     help="원문이 들어가 backend/data/ 아래만 허용")
    erb.set_defaults(fn=cmd_export_reaction_batch, labels_out=None)

    irb = sub.add_parser("import-reaction-batch",
                         help="Reaction 판정 결과를 검증하고 저장 (비용 0)")
    irb.add_argument("batch_id")
    irb.add_argument("--out", default="./data/batches/reaction")
    irb.add_argument("--labels-out",
                     help="DB 대신 이 라벨 파일에 반영 (fresh raw 표본용, backend/data/ 아래)")
    irb.add_argument("--dry-run", action="store_true", help="검증만 하고 저장하지 않음")
    irb.set_defaults(fn=cmd_import_reaction_batch)

    lrp = sub.add_parser("label-reactions",
                         help="Reaction·Target 을 API 로 판정 — 돈이 나간다 (검증 전 AI 판정)")
    reaction_source(lrp)
    lrp.add_argument("--labels-out",
                     help="--input 과 함께: DB 대신 이 라벨 파일에 (backend/data/ 아래)")
    lrp.add_argument("--dry-run", action="store_true",
                     help="대상 건수와 묶음 수만 세고 호출하지 않는다 (키 없이도 돈다)")
    lrp.set_defaults(fn=cmd_label_reactions)

    erx = sub.add_parser("export-reactions", help="DB 의 Reaction 판정 → 평가용 라벨 파일")
    erx.add_argument("--out", default="./data/reaction-labels/ai.json")
    erx.add_argument("--prompt-version")
    erx.add_argument("--model", help="기본은 .env 의 ANTHROPIC_MODEL")
    erx.set_defaults(fn=cmd_export_reactions)

    rsh = sub.add_parser("reaction-sheet", help="사람 판정 시트 HTML (원문 포함 → backend/data/ 만)")
    rsh.add_argument("raw", help="raw 수집 JSON")
    rsh.add_argument("--out", default="./data/reaction-sheets/sheet.html")
    rsh.set_defaults(fn=cmd_reaction_sheet)

    rev = sub.add_parser("reaction-eval", help="두 라벨 파일의 일치도 (A=기준, B=비교)")
    rev.add_argument("a")
    rev.add_argument("b")
    rev.add_argument("--out", help="JSON 보고서 경로 (숫자와 comment_id 만 담긴다)")
    rev.add_argument("--max-ids", type=int, default=50, help="화면에 보일 어긋난 ID 수")
    rev.set_defaults(fn=cmd_reaction_eval)

    s = sub.add_parser("stats", help="수집 현황과 설정 상태")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
