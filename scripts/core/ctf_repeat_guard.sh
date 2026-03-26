#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ctf_repeat_guard.sh [options] -- <command> [args...]

Options:
  --window-sec <n>     Time window for duplicate detection (default: 1200)
  --log-file <path>    Log file path (default: ./runtime/logs/command.log)
  --note <text>        Justification for repeating the same command (allows repeat)
  --allow-repeat       Allow repeat without note (still logged)
USAGE
}

WINDOW_SEC=1200
LOG_FILE="./runtime/logs/command.log"
NOTE=""
ALLOW_REPEAT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --window-sec)
      WINDOW_SEC="$2"
      shift 2
      ;;
    --log-file)
      LOG_FILE="$2"
      shift 2
      ;;
    --note)
      NOTE="$2"
      shift 2
      ;;
    --allow-repeat)
      ALLOW_REPEAT=1
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

mkdir -p "$(dirname "$LOG_FILE")"

cmd_str="$(printf '%q ' "$@")"
cmd_hash="$(printf '%s' "$cmd_str" | sha256sum | awk '{print $1}')"
now_ts="$(date +%s)"

last_ts=""
last_note=""
if [[ -f "$LOG_FILE" ]]; then
  last_ts="$(awk -F',' -v h="$cmd_hash" '$2==h {print $1}' "$LOG_FILE" | tail -n 1)"
  last_note="$(awk -F',' -v h="$cmd_hash" '$2==h {print $4}' "$LOG_FILE" | tail -n 1)"
fi

if [[ -n "$last_ts" ]]; then
  delta="$((now_ts - last_ts))"
  if (( delta <= WINDOW_SEC )) && [[ "$ALLOW_REPEAT" -eq 0 && -z "$NOTE" ]]; then
    echo "[-] duplicate command blocked (within ${WINDOW_SEC}s): $cmd_str" >&2
    echo "    last_note: ${last_note:-none}" >&2
    echo "    re-run with --note \"<reason>\" or --allow-repeat to proceed" >&2
    exit 125
  fi
fi

printf '%s,%s,%s,%s\n' "$now_ts" "$cmd_hash" "$cmd_str" "${NOTE:-}" >> "$LOG_FILE"

exec "$@"
