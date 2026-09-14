# Chim Stage 2 Runner v0.2

이 패키지는 **metadata Stage 1에서 U가 나온 15개 영상만** 자동으로 더 본다.

## 하는 일

1. YouTube 자막/자동자막을 가져온다.
2. 저해상도 영상을 임시로 내려받는다.
3. Shorts 전체에 걸쳐 5개 시점의 프레임을 뽑는다.
4. 원본 영상은 프레임 추출 뒤 삭제한다.
5. 영상별 `evidence_packet.json`을 만든다.
6. 전체를 `stage2_output/judge_input.jsonl`로 묶는다.

**조회수 / 좋아요 / 댓글 / 상대성과는 일절 읽지 않는다.**

## Windows에서 실행

압축을 푼 폴더에서 PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\run_stage2.ps1
```

Chrome 쿠키 읽기가 실패하면 브라우저를 완전히 종료하고 다시 실행한다.

Edge를 쓰고 싶으면 직접:

```powershell
py .\stage2_collect.py `
  --queue .\stage2_escalation_15.json `
  --out .\stage2_output `
  --cookies-from-browser edge
```

## 먼저 1개만 시험

```powershell
py .\stage2_collect.py `
  --queue .\stage2_escalation_15.json `
  --out .\stage2_test `
  --cookies-from-browser chrome `
  --limit 1
```

## 성공하면 생기는 것

```text
stage2_output/
  collection_summary.json
  judge_input.jsonl
  VIDEO_ID/
    evidence_packet.json
    frames/
      frame_01_....jpg
      ...
    subs/
      ...
```

`judge_input.jsonl`과 각 영상의 `frames`가 Stage-2 멀티모달 판정 입력이다.

## 지금 일부러 안 한 것

- 얼굴인식
- speaker diarization
- 모든 feature 자동화
- Human label 사용
- Finding Engine 연결

우선 15개에서 evidence 수집 자체가 안정적으로 되는지만 확인한다.

## 주의

YouTube가 자동 요청을 막으면 yt-dlp가 쿠키를 요구할 수 있다.
그 경우 `--cookies-from-browser chrome` 또는 `edge`를 사용한다.

이 스크립트는 Human gold label을 포함하지 않으므로 Stage-2 blind evaluation을 깨지 않는다.


## v0.2 수정
`yt-dlp.exe`가 PATH에 없어도 동작하도록 모든 호출을 `py -m yt_dlp` 방식으로 변경했다.
