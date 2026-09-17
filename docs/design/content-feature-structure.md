# Content Feature Structure — Human-confirmed

2026-09-17 인간 확정 결정의 보존 복구.

현재 Feature 작업은 Reaction보다 후순위로 일시 정지돼 있다.

하지만 이미 확정한 구조는 저장소에 남겨야 한다.

Content Feature는 **프로그램이 정보를 얻는 방식**에 따라 다음 세 층으로 구분한다.

## A-1. 직접/기본 정보

영상 파일을 의미적으로 이해하지 않아도 직접 얻을 수 있는 객관적 정보.

예:

* 영상 길이
* 게시 시각
* 업로드 간격
* 제목의 원시적 속성

주의:

raw views / likes / comments 같은 **성과값은 Content Feature가 아니라 Performance(C)**에 속한다.

## A-2. 미디어 측정

영상의 시청각 신호를 계산·측정해서 얻는 정보.

현재 PoC 후보:

* cuts_per_minute
* median_shot_duration_sec
* silence_ratio
* speech_ratio

영상 길이는 A-1에서 이미 확보 가능하므로 A-2 media PoC에서 중복 측정할 필요가 없다.

## A-3. 의미 이해

영상의 의미·맥락을 이해해야 판정할 수 있는 특성.

예:

* 인터뷰
* 토론
* 전문가 등장
* 먹방
* 리뷰
* 게스트
* 순위/월드컵
* PPL
* 개인 이야기
* 분위기/tone
* 출연 구성
* setting

목표 구조:

**인간 discovery → AI 자동 추출 → 인간 검증**

인간 discovery의 목적은 사람이 영원히 Feature를 입력하는 것이 아니라,

**AI가 앞으로 무엇을 찾아야 하는지를 발견하고 검증 기준을 만드는 것**이다.

이 문서는 구조적 결정의 canonical 기록이다. 예시는 확정·동결된 registry 항목 목록이 아니며 A-2는 PoC 후보다. 이번 보존 복구에서는 registry 변경, Feature freeze 또는 자동 추출 구현을 수행하지 않는다.
