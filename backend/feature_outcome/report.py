"""마크다운 보고서. 숫자는 전부 앞 단계 결과에서만 가져온다."""


def _f(x, nd=2):
    if x is None:
        return "-"
    if isinstance(x, int) or (isinstance(x, float) and abs(x) >= 1000):
        return f"{int(round(x)):,}"
    return f"{x:.{nd}f}"


def _pct(a, b):
    return "-" if not a or b is None else f"{(b - a) / a * 100:+.1f}%"


def render(meta, videos, flags, split_hits, trend_rows, multiples_old, multiples_new, outcome_rows):
    byid = {v["video_id"]: v for v in videos}
    L = [f"# 특징 × 성과 — {meta.get('channel', '')} ({meta.get('generated', '')})", ""]
    L += ["입력: " + ", ".join(f"{k}=`{v}`" for k, v in meta["inputs"].items()), ""]
    n_b = sum(f["breakout"] for f in flags.values())
    L += ["## 1. 급등 영상 표시 (삭제 아님)", "",
          f"규칙: IQR k={meta['k_iqr']}, 배수≥{meta['multiple_min']}, 사건 파일={meta['inputs'].get('events', '-')}. "
          f"표시 {n_b}/{len(flags)}편.", ""]
    for r in ("rule_iqr", "rule_multiple", "rule_event"):
        L.append(f"- {r}: {sum(f[r] for f in flags.values())}편")
    L += ["", "| 제목 | 축 | 게시 | 조회수 | 원 배수 | iqr | mul | ev |", "|---|---|---|---:|---:|:-:|:-:|:-:|"]
    for vid, f in sorted(flags.items(), key=lambda kv: -byid[kv[0]]["view_count"]):
        if f["breakout"]:
            v = byid[vid]
            L.append(f"| {v['title'][:40]} | {v['length_axis']} | {v['published_at'][:10]} | {_f(v['view_count'])} | "
                     f"{_f(v.get('view_multiple'))} | {f['rule_iqr']} | {f['rule_multiple']} | {f['rule_event']} |")
    L += ["", "분할별 급등 영상: " + ", ".join(f"{k} {len(v)}편" for k, v in sorted(split_hits.items())) + ".",
          "discovery에 있으면 발견 표본에서 빼고 패킷을 다시 자른다.", ""]
    L += ["## 2. 게시 월 코호트 (전체 → 제외)", "",
          "스냅샷 1회라 성장 곡선이 아니라 코호트 비교다. 최근 월은 경과일이 짧다.", ""]
    for axis in sorted({r["axis"] for r in trend_rows}):
        L += [f"**{axis}**", "", "| 월 | n | 조회 중앙 전체→제외 | 변화 | 좋아요율 | 댓글율 | views/day |", "|---|---|---|---:|---|---|---|"]
        for r in trend_rows:
            if r["axis"] != axis:
                continue
            L.append(f"| {r['month'][5:]} | {r['n_all']}→{r['n_ex']} | {_f(r['views_all'])}→{_f(r['views_ex'])} | "
                     f"{_pct(r['views_all'], r['views_ex'])} | {_f(r['like_rate_all'], 4)}→{_f(r['like_rate_ex'], 4)} | "
                     f"{_f(r['comment_rate_all'], 5)}→{_f(r['comment_rate_ex'], 5)} | {_f(r['vpd_all'])}→{_f(r['vpd_ex'])} |")
        L.append("")
    L += ["## 3. 분모 재계산 — 급등 영상을 동료 중앙값에서 뺀 배수", "",
          "같은 (축, 분기) 동료, 자기 제외, 급등 영상 제외, 동료 5편 미만이면 미계산.", ""]
    shifts = []
    for vid in flags:
        if flags[vid]["breakout"]:
            continue
        o, n = multiples_old.get(vid), multiples_new.get(vid)
        if o and n is not None:
            shifts.append((abs(n - o) / o, vid, o, n))
    big = sum(1 for s in shifts if s[0] > 0.2)
    L += [f"비교란 영상 중 20% 넘게 움직인 것: {big}/{len(shifts)}편.", "",
          "| 제목 | 축 | 원 배수 | 새 배수 | 변화 |", "|---|---|---:|---:|---:|"]
    for s in sorted(shifts, reverse=True)[:10]:
        v = byid[s[1]]
        L.append(f"| {v['title'][:40]} | {v['length_axis']} | {_f(s[2])} | {_f(s[3])} | {_pct(s[2], s[3])} |")
    L += ["", f"## 4. 특징 × 성과 — {meta['split_name']} 분할", "",
          f"성과 = {meta['outcome']}. diff = median(1) − median(0). LOO = 제외본에서 한 편씩 뺀 diff 범위. 셀 n<{meta['min_cell']}이면 보류.", ""]
    if outcome_rows and outcome_rows[0]["u_as_control"]:
        L += ["**주의: U를 대조군으로 썼다(자리표시자 판정).** 사람·LLM 판정 파일이 오면 이 옵션을 끈다.", ""]
    L += ["| 특징 | 축 | 전체 n1/n0 | 전체 med1/med0 | 전체 diff | 제외 n1/n0 | 제외 med1/med0 | 제외 diff | LOO | 판정 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in outcome_rows:
        a, e = r["all"], r["excluded"]
        loo = "-" if not r["loo_range"] else f"[{_f(r['loo_range'][0])}, {_f(r['loo_range'][1])}]"
        L.append(f"| {r['feature_id']} | {r['axis']} | {a['n1']}/{a['n0']} | {_f(a['med1'])}/{_f(a['med0'])} | {_f(a['diff'])} | "
                 f"{e['n1']}/{e['n0']} | {_f(e['med1'])}/{_f(e['med0'])} | {_f(e['diff'])} | {loo} | {', '.join(r['verdict'])} |")
    L += ["", "## 한계", "",
          "- 판정 파일이 제목 정규식 자리표시자면 content형 특징은 0이 없다. U는 0이 아니다.",
          "- 스냅샷 1회. 월은 게시 코호트이지 성장 곡선이 아니다.",
          "- 급등 영상 임계값(k, 배수, 사건 창)은 사전에 정한 값이고 검증된 것이 아니다.",
          "- 셀 n이 한 자리면 LOO 범위가 diff보다 넓다 — 한 편이 만든 값이다.", ""]
    return "\n".join(L)
