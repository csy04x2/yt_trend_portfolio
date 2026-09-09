#!/usr/bin/env bash
# Stop 훅: 세션이 끝날 때 점수와 변경 내역을 HISTORY.md에 남긴다.
#
# 기록하는 것 세 가지:
#   1. 채점기 점수 (app/eval.py --json)
#   2. 이번 세션에 무엇이 바뀌었는지 (git diff --stat)
#   3. 에이전트가 .claude/loop/NOTES.md에 쓴 "잘 안 된 것"
#
# 훅은 무엇이 잘 안 됐는지 스스로 알 수 없다. 그 서술은 에이전트가 NOTES.md에
# 쓰고, 이 훅이 그것을 HISTORY.md로 옮긴 뒤 비운다. 훅은 숫자와 시각을 맡는다.
#
# 실패해도 절대 세션을 막지 않는다 (fail open).

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HISTORY="$ROOT/.claude/loop/HISTORY.md"
NOTES="$ROOT/.claude/loop/NOTES.md"

# 파이썬 찾기 — 새로 설치한 경우 PATH가 낡아 있을 수 있다
PY=""
for c in python python3 "${LOCALAPPDATA:-}/Programs/Python/Python313/python.exe"; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && exit 0

SCORE="$(cd "$ROOT/backend" && PYTHONIOENCODING=utf-8 "$PY" -m app.eval --json 2>/dev/null)"
[ -z "$SCORE" ] && SCORE='{"error":"채점기를 돌리지 못했다"}'

if printf '%s' "$SCORE" | grep -q '"goal_met": *true'; then GOAL_MET="달성"; else GOAL_MET="미달"; fi
STAT="$(cd "$ROOT" && git diff --stat HEAD -- backend .claude 2>/dev/null | tail -6)"
[ -z "$STAT" ] && STAT="(변경 없음)"

{
  echo ""
  echo "## $(date '+%Y-%m-%d %H:%M') · 목표 $GOAL_MET"
  echo ""
  echo '```json'
  printf '%s\n' "$SCORE"
  echo '```'
  echo ""
  echo "**변경**"
  echo '```'
  printf '%s\n' "$STAT"
  echo '```'
  if [ -s "$NOTES" ]; then
    echo ""
    printf '%s\n' "$(cat "$NOTES")"
    : > "$NOTES"   # 옮겼으니 비운다. 다음 이터레이션이 새로 쓴다
  else
    echo ""
    echo "*(NOTES.md 비어 있음 — 에이전트가 기록을 남기지 않았다)*"
  fi
  echo ""
  echo "---"
} >> "$HISTORY"

# systemMessage는 JSON 문자열이라 점수를 그대로 끼우면 따옴표가 깨진다. 숫자만 뽑는다.
ACC="$(printf '%s' "$SCORE" | grep -o '"accuracy": *[0-9.]*' | grep -o '[0-9.]*$')"
FD="$(printf '%s' "$SCORE" | grep -o '"false_drop": *[0-9]*' | grep -o '[0-9]*$')"
printf '{"systemMessage":"루프 기록 · 목표 %s · 정확도 %s · 오탐 %s"}\n' "$GOAL_MET" "${ACC:-?}" "${FD:-?}"
exit 0
