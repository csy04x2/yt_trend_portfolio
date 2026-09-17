# Reaction Phase 3: AI 판정기와 평가 도구

기준 정본: [Reaction Phase 1 checkpoint](../reaction-phase1-checkpoint.md) (Reaction·Target 정의, H1–H4), [Reaction track closeout](../reaction-track-closeout-2026-09-17.md) (Final vNext, R9 행동 지향, 「2026-09-17 재개 결정」), [데이터 장부](../data-ledger.md) I항목 (Phase 2 200개, fresh-blind = NO).

이 문서는 재개 결정의 범위 1(AI 판정 프롬프트와 판정기)과 범위 2(사람 판정과의 일치도 평가 도구)에서 **만든 것**과 **돌리는 법**, **검증 절차**를 적는다. taxonomy는 바꾸지 않았다. 범위 3(Stage 08 집계·09 해석·대시보드)과 범위 4(Content Feature·성과 결합)는 이 작업에 포함되지 않는다. 범위 3은 [Reaction 결과를 리포트에 연결](reaction-report.md)에 있다.

> **결과의 지위: 검증 전 AI 판정.** 아래 도구로 만든 Reaction·Target 값은 독립 fresh 표본 검증을 통과하기 전까지 전부 「검증 전 AI 판정」이다. MVP Finding 입력으로 쓰지 않고, 대시보드·리포트에 싣는 경우 그 사실을 표시한다(재개 결정의 제품 사용 조건).

## 1. 만든 것

| 파일 | 역할 |
|---|---|
| `backend/app/prompts/comment_reaction.md` | 판정 프롬프트 `reaction-v1`. 프롬프트 레지스트리에 버전·이력과 함께 등록된다. 정의·경계는 두 기준 문서의 문장을 옮겼고 새 경계를 만들지 않았다 |
| `backend/app/db/schema.sql` | `comment_reactions` 표 추가. 키는 (comment_id, prompt_version, model). 기존 감성·주제 표는 건드리지 않았다 |
| `backend/app/pipeline/label_reactions.py` | 묶음 → Claude(API 또는 오프라인) → 검증 → DB 또는 라벨 파일 저장 |
| `backend/app/pipeline/reaction_eval.py` | 두 라벨 파일의 일치도 계산. 출력은 숫자와 comment_id 뿐이다 |
| `backend/app/pipeline/reaction_sheet.py` | 사람 판정 시트(혼자 열리는 HTML) 생성기 |
| `backend/app/cli.py` | `export-reaction-batch` · `import-reaction-batch` · `label-reactions` · `export-reactions` · `reaction-sheet` · `reaction-eval` |
| `backend/tests/test_label_reactions.py`, `test_reaction_eval.py` | 레지스트리·검증 규칙·저장·지표·시트. 합성 댓글만 쓴다 |

### 판정 하나의 모양

```json
{"comment_id": "...", "reactions": ["R1", "R7"], "targets": ["T2"],
 "explicit_timestamps": ["32:19"], "review_flag": false, "review_reason": null,
 "rationale": "한두 문장"}
```

### 검증 규칙 (어기면 그 묶음 전체를 저장하지 않는다)

| 규칙 | 근거 |
|---|---|
| Reaction은 R1–R10, Target은 T1–T5와 UNKNOWN만. `R11`, `T6`, `"None"` 문자열은 거부 | closeout Final vNext — 추가·삭제·병합 없음 |
| Reaction=None은 `[]`. 판정 불가는 `["UNKNOWN"]`. 둘을 다른 값으로 저장 | checkpoint Reaction 공통 규칙 「None은 반응이 없음이고 UNKNOWN과 다르다」 |
| UNKNOWN은 혼자만 온다. 코드와 섞이면 거부 | 구현 해석: UNKNOWN은 「판정할 수 없는 경우」라 같은 축의 코드 선택과 동시에 성립하지 않는다고 봤다. 기준 문서에 명시된 문장은 아니다(5장) |
| Reaction이 있는데 Target이 비면 거부(모르면 `["UNKNOWN"]`). Reaction=None이면 Target은 비워도 되고 붙여도 된다 | Phase 3 작업 지시의 출력 계약. Phase 2 분포(None 11, no target 4)와 모순되지 않는다 |
| timestamp는 원문에 글자 그대로 있는 값만. 원문에 없는 값이 오면 거부. 원문에 있는데 모델이 빠뜨린 `m:ss`·`h:mm:ss`는 코드가 채운다 | H2 — AI가 장면·timestamp를 추정하지 않는다. 채우는 값은 원문에 있는 값이다 |
| `review_flag=true`이면 사유가 APPLICATION_ERROR / DEFINITION_BOUNDARY / STRUCTURE_CANDIDATE 중 하나, false이면 사유는 null | closeout review audit 분류 |
| 번호 누락·중복·없는 번호 거부, AI 출력은 rationale 필수 | 기존 `offline_llm.validate_result`와 같은 원칙 |

사람 판정 파일과 평가 입력에도 같은 코드 규칙을 적용한다(review·timestamp·rationale 칸이 없으면 기본값으로 채운다).

### 분석 대상 (H3)

- DB 경로: `comments`에 `analysis_eligible` 열이 있으면 0으로 **확정된** 댓글만 뺀다. 열이 없거나 값이 NULL이면 판정하고, 거르는 일은 집계에 맡긴다.
- raw JSON 경로: `analysis_eligible: false`인 행을 뺀다(수집기 `phase2_collect.py`의 필드).
- 채널 본인 댓글 제외는 집계 단계의 일이다. 판정기는 직원·부계정 의심만으로 제외하지 않는다.

## 2. 판정 돌리는 법

모든 명령은 `backend/`에서 실행한다. 원문이 들어가는 산출물(묶음 파일, 사람 판정 시트, rationale이 든 라벨 파일)은 gitignored인 `backend/data/` 아래가 아니면 **명령이 거부한다.**

### 오프라인 (API 키 없음, 금전 비용 0)

```bash
# DB 댓글이 대상일 때
python -m app.cli export-reaction-batch rx --out ./data/batches/reaction
# fresh raw 표본(DB에 없음)이 대상일 때
python -m app.cli export-reaction-batch rx --input ./data/<표본>/raw_collection.json --out ./data/batches/reaction

# 각 묶음 .md를 Claude Code에 읽혀 <batch>.result.json으로 저장한 뒤
python -m app.cli import-reaction-batch rx_001 --out ./data/batches/reaction            # → comment_reactions
python -m app.cli import-reaction-batch rx_001 --out ./data/batches/reaction \
    --labels-out ./data/reaction-labels/ai-offline.json                                 # → 라벨 파일
```

### API (금전 비용이 나간다)

```bash
python -m app.cli label-reactions --dry-run --limit 20        # 건수·묶음 수만 (키 불필요)
python -m app.cli label-reactions --limit 20                  # DB 댓글 → comment_reactions
python -m app.cli label-reactions --input ./data/<표본>/raw_collection.json \
    --labels-out ./data/reaction-labels/ai-<모델>.json         # raw → 라벨 파일
python -m app.cli export-reactions --out ./data/reaction-labels/ai.json --model <모델>
```

`python -m app.cli prompts`는 `comment_reactions`에 쌓인 버전도 저장소의 프롬프트 파일과 대조한다.

## 3. 평가 돌리는 법

### 사람 판정 시트

```bash
python -m app.cli reaction-sheet ./data/<표본>/raw_collection.json --out ./data/reaction-sheets/<표본>.html
```

- 브라우저로 열어 댓글마다 Reaction(코드 / 없음(None) / 판정 불가(UNKNOWN))과 Target을 고른다. 아무것도 안 고른 상태와 None을 구분하기 위해 None도 명시적으로 고른다.
- 진행 상태는 브라우저 저장소에 자동 저장되고, 「JSON 내보내기」로 라벨 파일을 받는다. 규칙에 맞지 않는 댓글은 `labels`에 들어가지 않고 `incomplete_ids`로만 나간다. 받은 JSON은 `backend/data/` 아래에 둔다.
- 시트에는 AI 판정이 없다(블라인드). 분석 제외로 확정된 댓글도 싣지 않는다.
- **시트 HTML에는 댓글 원문이 들어 있다. 커밋하지 않는다.**

### 일치도

```bash
python -m app.cli reaction-eval ./data/reaction-labels/human-<판정자>.json ./data/reaction-labels/ai-<모델>.json \
    --out ../docs/reports/<이름>.json
```

A가 기준, B가 비교 대상이다. 사람 대 AI, AI 대 AI(모델 간·재실행 간), 사람 대 사람 모두 같은 명령이다.

| 지표 | 정의 |
|---|---|
| 라벨별 precision / recall / F1 | R1–R10, Reaction UNKNOWN, T1–T5, Target UNKNOWN 각각의 존재 여부를 이진으로 본 값. A를 기준으로 본 B. 두 쪽 모두 한 번도 안 쓴 라벨은 —(None) |
| 라벨별 Cohen's kappa | 같은 이진 표의 kappa. 기대 일치가 1이면 정의되지 않아 — |
| Reaction=None 혼동표 | A None/반응 있음 × B None/반응 있음 2×2, 그리고 kappa |
| 정확 일치율 | Reaction 집합, Target 집합, 둘 다가 완전히 같은 댓글의 비율 |
| Jaccard 평균 | 댓글별 (A∩B 크기) ÷ (A∪B 크기)의 평균. 둘 다 비었으면 1 |
| macro F1 | F1이 정의되는 라벨들의 평균 |
| 어긋난 comment_id | Reaction·Reaction=None·Target 별 ID 목록 (원문 없음) |

보고서(JSON·화면)에는 댓글 원문과 rationale이 들어가지 않는다. 입력 라벨 파일은 rationale을 담으므로 `backend/data/`에 둔다.

## 4. 검증 프로토콜

재개 결정의 조건을 그대로 따른다.

1. **Phase 2 200개는 개발·보정용이다.** 슈카월드·MBCNEWS 200개는 R9 구조 수정의 근거로 쓰였으므로 fresh-blind validation eligibility = NO다(데이터 장부 I항목). 이 표본에서 잰 일치도는 프롬프트를 고치는 재료일 뿐이며 판정기의 독립 성능 증거로 보고하지 않는다. 이 표본으로 프롬프트를 고칠 때마다 버전을 올리고 이력에 남긴다.
2. **독립 검증에는 새로 수집한, 누구도 본 적 없는 fresh 표본이 필요하다.** 수집 전에 데이터 장부의 Blind 사용 규칙 5문항(comment_id 중복, 같은 영상, 내용 노출, 기존 Reaction 판정 존재, 다른 목적 라벨)을 확인하고 기록한다. 확인되지 않은 데이터에 fresh=YES를 주지 않는다.
3. **검증에 쓸 프롬프트 버전과 모델을 표본을 열기 전에 고정한다.** fresh 표본 결과를 보고 프롬프트를 고치면 그 표본은 더 이상 fresh가 아니다. 고쳤다면 새 표본이 필요하다.
4. **사람 판정은 AI 판정을 보지 않고 한다.** 시트는 AI 값을 싣지 않는다. 사람 판정이 끝나기 전에 AI 결과 파일을 판정자에게 주지 않는다.
5. **`reaction-eval`로 사람(A) 대 AI(B)를 잰다.** 통과 기준에 미달하거나 기준이 정해지지 않았으면 결과는 계속 「검증 전 AI 판정」이다.
6. 사용 이력(어느 표본이 무엇에 쓰였는지)은 데이터 장부에 기록한다.

`review_flag=false`는 정답을 뜻하지 않는다(closeout). 일치도 보고에서 review_flag 건수는 참고값이다.

## 5. 사람이 정할 것 (이 작업에서 정하지 않음)

- **누가 사람 판정을 하는가.** 판정자 수(1명 / 2명 이상), 판정자 간 일치도를 먼저 잴지, 불일치 조정(adjudication) 방식.
- **통과 기준.** 어떤 지표(라벨별 F1·kappa, 정확 일치율, Reaction=None kappa 등)를 몇 이상으로 볼지, 희귀 라벨(R5·R10 등 표본에 거의 없는 라벨)을 어떻게 다룰지.
- **fresh 표본 설계.** 채널·영상 수, 댓글 수, 정렬(relevance / time), 답글 포함 여부, 제외 채널.
- **검증 대상 모델과 프롬프트 버전.** 오프라인(Claude Code) 판정과 API 모델 중 무엇을 검증 대상으로 고정할지.
- **Reaction UNKNOWN의 출력 형태.** checkpoint 공통 규칙이 Reaction에 대해서도 UNKNOWN(판정 불가)을 None과 구분하므로 `["UNKNOWN"]`을 허용했다. closeout의 Phase 2 분포에는 Reaction UNKNOWN 집계 칸이 없다. 이 형태를 유지할지 확인이 필요하다.
- **UNKNOWN 배타 규칙.** UNKNOWN을 코드와 섞지 못하게 한 것은 구현 해석이다. 유지할지 확인이 필요하다.
- **review_reason 세 사유의 정의.** 이름은 closeout review audit에서 가져왔지만 기준 문서에 사유별 정의 문장은 없다. 프롬프트와 시트의 설명(적용 불확실 / 두 정의의 경계 / 구조 검토 후보)은 이름에서 옮긴 작업 정의이며 사람 확정이 필요하다.
- **답글의 맥락.** H3는 제외된 parent 댓글을 viewer reply의 맥락으로 보존할 수 있다고 하지만, 판정기는 지금 댓글 하나와 영상 제목·채널 이름만 맥락으로 준다. parent 맥락을 넣을지.
- Phase 2 AI coding 결과 파일의 보관 위치(데이터 장부에서 확인 필요로 남아 있음). 개발·보정 비교에 쓰려면 이 파일이 필요하다.
