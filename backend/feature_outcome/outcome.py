"""특징 × 성과. 전체와 급등 영상 제외 두 판을 항상 같이 낸다. 홀드아웃은 봉인."""
import statistics as st


class HoldoutSealed(Exception):
    pass


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def _cell(rows):
    a = [o for lab, o in rows if lab == 1]
    b = [o for lab, o in rows if lab == 0]
    ma, mb = _med(a), _med(b)
    diff = (ma - mb) if ma is not None and mb is not None else None
    return {"n1": len(a), "n0": len(b), "med1": ma, "med0": mb, "diff": diff}


def feature_outcome(
    videos, labels, flags, split, split_name="development", outcome=None,
    min_cell=4, unseal_holdout=False, axis=None, u_as_control=False,
):
    """outcome: {video_id: 값} (없으면 videos[i]['view_multiple']).

    u_as_control=True 는 U를 0 대신 대조군으로 쓰는 자리표시자 전용 옵션이다.
    제목만 본 판정처럼 content형이 0을 낼 수 없을 때만 켠다. 보고서에 그 사실이 찍힌다.
    """
    if split_name == "holdout" and not unseal_holdout:
        raise HoldoutSealed("holdout은 봉인되어 있다. 특징 정의를 동결한 뒤 --unseal-holdout 으로 한 번만 연다.")
    byid = {v["video_id"]: v for v in videos}
    if outcome is None:
        outcome = {v["video_id"]: v.get("view_multiple") for v in videos}
    ids = [
        v["video_id"] for v in videos
        if split.get(v["video_id"]) == split_name and (axis is None or v["length_axis"] == axis)
    ]
    fids = sorted({f for vid in ids for f in labels.get(vid, {})})
    out = []
    for fid in fids:
        def rows(exclude):
            r = []
            for vid in ids:
                if exclude and flags[vid]["breakout"]:
                    continue
                lab = labels.get(vid, {}).get(fid)
                o = outcome.get(vid)
                if lab is None or o is None:
                    continue
                if lab == "U":
                    if not u_as_control:
                        continue
                    lab = 0
                r.append((lab, o))
            return r

        all_c, ex_c = _cell(rows(False)), _cell(rows(True))
        ex_rows = rows(True)
        loo = []
        if ex_c["n1"] >= min_cell and ex_c["n0"] >= min_cell:
            for i in range(len(ex_rows)):
                d = _cell(ex_rows[:i] + ex_rows[i + 1:])["diff"]
                if d is not None:
                    loo.append(d)
        verdict = []
        if min(all_c["n1"], all_c["n0"]) < min_cell or min(ex_c["n1"], ex_c["n0"]) < min_cell:
            verdict.append(f"셀 n<{min_cell}, 판단 보류")
        else:
            da, de = all_c["diff"], ex_c["diff"]
            if da and de and (da > 0) != (de > 0):
                verdict.append("부호반전")
            if da and de is not None and abs(de) <= abs(da) / 2:
                verdict.append("붕괴")
            if loo and min(loo) < 0 < max(loo):
                verdict.append("LOO가 0을 가로지름")
        out.append({
            "feature_id": fid, "axis": axis or "all",
            "all": all_c, "excluded": ex_c,
            "loo_range": [min(loo), max(loo)] if loo else None,
            "verdict": verdict, "u_as_control": u_as_control,
        })
    return out
