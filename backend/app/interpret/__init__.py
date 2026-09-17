"""Stage 09 — Stage 08 이 만든 사실(수치)을 골라 사람이 읽는 문장으로 바꾼다.

경계 (docs/design/youtube-trend-architecture.md 「현재 canonical 경계」):
Stage 08 은 집계·관계 계산까지, 해석은 여기서만 한다. 이 패키지는 수치를 새로
계산하지 않고, `app.pipeline` 쪽 집계 코드는 이 패키지를 import 하지 않는다.
"""
