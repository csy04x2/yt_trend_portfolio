# 침착맨 Feature Discovery 재현 — Claude, 2026-09-14

팀원 11일자 보고(「Discovery 90개 보고 특징 찾기 → 12개 → Registry A-v0.1 동결」)를
같은 도구로 따라 해 본 결과. **팀원 결과가 아니다.** 비교용 두 번째 판정자다.

## 조건과 한계

- 입력: `docs/prototype/chim-evidence.json`의 300편에서 **제목·길이·게시일·코너**만 추출
  (`chim-content.json`). 설명·자막 없음. 로컬에 DB가 없어서다.
- 분할: 브랜치 `feat/feature-discovery-experiment`의 `split_dataset.py`, seed 42 →
  discovery 90 / development 90 / holdout 120 (`split.csv`). 팀원이 같은 seed를 썼다면
  같은 분할이지만, 팀원의 입력 파일이 다르면(설명·자막 포함) ID 순서화는 같아도 확인 필요.
- 블라인드: 성과 열은 `export_blind_discovery.py`가 차단. 단, 판정자(Claude)는 이 작업
  전에 배수 상위 10편 제목을 본 상태였다. 그중 Discovery 90에 든 것은 「그야... 재밌으니까」
  「I punch like King Kong to 침착맨」 2편.
- 리센느 관련 4편은 Discovery 90에 들지 않았다.
- 판정자: Claude 단독(source=llm). 사람 후보 없음.

## 후보 16개 → 채택 12개

Discovery 90편 제목 키워드 1차 판정. content형은 제목에 없으면 U, form형(제목 자체가
근거)은 없으면 0.

| 후보 | 1 | 0 | U | 쇼츠/롱폼 | 채택 |
|---|---:|---:|---:|---|---|
| guest_external 외부 게스트 | 16 | 0 | 74 | 2/14 | ○ |
| food_eating 음식·먹방 | 14 | 0 | 76 | 2/12 | ○ |
| expert_knowledge 전문 지식 전달 | 13 | 0 | 77 | 2/11 | ○ |
| one_hour_plus 60분 초과 | 11 | 79 | 0 | 0/11 | ○ |
| pop_culture_ip IP·캐릭터 참조 | 10 | 0 | 80 | 6/4 | ○ |
| recurring_bit 반복 시리즈 표식 | 9 | 81 | 0 | 8/1 | ○ |
| title_quote 대사 인용 제목 | 8 | 82 | 0 | 8/0 | ○ |
| title_wordplay 말장난 제목 | 8 | 82 | 0 | 8/0 | ○ |
| guest_in_title 제목에 게스트 표기 | 7 | 83 | 0 | 0/7 | ○ |
| tournament_ranking 월드컵·순위 | 6 | 0 | 84 | 2/4 | ○ |
| host_in_title 제목에 진행자 | 6 | 84 | 0 | 4/2 | ○ |
| media_review 작품 리뷰·추천 | 5 | 0 | 85 | 1/4 | ○ |
| tech_business_topic AI·기업 | 6 | 0 | 84 | 1/5 | × 경계 모호 |
| fear_horror 공포·범죄 | 6 | 0 | 84 | 2/4 | × 소재 축과 중복 |
| viewer_submission 시청자 사연 | 3 | 0 | 87 | 1/2 | × 표본 3 |
| question_hook 질문형 제목 | 2 | 88 | 0 | 0/2 | × 표본 2 |

키워드 판정의 오탐 예: 「세계 최강의 검사」→tournament, 「침착맨 추천작」→tournament.
사람이 다시 봐야 한다. `discovery90-labels.json`에 90×16 판정이 그대로 있다.

## 여기서 보인 것

1. **제목만으로는 content형 특징에 0을 줄 수 없다.** 8개 content형 후보의 U가 74~87.
   자막이나 설명이 없으면 「없음」을 증명할 수 없어서다. 팀원의 12개도 자막 없이
   판정했다면 같은 벽을 만났을 것이다. Development 단계에서 U를 0으로 뭉개면 안 된다.
2. **쇼츠와 롱폼의 특징이 갈린다.** 제목형 특징(대사 인용·말장난·반복 표식)은 거의
   쇼츠 전용, 내용형(게스트·먹방·특강·60분 초과)은 롱폼 전용. 성과 세 판(쇼츠/롱폼/합침)을
   나눈 것처럼 특징도 축별로 따로 봐야 한다.
3. **게스트는 둘로 갈라야 한다.** 「출연했는가」(content)와 「제목에 썼는가」(form)는
   다른 특징이고, 후자만 제목으로 0/1이 된다. 리센느 문제와 직결된다 — 이상치 묶음을
   특징으로 오인하지 않으려면 「고정 크루 명단」을 먼저 문서로 고정해야 한다.

## 팀원이 자기 12개로 바꿔 돌리는 법

판정과 정의는 **입력 파일**이고, 급등 영상 표시·분모 재계산·전체/제외 두 판·홀드아웃 봉인은
`backend/feature_outcome/` 코드다. 파일 둘만 바꾸면 같은 분석이 팀원 판정으로 돈다.

1. `registry-claude-v0.1.json` 자리에 Registry A-v0.1 JSON을 둔다 (팀원 `registry.py` 형식 그대로).
2. `labels-title-regex-300.json` 자리에 판정 파일을 둔다. 형식은
   `{"labels": {"<video_id>": {"<feature_id>": 0 | 1 | "U"}}}`. U는 0이 아니다 — 코드가 U를 세지 않는다.
3. 실행 (backend 폴더에서):

```
python -m feature_outcome run \
  --evidence ../docs/prototype/chim-evidence.json \
  --split    fixtures/labeled/discovery-chim-claude-20260914/split.csv \
  --registry <팀원 registry.json> \
  --labels   <팀원 labels.json> \
  --events   fixtures/labeled/discovery-chim-claude-20260914/events.json \
  --out      <출력 폴더>
```

`--u-as-control`은 **빼고** 돈다. 그 옵션은 제목 정규식 자리표시자(content형이 0을 못 내는
판정)에서만 쓴다. `--split-name holdout`은 기본 거부이며, 정의를 동결한 뒤 `--unseal-holdout`으로
한 번만 연다. `--k-iqr`, `--multiple-min`, `events.json`이 급등 영상 규칙이고, 바꾸면 보고서 머리에 찍힌다.

## 피드백이 코드로 들어간 자리

| 피드백 | 어디 |
|---|---|
| 급등 영상을 빼고 비교 | `breakout.py` — 삭제 없이 표시. 모든 표가 전체→제외 두 판 |
| 리센느가 이웃 배수를 누른다 | `recompute_multiples` — 분모(동료 중앙값)에서 급등 영상 제외 |
| 한 편이 만든 결론 잡기 | `outcome.py` — 부호반전·붕괴·LOO 판정 |
| Discovery에 대박 영상이 섞이면 안 됨 | 보고서 1절 「분할별 급등 영상」 — discovery에 있으면 다시 자르라고 표시 |
| 홀드아웃은 한 번만 | `HoldoutSealed` — 기본 거부 |
| 제목만 본 판정의 한계 | U를 세지 않음. 자리표시자 옵션을 켜면 보고서에 경고 |

## 대시보드

`docs/prototype/report-prototype.html` 08번 「급등 영상과 특징」 페이지가 이 결과를 보여 준다.
데이터는 `python -m feature_outcome run ... --evidence-out ../docs/prototype/chim-evidence.json`이
evidence JSON에 `feature_outcome` 키로 붙이고, `python scripts/render_prototype.py`가 DB 없이
HTML을 다시 그린다. 주의: `build_chim_prototype.py`로 DB에서 evidence를 새로 만들면 이 키가
사라지므로, 그 뒤에 `feature_outcome run --evidence-out`을 다시 돌린다.

대시보드에서 특징은 **영상마다 붙은 태그**다. `feature_outcome run --evidence-out`이 판정 파일의
0/1/U를 그대로 evidence JSON에 싣고, 화면은 그것만 읽는다.

- 툴바 「특징」 선택: 「이름 · 있음」「이름 · 없음」을 고르면 **모든 페이지**(지표 카드·산점도·표·
  특성 효과·월별 막대)가 그 영상들만으로 다시 계산된다. U인 영상은 양쪽 어디에도 들어가지 않는다.
- 영상 표의 제목 아래에 있음(1)인 특징이 칩으로 붙고, 상세 창에는 없음·U까지 전부 보인다.
- 특징 이름은 레지스트리의 `name`, 판정은 판정 파일에서 온다. 팀원의 12개로 바꾸고 같은 명령을
  돌리면 선택 목록·칩·④ 표가 전부 그 12개로 바뀐다. 템플릿을 고칠 필요가 없다.

## 판정 파일을 AI로 만들기 — 채널 단위 추출기

제목 정규식 자리표시자를 대체할 판정 파일은 `tools/feature_extractor/channel.py`가 만든다
(저장소 루트에서 실행). 제목·설명 → 자막 → 장면 순서로 보고, 한 영상에 한 번 물어 모든 특징을
0/1/U로 받는다. 출력 `labels.json`은 이 폴더의 `labels-title-regex-300.json` 자리에 그대로 들어간다.

```
python -m tools.feature_extractor.channel run --content docs/prototype/chim-evidence.json \
  --registry <레지스트리> --split <split.csv> --scope development --out <새 폴더> \
  --captions <자막 폴더> --evidence-root <stage2 패킷 폴더> --judge api --model <ID> --cache <캐시 폴더>
```

자막·장면 없이 돌리면 제목만 보는 것과 같으니(U가 대부분) 먼저 `tools/stage2_evidence`로
증거를 모은다. 사람 정답과의 대조는 `channel.py evaluate`로 잰다 — 침착맨 development 90의
게스트 출연 사람 정답이 `../discovery-chim-human-20260917/`에 있다.

## 14F 특징 적용 결과가 오면 — 진행 절차

팀원이 친구에게 맡긴 14F Human Discovery(90편) 결과와 그 뒤의 LLM Discovery가 오면 아래 순서로
간다. 순서를 지키는 이유는 하나다 — **사람 결과가 LLM 결과에, 발견이 성과에 오염되지 않게.**

1. **사람 판정 먼저 동결.** 친구가 보낸 Registry와 판정 JSON을 그대로
   `backend/fixtures/labeled/discovery-14f-<날짜>/`에 커밋한다. 고치지 않는다. 그 다음에야
   14F LLM Discovery를 돌리고, 두 목록을 나란히 놓고 겹침·유사·고유로 나눈 표를 만든다.
2. **14F 급등 영상 표시.** 14F evidence JSON을 만들고(`observable.build`, DB 필요) 같은 규칙으로
   `feature_outcome run`을 돌린다. 14F에는 리센느 같은 사건이 없으므로 `events.json`은
   비운다. 보고서 1절 「분할별 급등 영상」에 discovery가 0이 아니면 패킷을 다시 자른다.
3. **같은 채널 안에서 두 판.** 14F Development 90에서 14F 특징을 전체·제외로 돌린다.
   부호반전·붕괴·LOO가 0을 지나는 특징은 14F 안에서도 탈락이다. 판정 파일이 자막 기반이면
   `--u-as-control` 없이 돌린다. 그때 U 비율이 침착맨 자리표시자(74~87/90)보다 얼마나
   줄었는지가 「자막이 U를 얼마나 없애는가」의 첫 수치다.
4. **코너와 겹치는 특징 걸러내기.** 14F는 롱폼의 72%가 코너다. 특징이 사실은 코너 이름의
   다른 표현(돈슐랭 = 음식·먹방)이면 새 정보가 아니다. 특징 × 코너 배정의 겹침을 표로 내고,
   같은 코너 안에서도 효과가 남는 특징만 남긴다. 이건 코드에 아직 없다 — 이 단계에서 넣는다.
5. **채널 횡단 교차 적용.** 침착맨 특징을 14F Development에, 14F 특징을 침착맨 Development에
   서로 대 본다. 판정 파일만 바꾸면 되므로 코드 변경은 없다. 두 채널 모두에서 부호가 같고
   급등 영상 제외 후에도 남는 특징만 「구조 후보」로 올린다. 한 채널에만 있는 특징은 실패가
   아니라 채널 고유 특성이고, 그렇게 기록한다.
6. **홀드아웃은 살아남은 특징만, 한 번.** 구조 후보에 한해 두 채널 홀드아웃을
   `--unseal-holdout`으로 연다. 연 뒤에는 정의를 고치지 않는다. 고치면 새 실험이고 분할을
   다시 잘라야 한다.
7. **세 번째 채널은 성장 채널로.** 침착맨·14F 둘 다 정점 채널이라는 지적이 남아 있다.
   게시 월별 중앙 조회수가 오르는 중간 규모 채널을 발견 집합으로 받고, 두 채널은 대조군으로
   돌린다. 「성장 중」의 정의는 스냅샷이 쌓여야 정확해지므로 당장은 코호트 기울기로 고른다.

각 단계의 산출물은 같은 `feature_outcome` 보고서 형식이라 침착맨 결과와 표 단위로 비교된다.

## 파일

- `registry-claude-v0.1.json` — 재현본 12개 정의. **교체 대상.**
- `labels-title-regex-300.json` — 제목 정규식 자리표시자 판정 300편. **교체 대상.**
- `title-regex-config.json` — 자리표시자 규칙. `python -m feature_outcome labels`로 재생성.
- `events.json` — 사건 묶음(리센느 주간). 사람이 고친다.
- `split.csv`, `chim-content.json`, `packet/` — seed 42 분할과 블라인드 패킷.
- `report/` — `report.md`, `breakout.csv`(300편 전부, 새 배수 포함), `results.json`.
- `comment-pilot.json`, `comment-pilot.md` — 댓글에서 콘텐츠 특징 신호 소규모 시험.
