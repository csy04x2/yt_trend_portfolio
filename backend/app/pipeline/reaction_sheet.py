"""Reaction Phase 3 — 사람 판정 시트 생성기.

raw 수집 JSON 을 받아 **혼자 열리는 HTML 파일 하나**를 만든다. 사람이 브라우저로
열어 댓글마다 R·T 코드를 고르고, 평가 도구(`reaction_eval`)가 읽는 JSON 으로
내보낸다. 서버도 네트워크도 쓰지 않는다.

## 이 파일에는 댓글 원문이 들어간다

그래서 `backend/data/` (gitignored) 아래에만 쓴다. 다른 경로를 주면 거부한다
(`label_reactions.ensure_private_path`). 내보낸 판정 JSON 에는 원문이 없지만
메모(rationale)에 사람이 원문을 옮겨 적을 수 있으므로 그것도 data/ 에 둔다.

## 블라인드

시트에는 AI 판정을 싣지 않는다. 사람 판정이 AI 판정을 보고 따라가면 일치도가
부풀어 검증 의미가 없어진다. 분석 대상에서 제외(analysis_eligible=false)로
확정된 댓글도 싣지 않는다.

## 시트가 지키는 규칙

AI 검증기(`label_reactions.check_label`)와 같다. 규칙에 맞지 않는 댓글은
「미완료」로 남고 내보낸 JSON 의 `labels` 에 들어가지 않는다 (`incomplete_ids` 로만
나간다).

- Reaction 은 코드 선택 / 없음(None) / 판정 불가(UNKNOWN) 중 하나를 **명시적으로** 고른다
  — 아무것도 안 고른 것과 None 을 구분하기 위해서다
- UNKNOWN 은 혼자만, Reaction 이 있으면 Target 필수
- timestamp 는 원문에 글자 그대로 있는 것만 (원문에서 찾은 값을 미리 채워 둔다)
- review 표시를 켜면 사유 필수
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

from app.pipeline.label_reactions import (
    DATA_DIR,
    LABEL_FORMAT,
    REACTION_NAMES,
    REVIEW_REASONS,
    TARGET_NAMES,
    ensure_private_path,
    literal_timestamps,
    load_raw_comments,
)

# 시트 안에서 보는 짧은 정의. 기준 문서 문장을 줄인 것이며 경계는 문서가 정본이다.
REACTION_HINTS = {
    "R1": "질·능력·완성도·유용성 등에 대한 긍정적 평가 (단순 애정·응원은 R2)",
    "R2": "인물·채널을 향한 호감·애정·애착·응원·팬심 (품질 칭찬은 R1)",
    "R3": "웃음·재미와 함께 따라하기·재연·변형·말장난·댓글 놀이·창작적 상상 "
          "(장면 포착만으로 자동 부여 안 함)",
    "R4": "콘텐츠·품질·제작·진행 등에 대한 부정적 평가·비판·불만",
    "R5": "계속 보거나 소비하는 데 느끼는 어려움·부담·이탈·스킵·회피 (일반 비판은 R4)",
    "R6": "이상함·혼란·뜻밖임·이해 안 됨 (답을 얻으려는 실제 질문은 R7)",
    "R7": "실질적 인지적 기여: 의견·해석·추론·정보·경험 연결·실제 질문 "
          "(단순 관찰·장면 포착·짧은 연상은 아님, H1)",
    "R8": "제작자의 미래 행동(콘텐츠·구성·출연·진행)에 대한 요청·제안",
    "R9": "현실 행동을 했다/하겠다, 또는 개인·집단·기관의 구체적 현실 행동 요구·촉구 "
          "(단순 의견·해석 아님, 제작 요청은 R8)",
    "R10": "조회·댓글·좋아요 등 성과를 직접 높이려는 참여나 그 요청 (성과 관찰만은 아님)",
}
TARGET_HINTS = {
    "T1": "특정 요소보다 영상·콘텐츠 전체",
    "T2": "주제·정보·사건·주장·이야기·소재 등 내용 자체",
    "T3": "출연자·진행자·게스트 등 영상 속 사람",
    "T4": "편집·자막·촬영·연출·음악·표현 방식",
    "T5": "채널 자체·팬덤·댓글 공동체·채널의 역사·관계적 맥락",
    "UNKNOWN": "댓글만으로 대상을 판정할 수 없음",
}


def _embed(obj) -> str:
    """<script type=application/json> 안에 넣어도 태그가 닫히지 않게.

    `<` 를 전부 JSON 유니코드 이스케이프로 바꾼다. 댓글 원문에 `</script>` 나
    `<!--` 가 들어 있어도 태그로 읽히지 않고, JSON.parse 결과는 원문 그대로다.
    """
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def build_sheet(comments: list[dict], *, sheet_id: str, title: str = "Reaction 사람 판정 시트") -> str:
    items = [{
        "comment_id": c["comment_id"],
        "video_id": c.get("video_id") or "",
        "video_title": c.get("video_title") or "",
        "channel_name": c.get("channel_name") or "",
        "text": c.get("text") or "",
        "timestamps": literal_timestamps(c.get("text") or ""),
    } for c in comments]
    config = {
        "sheet_id": sheet_id,
        "format": LABEL_FORMAT,
        "reactions": [{"code": k, "name": v, "hint": REACTION_HINTS[k]}
                      for k, v in REACTION_NAMES.items()],
        "targets": [{"code": k, "name": v, "hint": TARGET_HINTS[k]}
                    for k, v in TARGET_NAMES.items()],
        "review_reasons": list(REVIEW_REASONS),
    }
    return (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__CONFIG__", _embed(config))
            .replace("__ITEMS__", _embed(items)))


def write_sheet(raw_path, out_path, *, base: pathlib.Path = DATA_DIR) -> dict:
    """raw JSON → 시트 HTML. 원문이 들어가므로 base(backend/data) 밖이면 거부한다."""
    out = ensure_private_path(out_path, base)
    comments, skipped = load_raw_comments(raw_path)
    ids = "\n".join(sorted(c["comment_id"] for c in comments))
    sheet_id = "sheet-" + hashlib.sha256(ids.encode("utf-8")).hexdigest()[:12]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_sheet(comments, sheet_id=sheet_id), encoding="utf-8")
    return {"path": str(out), "comments": len(comments), "skipped_ineligible": skipped,
            "sheet_id": sheet_id,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --ink:#1d1d1f; --mute:#6e6e73; --line:#d2d2d7; --bg:#f5f5f7; --card:#fff;
          --accent:#0a5bd3; --warn:#b3261e; --ok:#1b7f3b; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font: 15px/1.55 "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid var(--line);
           padding:10px 16px; display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; }
  header h1 { font-size:16px; margin:0; font-weight:700; }
  header .progress { font-weight:700; }
  header input[type=text] { padding:4px 8px; border:1px solid var(--line); border-radius:6px; }
  button { font:inherit; padding:5px 12px; border:1px solid var(--line); border-radius:6px;
           background:#fff; cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
  main { max-width:980px; margin:0 auto; padding:16px; }
  details.guide { background:var(--card); border:1px solid var(--line); border-radius:10px;
                  padding:10px 14px; margin-bottom:16px; }
  details.guide summary { cursor:pointer; font-weight:700; }
  .guide dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 12px; margin:8px 0; }
  .guide dt { font-weight:700; }
  .guide dd { margin:0; color:var(--mute); }
  .card { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--line);
          border-radius:10px; padding:12px 14px; margin-bottom:12px; }
  .card.done { border-left-color:var(--ok); }
  .card.bad { border-left-color:var(--warn); }
  .meta { color:var(--mute); font-size:13px; margin-bottom:6px; word-break:break-all; }
  .text { white-space:pre-wrap; word-break:break-word; font-size:16px; padding:8px 10px;
          background:var(--bg); border-radius:8px; margin-bottom:10px; }
  .row { display:flex; flex-wrap:wrap; gap:4px 6px; align-items:center; margin:6px 0; }
  .row > b { min-width:84px; font-size:13px; }
  label.chip { display:inline-flex; gap:4px; align-items:center; border:1px solid var(--line);
               border-radius:999px; padding:2px 10px; font-size:13px; cursor:pointer; user-select:none; }
  label.chip:has(input:checked) { background:#e8f0fe; border-color:var(--accent); font-weight:600; }
  label.chip.special:has(input:checked) { background:#fff4e5; border-color:#c77700; }
  .row input[type=text], .row select { padding:3px 8px; border:1px solid var(--line); border-radius:6px; font:inherit; font-size:13px; }
  .row input.wide { flex:1 1 320px; }
  .problems { color:var(--warn); font-size:13px; margin-top:4px; }
  textarea#out { width:100%; min-height:120px; font:12px/1.4 ui-monospace, Consolas, monospace; }
  .filter { display:flex; gap:8px; align-items:center; font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="progress" id="progress"></span>
  <label>판정자 <input type="text" id="labeler" placeholder="이름 또는 이니셜"></label>
  <span class="filter"><label><input type="checkbox" id="onlyTodo"> 미완료만 보기</label></span>
  <button class="primary" id="exportBtn">JSON 내보내기</button>
  <button id="importBtn" type="button">이어서 하기(JSON 불러오기)</button>
  <input type="file" id="importFile" accept=".json,application/json" hidden>
</header>
<main>
  <details class="guide">
    <summary>판정 기준 요약 (정본: docs/reaction-phase1-checkpoint.md · docs/reaction-track-closeout-2026-09-17.md)</summary>
    <p>Reaction 복수 선택 가능. 성립하는 Reaction 이 없으면 <b>없음(None)</b>, 정보 부족·모호성으로 판정할 수 없으면 <b>판정 불가(UNKNOWN)</b>. None 과 UNKNOWN 은 다르다.
       Target 복수 선택 가능. Reaction 이 있으면 Target 이 필요하다(모르면 UNKNOWN).
       단순 관찰·장면 포착·짧은 연상은 R7 이 아니다(H1). 장면·timestamp 는 Reaction·Target 이 아니며, 원문에 적힌 timestamp 만 기록한다(H2).
       긍정/부정 감성은 Reaction 이 아니다.</p>
    <dl id="guideR"></dl>
    <dl id="guideT"></dl>
    <p>review 사유: APPLICATION_ERROR(기준은 분명하나 댓글 이해가 불확실) · DEFINITION_BOUNDARY(두 정의의 경계) · STRUCTURE_CANDIDATE(현재 구조 어디에도 자연스럽게 안 들어감).</p>
  </details>
  <div id="list"></div>
  <details class="guide" id="outWrap">
    <summary>내보낸 JSON (다운로드가 막혔을 때 복사해서 backend/data/ 아래 파일로 저장)</summary>
    <textarea id="out" readonly></textarea>
  </details>
</main>
<script type="application/json" id="config">__CONFIG__</script>
<script type="application/json" id="items">__ITEMS__</script>
<script>
(function () {
  "use strict";
  var CFG = JSON.parse(document.getElementById("config").textContent);
  var ITEMS = JSON.parse(document.getElementById("items").textContent);
  var KEY = "reaction-sheet:" + CFG.sheet_id;
  var state = {};
  var store = null;
  try { store = window.localStorage; } catch (e) { store = null; }

  function blank(it) {
    return { mode: "", reactions: [], targets: [], timestamps: it.timestamps.join(", "),
             review_flag: false, review_reason: "", rationale: "" };
  }
  ITEMS.forEach(function (it) { state[it.comment_id] = blank(it); });
  try {
    var saved = store && JSON.parse(store.getItem(KEY) || "null");
    if (saved && saved.state) {
      Object.keys(saved.state).forEach(function (k) { if (state[k]) state[k] = saved.state[k]; });
      document.getElementById("labeler").value = saved.labeler || "";
    }
  } catch (e) { /* 저장값이 없거나 깨졌으면 새로 시작 */ }

  function save() {
    try { store && store.setItem(KEY, JSON.stringify({ labeler: document.getElementById("labeler").value, state: state })); }
    catch (e) { /* 저장 불가 환경 — 내보내기로 보존 */ }
  }

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  // AI 검증기(label_reactions.check_label)와 같은 규칙
  function check(it, s) {
    var p = [];
    var reactions = s.mode === "codes" ? s.reactions.slice() : s.mode === "unknown" ? ["UNKNOWN"] : [];
    if (!s.mode) p.push("Reaction 을 고르거나 없음(None)/판정 불가(UNKNOWN) 를 고른다");
    if (s.mode === "codes" && !s.reactions.length) p.push("Reaction 코드를 하나 이상 고른다");
    if (s.targets.indexOf("UNKNOWN") >= 0 && s.targets.length > 1) p.push("Target UNKNOWN 은 다른 코드와 섞을 수 없다");
    if (reactions.length && !s.targets.length) p.push("Reaction 이 있으면 Target 이 필요하다 (모르면 UNKNOWN)");
    var stamps = s.timestamps.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
    stamps.forEach(function (t) { if (it.text.indexOf(t) < 0) p.push("timestamp '" + t + "' 가 원문에 없다 (H2)"); });
    if (s.review_flag && CFG.review_reasons.indexOf(s.review_reason) < 0) p.push("review 표시를 켰으면 사유를 고른다");
    return { problems: p, label: { comment_id: it.comment_id, reactions: reactions, targets: s.targets.slice(),
             explicit_timestamps: stamps, review_flag: !!s.review_flag,
             review_reason: s.review_flag ? s.review_reason : null, rationale: s.rationale || "" } };
  }

  function order(list, codes) {
    return codes.filter(function (c) { return list.indexOf(c) >= 0; });
  }

  var cards = {};
  function render() {
    var list = document.getElementById("list");
    ITEMS.forEach(function (it, n) {
      var s = state[it.comment_id];
      var card = el("section", { "class": "card" });
      card.appendChild(el("div", { "class": "meta" },
        "#" + (n + 1) + " · " + it.comment_id + " · " + it.channel_name + " · " + it.video_title));
      card.appendChild(el("div", { "class": "text" }, it.text));

      var rRow = el("div", { "class": "row" }); rRow.appendChild(el("b", {}, "Reaction"));
      var rCodes = CFG.reactions.map(function (r) { return r.code; });
      CFG.reactions.forEach(function (r) {
        var lab = el("label", { "class": "chip", title: r.hint });
        var cb = el("input", { type: "checkbox" }); cb.checked = s.mode === "codes" && s.reactions.indexOf(r.code) >= 0;
        cb.addEventListener("change", function () {
          var cur = s.mode === "codes" ? s.reactions : [];
          cur = cb.checked ? cur.concat([r.code]) : cur.filter(function (x) { return x !== r.code; });
          s.reactions = order(cur, rCodes); s.mode = s.reactions.length ? "codes" : "";
          refresh(it);
        });
        lab.appendChild(cb); lab.appendChild(document.createTextNode(r.code + " " + r.name));
        rRow.appendChild(lab);
      });
      [["none", "없음(None)"], ["unknown", "판정 불가(UNKNOWN)"]].forEach(function (m) {
        var lab = el("label", { "class": "chip special" });
        var cb = el("input", { type: "checkbox" }); cb.checked = s.mode === m[0];
        cb.addEventListener("change", function () {
          s.mode = cb.checked ? m[0] : ""; s.reactions = []; refresh(it);
        });
        lab.appendChild(cb); lab.appendChild(document.createTextNode(m[1]));
        rRow.appendChild(lab);
      });
      card.appendChild(rRow);

      var tRow = el("div", { "class": "row" }); tRow.appendChild(el("b", {}, "Target"));
      var tCodes = CFG.targets.map(function (t) { return t.code; });
      CFG.targets.forEach(function (t) {
        var lab = el("label", { "class": "chip" + (t.code === "UNKNOWN" ? " special" : ""), title: t.hint });
        var cb = el("input", { type: "checkbox" }); cb.checked = s.targets.indexOf(t.code) >= 0;
        cb.addEventListener("change", function () {
          var cur = s.targets;
          if (cb.checked) cur = t.code === "UNKNOWN" ? ["UNKNOWN"] : cur.filter(function (x) { return x !== "UNKNOWN"; }).concat([t.code]);
          else cur = cur.filter(function (x) { return x !== t.code; });
          s.targets = order(cur, tCodes); refresh(it);
        });
        lab.appendChild(cb); lab.appendChild(document.createTextNode(t.code + " " + t.name));
        tRow.appendChild(lab);
      });
      card.appendChild(tRow);

      var xRow = el("div", { "class": "row" }); xRow.appendChild(el("b", {}, "timestamp"));
      var ts = el("input", { type: "text", placeholder: "원문에 적힌 그대로, 쉼표로 구분" }); ts.value = s.timestamps;
      ts.addEventListener("input", function () { s.timestamps = ts.value; refresh(it, true); });
      xRow.appendChild(ts);
      var rv = el("label", { "class": "chip special" });
      var rvcb = el("input", { type: "checkbox" }); rvcb.checked = !!s.review_flag;
      var sel = el("select");
      sel.appendChild(el("option", { value: "" }, "review 사유"));
      CFG.review_reasons.forEach(function (r) { var o = el("option", { value: r }, r); sel.appendChild(o); });
      sel.value = s.review_reason || "";
      rvcb.addEventListener("change", function () { s.review_flag = rvcb.checked; if (!rvcb.checked) { s.review_reason = ""; sel.value = ""; } refresh(it); });
      sel.addEventListener("change", function () { s.review_reason = sel.value; if (sel.value) { s.review_flag = true; rvcb.checked = true; } refresh(it); });
      rv.appendChild(rvcb); rv.appendChild(document.createTextNode("review"));
      xRow.appendChild(rv); xRow.appendChild(sel);
      card.appendChild(xRow);

      var mRow = el("div", { "class": "row" }); mRow.appendChild(el("b", {}, "메모"));
      var memo = el("input", { type: "text", "class": "wide", placeholder: "판정 이유 한 줄 (선택)" }); memo.value = s.rationale || "";
      memo.addEventListener("input", function () { s.rationale = memo.value; save(); });
      mRow.appendChild(memo);
      card.appendChild(mRow);

      var probs = el("div", { "class": "problems" });
      card.appendChild(probs);
      cards[it.comment_id] = { card: card, probs: probs, inputs: card.querySelectorAll("input[type=checkbox]") };
      list.appendChild(card);
      paint(it);
    });
    var gR = document.getElementById("guideR"), gT = document.getElementById("guideT");
    CFG.reactions.forEach(function (r) { gR.appendChild(el("dt", {}, r.code + " " + r.name)); gR.appendChild(el("dd", {}, r.hint)); });
    CFG.targets.forEach(function (t) { gT.appendChild(el("dt", {}, t.code + " " + t.name)); gT.appendChild(el("dd", {}, t.hint)); });
  }

  function paint(it) {
    var s = state[it.comment_id], c = cards[it.comment_id], r = check(it, s);
    var touched = s.mode || s.targets.length || s.review_flag;
    c.card.classList.toggle("done", !r.problems.length);
    c.card.classList.toggle("bad", !!(r.problems.length && touched));
    c.probs.textContent = touched ? r.problems.join(" · ") : "";
    c.card.hidden = document.getElementById("onlyTodo").checked && !r.problems.length;
  }

  function refresh(it, keepInputs) {
    if (!keepInputs) {
      // 체크 상태를 state 에 맞춰 다시 그린다 (None/UNKNOWN 배타 처리 반영)
      var s = state[it.comment_id], boxes = cards[it.comment_id].inputs, i = 0;
      CFG.reactions.forEach(function (r) { boxes[i++].checked = s.mode === "codes" && s.reactions.indexOf(r.code) >= 0; });
      boxes[i++].checked = s.mode === "none"; boxes[i++].checked = s.mode === "unknown";
      CFG.targets.forEach(function (t) { boxes[i++].checked = s.targets.indexOf(t.code) >= 0; });
      boxes[i++].checked = !!s.review_flag;
    }
    paint(it); progress(); save();
  }

  function progress() {
    var done = ITEMS.filter(function (it) { return !check(it, state[it.comment_id]).problems.length; }).length;
    document.getElementById("progress").textContent = "완료 " + done + " / " + ITEMS.length;
  }

  document.getElementById("onlyTodo").addEventListener("change", function () { ITEMS.forEach(paint); });
  document.getElementById("labeler").addEventListener("input", save);

  document.getElementById("exportBtn").addEventListener("click", function () {
    var labels = [], incomplete = [];
    ITEMS.forEach(function (it) {
      var r = check(it, state[it.comment_id]);
      if (r.problems.length) incomplete.push(it.comment_id); else labels.push(r.label);
    });
    var who = document.getElementById("labeler").value.trim();
    var out = { format: CFG.format, labeler: "human:" + (who || "unnamed"), sheet_id: CFG.sheet_id,
                prompt_version: null, model: null, status: "사람 판정",
                created_at: new Date().toISOString(), labels: labels, incomplete_ids: incomplete };
    var text = JSON.stringify(out, null, 2);
    document.getElementById("out").value = text;
    document.getElementById("outWrap").open = true;
    try {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
      a.download = "reaction-human-" + CFG.sheet_id + "-" + (who || "unnamed") + ".json";
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e) { /* 다운로드가 막히면 아래 텍스트를 복사한다 */ }
  });

  document.getElementById("importBtn").addEventListener("click", function () { document.getElementById("importFile").click(); });
  document.getElementById("importFile").addEventListener("change", function (ev) {
    var f = ev.target.files[0]; if (!f) return;
    f.text().then(function (txt) {
      var data = JSON.parse(txt);
      (data.labels || []).forEach(function (l) {
        var it = ITEMS.filter(function (x) { return x.comment_id === l.comment_id; })[0];
        if (!it) return;
        var r = l.reactions || [];
        state[it.comment_id] = {
          mode: !r.length ? "none" : (r.length === 1 && r[0] === "UNKNOWN") ? "unknown" : "codes",
          reactions: r.filter(function (x) { return x !== "UNKNOWN"; }), targets: l.targets || [],
          timestamps: (l.explicit_timestamps || []).join(", "), review_flag: !!l.review_flag,
          review_reason: l.review_reason || "", rationale: l.rationale || "" };
      });
      if (data.labeler && data.labeler.indexOf("human:") === 0) document.getElementById("labeler").value = data.labeler.slice(6);
      document.getElementById("list").textContent = ""; cards = {};
      document.getElementById("guideR").textContent = ""; document.getElementById("guideT").textContent = "";
      render(); progress(); save();
    });
  });

  render(); progress();
})();
</script>
</body>
</html>
"""
