#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ctf_throttle.sh [options] -- <command> [args...]

Options:
  --max-lines <n>     Max total lines before truncation (default: 400)
  --max-bytes <n>     Max total bytes before truncation (default: 65536)
  --head-lines <n>    Lines to show from start when truncating (default: 120)
  --tail-lines <n>    Lines to show from end when truncating (default: 80)
  --mode <mode>       head|tail|both (default: both)
  --save <file>       Append full output to file
  --cleanup           Remove temp output file (default: keep and show path)
USAGE
}

MAX_LINES=400
MAX_BYTES=65536
HEAD_LINES=120
TAIL_LINES=80
MODE="both"
SAVE_FILE=""
CLEANUP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-lines)
      MAX_LINES="$2"
      shift 2
      ;;
    --max-bytes)
      MAX_BYTES="$2"
      shift 2
      ;;
    --head-lines)
      HEAD_LINES="$2"
      shift 2
      ;;
    --tail-lines)
      TAIL_LINES="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --save)
      SAVE_FILE="$2"
      shift 2
      ;;
    --cleanup)
      CLEANUP=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ $# -eq 0 ]]; then
  echo "No command provided" >&2
  usage
  exit 1
fi

tmp="$(mktemp)"
set +e
"$@" >"$tmp" 2>&1
rc=$?
set -e

if [[ -n "$SAVE_FILE" ]]; then
  mkdir -p "$(dirname "$SAVE_FILE")"
  cat "$tmp" >> "$SAVE_FILE"
fi

bytes="$(wc -c < "$tmp" | tr -d ' ')"
lines="$(wc -l < "$tmp" | tr -d ' ')"

if (( bytes <= MAX_BYTES && lines <= MAX_LINES )); then
  cat "$tmp"
else
  echo "[ctf_throttle] output truncated: ${lines} lines, ${bytes} bytes"
  case "$MODE" in
    head)
      head -n "$HEAD_LINES" "$tmp"
      ;;
    tail)
      tail -n "$TAIL_LINES" "$tmp"
      ;;
    both)
      head -n "$HEAD_LINES" "$tmp"
      echo "..."
      tail -n "$TAIL_LINES" "$tmp"
      ;;
    *)
      echo "[ctf_throttle] invalid mode: $MODE (expected head|tail|both)" >&2
      ;;
  esac
  if [[ "$CLEANUP" -eq 0 ]]; then
    echo "[ctf_throttle] full output saved at: $tmp"
  fi
fi

if [[ "$CLEANUP" -eq 1 ]]; then
  rm -f "$tmp"
fi

exit "$rc"
