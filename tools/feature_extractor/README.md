# guest_present cascade v0.1

Frozen Registry A-v0.1 envelope의 guest_present 원문 정의·포함/제외 예시·필요 증거를 사용한다. 다른 feature를 판정하지 않는다. 기존 blind labelability artifact는 입력으로만 읽는다.

## 판정과 경계

- Stage 1은 영상 단위를 명시한 좁은 metadata 선언만 판정한다. 직접 게스트 참여 선언은 1, 영상 전체를 게스트 없이 혼자 진행했다는 선언은 0이다. 이름 등장·단순 동시 출연·제목 추측·모순·원본 영상과의 혼동은 U이다. ID/인물명 정답 목록은 없다. 이 보수적인 문법은 낮은 coverage를 의도한다.
- Stage 1 U만 기존 stage2_collect의 자막 및 샘플 프레임 경로로 보낸다. Shorts 5장, 나머지 6장이다. 자막이 없으면 프레임만으로 충분한 직접 참여가 확인될 때만 1이 가능하다.
- Stage 2는 명시적으로 지정한 Anthropic vision model을 사용한다. 실제 참여 설명, 제외 대상이 아닌 역할, 존재하는 프레임 citation이 필요하다. citation의 존재/해시는 검사하지만 시각적 해석의 진실성을 코드가 증명하지는 못한다. 샘플에서 안 보인다는 0은 U로 내린다. 실패·누락·불확실성도 U이다.
- confidence는 주관적 low/medium/high이며 확률이나 검증된 정확도가 아니다. 계약 테스트 통과와 Human reference 실증 평가는 구분한다. manifest는 자동으로 validated 상태로 승격하지 않는다.
- metadata는 6개 content 필드만 허용하며 frozen split의 Development ID만 받는다. split membership 이외의 Discovery/Holdout 내용, DB, 성과/댓글/정답은 extractor가 읽지 않는다. evidence의 임의 필드도 거부한다. 자막·영상 자체의 문구는 콘텐츠 증거로 전달되므로 내재된 모든 성과 언급을 제거했다는 보장은 없다. 모델에는 이를 판정 근거로 사용하지 않도록 지시한다.

## 실행 (repo 최상위 PowerShell)

Python 3.10+ 필요. 기본 실행은 네트워크 없이 Stage 1 및 미해결 U를 새 폴더에 저장한다.

```powershell
python -B -m tools.feature_extractor `
  --metadata ..\outputs\chim-development90-labelability-A-v0.1\llm-input.jsonl `
  --split backend\feature_discovery\outputs\chim-recent300-seed42\split.csv `
  --registry ..\outputs\feature-registry-A-v0.1\feature_registry_A_v0.1.json `
  --out backend\feature_discovery\outputs\guest-extractor-v0.1\run-001
```

Stage 2 실제 실행은 위 명령에 `--collect --model <사용가능한-vision-model-ID>`를 추가하고 새 output 경로를 사용한다. 현재 Python에 yt-dlp, PATH에 ffmpeg/ffprobe, 환경변수 ANTHROPIC_API_KEY가 필요하다. YouTube API key는 사용하지 않는다. 브라우저 쿠키는 사용하지 않으며 yt-dlp 사용자 설정을 무시한다. 수집 실패는 U로 남는다. 모델 API 호출 비용이 발생한다.

기존 collector evidence를 재사용할 때는 `--collect` 대신 `--evidence-root <evidence_packet.json의-영상별-폴더들이-있는-경로>`를 지정한다. 기존 evidence는 수정하지 않는다. 어느 경로도 기존 output을 덮어쓰지 않는다.

`predictions.jsonl`은 label/stage/confidence/evidence/provenance를 보존한다. `stage1.json`, `stage2_queue.json`, 모델 응답, 입력·코드·프롬프트·출력 SHA-256 manifest도 저장한다. 모델 버전 및 응답 ID를 기록하지만 API 응답 재현성을 보장하지 않는다.

`labels.json`의 `labels[video_id].guest_present`는 기존 frozen feature-outcome label 형식인 문자열 0/1/U이다. **부분 행렬**로 표시한다. 12개 feature 완비를 요구하는 현재 Finding Engine 실행에는 바로 넣을 수 없으며, 향후 명시적인 단일 feature scope 연결이 필요하다. 다른 11개를 0/U로 채우거나 prototype labels와 합치지 않는다.

## 분리된 평가

Human reference를 사용하는 유일한 명령이다. reference는 `{"labels":{"VIDEO_ID":{"guest_present":"0"}}}` 형식이며 예측에 포함된 Development subset이어야 한다. 먼저 prediction hash를 검사한다. U는 정답 0으로 바뀌지 않으며 coverage/n_u와 비-U 정확도를 별도로 보고한다. Human U는 정확도 분모에서 제외한다.

```powershell
python -B -m tools.feature_extractor.evaluate `
  --run backend\feature_discovery\outputs\guest-extractor-v0.1\run-001 `
  --reference <검증된-Human-reference.json> `
  --split backend\feature_discovery\outputs\chim-recent300-seed42\split.csv `
  --out backend\feature_discovery\outputs\guest-extractor-v0.1\eval-001.json
```

실제 Human reference 정확도는 아직 검증하지 않았다. 과거 handoff의 수치는 이 구현의 측정치가 아니다. 판정 규칙 조정에 평가 정답을 사용하지 않는다.

## 테스트

```powershell
python -B -m pytest -q -p no:cacheprovider backend/tests/test_guest_extractor.py backend/tests/test_feature_discovery.py
```

합성 데이터와 mock judge/collector로 계약을 검사한다. 외부 수집/모델 호출/DB write는 하지 않는다. Vision request 형식 참고: https://platform.claude.com/docs/en/build-with-claude/vision

## 채널 단위 실행기 — `channel.py` (2026-09-18)

`multi.extract_video`(한 영상 · 텍스트 한 번 · 필요 시 시각 한 번)를 채널 전체에 돌리는 실행기.
싼 단서부터 보고 판정이 끝난 특징은 더 보지 않는다. U를 0으로 바꾸는 일은 없다.

```
python -m tools.feature_extractor.channel run --content docs/prototype/chim-evidence.json \
    --registry <plain 또는 frozen registry> --out <새 폴더> \
    [--split split.csv --scope development] [--captions <vid>.txt 폴더] [--evidence-root stage2 패킷 폴더] \
    [--judge offline | --judge api --model <ID>] [--cache <폴더>] [--routing routing.json]
python -m tools.feature_extractor.channel import   --run <폴더> --answers <답안 폴더>     # offline 답안 반영
python -m tools.feature_extractor.channel evaluate --run <폴더> --reference <사람 정답> --out eval.json
```

- 입력 content는 허용 필드(제목·설명·길이·게시일·길이축)만 남기고 `blind.validate_rows`로 검사한다. 성과값은 들어갈 수 없다.
- 자막은 `--captions` 폴더의 `<video_id>.txt` 또는 `stage2_collect` 패킷에서 읽는다. 아주 길면 나눠 묻고 합친다(하나라도 1 → 1, 전부 0 → 0, 섞이면 U).
- 시각 단계는 텍스트 U이면서 경로 표가 `TEXT_THEN_VISUAL`인 특징에만, 패킷에 프레임이 있을 때만 쓴다. 프레임에 안 보인다는 이유로 0이 되지 않는다(`multi.py` 규칙 그대로).
- 다른 12개(예: 14F 레지스트리)를 쓰면 `--routing routing.json`으로 특징별 경로를 준다. 없으면 전부 시각 허용으로 두고 manifest에 `all_visual_fallback`을 남긴다. `core.set_feature_routing`이 이를 위해 추가됐다.
- 분할 파일이 있으면 기본은 development만, holdout은 `--unseal-holdout` 없이는 거부. 분할 파일이 없으면 채널 전체(제품 모드).
- `--cache`를 주면 같은 영상·레지스트리·프롬프트·모델·증거에 대해 다시 부르지 않는다.
- 출력: `labels.json`(전체 행렬, `feature_outcome`·대시보드가 그대로 읽음), `predictions.jsonl`(근거·단계), `review_queue.jsonl`(자신 없는 판정·시각 단계·무작위 10%), `summary.md`(특징별 0/1/U와 축별 U 비율), `manifest.json`.
- `--judge offline`은 영상마다 판정 입력 JSON을 내보내고, 답안을 `import`로 받는다. 저장소의 기존 오프라인 판정 방식과 같다.
- 자막·프레임을 **모으는** 일은 이 실행기가 하지 않는다. `tools/stage2_evidence/stage2_collect.py`(yt-dlp·ffmpeg)를 쓰며, 영상·자막 내려받기의 약관 판단은 미결이다.
