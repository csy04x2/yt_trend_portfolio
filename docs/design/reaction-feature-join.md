# Reaction × Content Feature × 상대 성과 결합 분석 (탐색용, opt-in)

2026-09-17 · branch `feat/reaction-feature-join` (base `integration/feature-discovery-observable` `cde9851`)

[Reaction track 재개 결정](../reaction-track-closeout-2026-09-17.md)의 **범위 4 — Reaction 결과와
Content Feature·성과의 결합 분석**을 위한 도구다. 실제 Reaction 판정이 아직 없으므로
합성 데이터로만 검증했고, 실제 데이터로 실행하지 않았다.

> **결과의 지위: 검증 전 AI 판정.** 이 도구가 내는 모든 행·계산·보고서는
> `validation_status: "검증 전 AI 판정"`, `mvp_input_eligible: false` 를 단다.
> 독립 fresh 표본 검증을 통과하기 전까지 MVP Finding 입력이 아니며, 코드가 그 경로를 막는다(4장).

이 문서에서 **[제안]** 이 붙은 값은 사람 승인 전이다.

## 1. 목적

- Content Feature(동결 registry의 A 특징)와 Reaction(영상별 R 코드 비율)이 같이 움직이는지,
  Reaction 비율과 상대 성과(`view_multiple`)가 같이 움직이는지를 **사실(Stage 08 모양)** 로 본다.
- 인과·예측·임계값 판정을 하지 않는다. Finding Engine v0.1과 같은 원칙이다
  (`thresholds_applied: []`, `causal_claim: false`).
- Finding Engine의 세 갈래(Feature→Performance, Feature→Audience Behavior, Behavior→Performance)를
  **대체하지도 확장하지도 않는다.** Reaction은 별도 보고서로만 나온다.

## 2. 데이터 흐름

```text
comments (analysis_eligible, parent_id)  ─┐
comment_reactions (prompt_version, model) ─┼─ reaction_profile.load_comment_reactions (read-only, 원문 열 SELECT 안 함)
observation_sampling (있으면)             ─┘            │
                                                        ▼
                                          build_profiles → 영상별 Reaction 프로필
split.csv ─ 선택 split만 ─┐                             │
frozen registry envelope ─┼─ load_frozen_inputs ─────────┤
labels (0/1/U)           ─┤  (frozen.ANALYSIS_FIELDS 투영)│
evidence.json            ─┘                             ▼
reference manifest (opt-in) ──────────────► join_rows → video_id 키 결합 행
                                                        ▼
                                          associations (Finding Engine _binary_leg / _continuous_leg)
                                                        ▼
                         feature_discovery/outputs/reaction-feature-join/<RUN>/{manifest.json, reaction_join.json}
```

| 파일 | 역할 |
|---|---|
| `backend/feature_outcome/reaction_profile.py` | 영상별 프로필 계산(순수 함수)과 읽기 전용 DB 로더 |
| `backend/feature_outcome/reaction_join.py` | 사전 점검(봉인·출력 경로), 동결 입력 투영, 결합, 연관 계산, CLI |
| `backend/feature_outcome/finding.py` | `build_findings` 에 Reaction 입력 거부 가드 추가 (기본 결과는 그대로) |
| `backend/tests/test_reaction_feature_join.py` | 합성 데이터 테스트 31개 |

### 2.1 영상별 Reaction 프로필

| 필드 | 뜻 |
|---|---|
| `eligible_n` | 분석 단위(기본 원댓글) 중 `analysis_eligible = 1` 인 댓글 수. 0·NULL·문자열은 대상이 아니다 |
| `n_labeled` | 그중 지정한 (prompt_version, model) 판정이 있고 코드 규칙(`label_reactions.check_label`)을 통과한 수 |
| `label_coverage` | `n_labeled / eligible_n` |
| `shares.reaction_share_R1…R10` | 코드가 붙은 댓글 ÷ `n_labeled`. 다중 코드라 합이 1이 아니다 |
| `shares.reaction_none_share` | Reaction=None(`[]`) ÷ `n_labeled` |
| `shares.reaction_unknown_share` | Reaction=`["UNKNOWN"]` ÷ `n_labeled` |
| `shares.reaction_target_share_T1…T5`, `reaction_target_unknown_share` | Target 코드 ÷ `reacting_n`(Reaction이 None도 UNKNOWN도 아닌 댓글) **[제안]** |
| `counts`, `target_counts`, `review_flag_share` | 원 건수(비율이 null이어도 남긴다)와 review 표시 비율 |
| `invalid_label_n`, `ineligible_labeled_n` | 규칙 위반 판정 수, 분석 제외 댓글에 붙은 판정 수(집계에서 뺐다) |
| `status`, `reason` | `available` / `no_eligible_comments` / `no_reaction_labels` / `insufficient_labeled_n` |
| `sampling` | `observation_sampling` 의 decision·completeness·inclusion_prob·label_cap·policy_version. 표가 없거나 행이 없으면 `not_recorded`, run_id 없이 실행이 여럿이면 `ambiguous_multiple_runs` |
| `prompt_version`, `model`, `label_unit`, `min_labeled` | 재현 키 |

`status` 가 `available` 이 아니면 **모든 비율이 null** 이다. 0으로 채우지 않는다.

**최소 n [제안]: `MIN_LABELED_PER_VIDEO = 30`.** 비율 p의 표준오차 `sqrt(p(1-p)/n)` 는 p=0.5, n=30에서
약 0.09다. 댓글 표본 정책 프리셋의 `label_cap`(light 50 / standard 100) 안에 들어오는 가장 작은 둥근
값이다. `--min-labeled` 로 바꿀 수 있고 값은 manifest·보고서에 남는다.

### 2.2 결합 행

`video_id` 하나에 한 행: `split`, `length_axis`, `features`(동결 판정 0/1/U 그대로),
`reaction_profile`, `view_multiple`, `relative_performance`, `validation_status`, `mvp_input_eligible`.
영상 제목과 댓글 원문은 싣지 않는다.

`relative_performance`:

| 조건 | 값 |
|---|---|
| `--reference-manifest` 없음 | 공급된 `view_multiple` 사용, `{"canonical": false, "status": "provisional_legacy", "final_eligible": false}`. 보고서 `input_contract.relative_performance` 는 Finding의 legacy 계약 그대로 |
| `--reference-manifest` 있음 | `finding._canonical_outcomes` 로 canonical 값으로 바꿈, `{"canonical": true, "status": "canonical_reference", "canonical_value_status": <영상별 status>, "final_eligible": <규칙 승인 여부>}` |

### 2.3 연관 계산

Finding Engine의 통계 함수를 그대로 부른다. 새 통계를 만들지 않았다.

| relation | 함수 | 효과 | 대상 |
|---|---|---|---|
| `feature_to_reaction` | `_binary_leg` | median difference (특징=1 − 특징=0), LOO 안정성 | 동결 특징 × 18개 비율(R 10, None, UNKNOWN, T 5, T UNKNOWN) |
| `reaction_to_performance` | `_continuous_leg` | Spearman rho, LOO 안정성 | 18개 비율 × `view_multiple` |

- U는 제외하고 대조군으로 쓰지 않는다. 비율이 null인 영상은 `missing_metric_n` / `missing_behavior_n` 으로 센다.
- 포함 확률 가중을 하지 않는다(`unweighted: true`). 보고서에 `inclusion_prob_values` 와
  completeness 개수를 남긴다. Development는 표본 정책 권장안에서 census(확률 1.0)다.
- 다중 비교 보정을 하지 않는다. 보고서에 `multiple_comparisons_note` 를 남긴다.
- 체인 후보(Feature→Reaction→Performance)는 만들지 않았다. 두 갈래 사실만 낸다.

## 3. 돌리는 법 (실제 Reaction 판정이 생긴 뒤)

모든 명령은 `backend/` 에서 실행한다. 유료 API를 부르지 않는다.

1. `comment_reactions` 에 검증할 (prompt_version, model) 판정을 쌓는다
   ([Phase 3 문서](reaction-classifier-phase3.md) 2장). 판정 대상 영상은 선택 split 영상이어야 한다.
2. 동결 registry envelope, 승인된 판정 파일(0/1/U), split CSV, evidence JSON을 준비한다
   (MVP Finding Runner와 같은 파일).
3. 실행:

```text
python -m feature_outcome.reaction_join \
    --registry <동결 registry envelope> --labels <판정 파일> \
    --split <split.csv> --evidence <evidence.json> \
    --db data/<채널>.db --prompt-version reaction-v1 --model <모델> \
    --out feature_discovery/outputs/reaction-feature-join/<RUN_ID> \
    [--reference-manifest <동결 manifest>] [--sampling-run-id <run_id>] \
    [--min-labeled 30] [--include-replies]
```

4. 결과: `<RUN_ID>/manifest.json`(입력 SHA-256, 버전, 모드), `<RUN_ID>/reaction_join.json`(행·계산).
   `feature_discovery/outputs/` 는 gitignored다.

Holdout은 `--split-name holdout --unseal-holdout` 을 **둘 다** 줘야 열린다. 한 번만 연다는 규칙은
기존 엔진과 같다. 재개 결정상 검증 전 판정으로 Holdout을 여는 것 자체를 권하지 않는다(6장).

## 4. 가드 (테스트로 고정)

| 가드 | 구현 | 테스트 |
|---|---|---|
| Holdout 봉인 | `check_scope` 가 입력 파일 접근 전에 `HoldoutSealed`. 입력을 지운 상태에서도 같은 예외 | `test_holdout_sealed_and_discovery_refused_before_input_access`, `test_cli_refuses_holdout_without_unseal`, `test_explicit_unseal_reads_only_holdout` |
| Discovery 거부 | `ALLOWED_SPLITS = (development, holdout)` | 위 테스트 |
| 동결 특징만 | `registry` 키가 있는 envelope만, `load_registry`/`load_labels`, 선택 영상 × 모든 특징 판정 필수 | `test_requires_frozen_registry_and_complete_labels` |
| 분석 대상만 | `analysis_eligible == 1` 만. 부적격 판정은 `ineligible_labeled_n` 으로만 | `test_eligibility_filter_uses_only_confirmed_eligible_comments` |
| 판정 버전 비혼합 | (prompt_version, model) 필수, JOIN 조건에 둘 다. DB에 있는 조합 목록을 보고서에 기록 | `test_development_run_...`(다른 버전 R5가 섞이지 않음), `test_prompt_version_and_model_required` |
| 최소 n·결측 | 미달·판정 없음·대상 없음이면 비율 null + reason | `test_missing_and_low_n_give_null_shares_with_reason`, `test_exactly_min_n_...` |
| 비정규 성과 표시 | legacy는 행마다 `canonical: false`, `provisional_legacy` | `test_development_run_...`, `test_reference_manifest_marks_canonical_rows` |
| 원문 없음 | 로더 SQL에 `text`·`rationale`·`timestamps_json` 없음, 읽기 전용 연결, 보고서에 제목 없음 | `test_loader_never_selects_comment_text_or_rationale`, 보고서 전체에 합성 원문·근거·timestamp 표식 부재 확인 |
| **MVP 격리** | ① `build_findings` 가 `reaction_` 접두 필드나 `mvp_input_eligible: false` 가 있는 영상 행을 거부 ② `frozen.ANALYSIS_FIELDS` 투영이 evidence의 Reaction 필드를 버림 ③ 출력 루트가 MVP 실행 루트(`experiment-analysis`)와 다르고, 그 아래로 쓰기를 거부 ④ 파일 이름이 `findings.json`/`results.json` 과 다름 | `test_join_rows_cannot_enter_finding_engine`, `test_finding_engine_rejects_any_reaction_marked_video`, `test_reaction_fields_in_evidence_never_reach_mvp_findings`, `test_mvp_contracts_have_no_reaction_fields`, `test_output_root_is_separate_new_directory`, `test_finding_engine_default_unchanged_without_reaction_fields` |

MVP 격리를 풀 옵션은 **없다.** 검증을 통과한 뒤 Reaction을 MVP 입력으로 들이려면 사람 결정 후
`finding.py` 의 가드와 계약을 코드로 바꿔야 한다.

## 5. 하지 않은 것

taxonomy·sealed fixture·split 파일·frozen registry 변경, `aggregate.py`·`schema.sql`·`docs/prototype` 수정,
새 DB 표, 유료 API 호출, 실제 댓글·실제 DB로 실행, 포함 확률 가중, 다중 비교 보정, 체인 후보.

## 6. 사람이 정할 것

1. **최소 n.** `MIN_LABELED_PER_VIDEO = 30` 유지 여부. 희귀 코드(R5·R10 등)는 30건에서도 비율이 0 근처에
   몰린다 — 코드별로 다른 최소치를 둘지.
2. **어떤 특징을 볼지.** 지금은 동결 registry의 모든 특징 × 18개 비율을 전부 계산한다. 사전에 가설 쌍을
   정해 비교 수를 줄일지(다중 비교), A-1/A-2/A-3 중 어느 층을 먼저 볼지.
3. **검증 전에 돌릴지.** 재개 결정은 결과를 「검증 전 AI 판정」으로 표시하면 리포트에 실을 수 있다고
   하지만, 결합 분석 결과를 보고 프롬프트·특징 정의를 고치면 fresh 표본과 Development가 오염된다.
   Development에서 먼저 돌릴지, fresh 검증 통과 후에만 돌릴지. Holdout은 검증 통과 전에는 열지 않는 것을 제안한다.
4. **분모 선택.** 원댓글만(기본) 대 답글 포함, Target 분모를 반응 있는 댓글로 둘지 판정 댓글 전체로 둘지.
5. **표본 가중.** census가 아닌 split(Discovery stratified, Holdout blind)에 쓸 때 `inclusion_prob` 가중 또는 층 고정을 넣을지.
6. **capped 영상 처리.** `completeness = capped` 인 영상(정렬 편향이 남은 표본)을 포함할지, 민감도 분석으로 분리할지.
7. **입력 경로.** 지금은 `comments`·`comment_reactions` DB만 읽는다. fresh raw 표본의 라벨 파일
   (`reaction-labels-v1`, video_id 없음)을 댓글→영상 대응표와 함께 받을지.
8. **Discovery 허용 여부.** 지금은 거부한다. 특징 발견 단계에서 Reaction을 참고 자료로 볼지.
