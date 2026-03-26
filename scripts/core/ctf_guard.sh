#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ctf_guard.sh [options] -- <command> [args...]

Options:
  --label <name>         Label for logging (default: task)
  --max-retries <n>      Retry count after first attempt (default: 2)
  --timeout-sec <n>      Timeout per attempt in seconds (default: 180)
  --budget-min <n>       Total budget in minutes (default: 20)
  --backoff-sec <n>      Base backoff seconds (default: 2)
  --light               Single-attempt mode: max-retries=0, budget-min=3, backoff-sec=0
  --log-file <path>      Log file path (default: ./runtime/logs/guard.log)
USAGE
}

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

LABEL="task"
MAX_RETRIES=2
TIMEOUT_SEC=180
BUDGET_MIN=20
BACKOFF_SEC=2
LOG_FILE="./runtime/logs/guard.log"
LIGHT_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --max-retries)
      MAX_RETRIES="$2"
      shift 2
      ;;
    --timeout-sec)
      TIMEOUT_SEC="$2"
      shift 2
      ;;
    --budget-min)
      BUDGET_MIN="$2"
      shift 2
      ;;
    --backoff-sec)
      BACKOFF_SEC="$2"
      shift 2
      ;;
    --light)
      LIGHT_MODE=1
      shift
      ;;
    --log-file)
      LOG_FILE="$2"
      shift 2
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

if [[ "$LIGHT_MODE" == "1" ]]; then
  MAX_RETRIES=0
  BUDGET_MIN=3
  BACKOFF_SEC=0
fi

if [[ $# -eq 0 ]]; then
  echo "No command provided" >&2
  usage
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"

start_ts="$(date +%s)"
budget_sec="$((BUDGET_MIN * 60))"
attempt=0
max_attempts="$((MAX_RETRIES + 1))"

while (( attempt < max_attempts )); do
  attempt="$((attempt + 1))"

  now_ts="$(date +%s)"
  elapsed="$((now_ts - start_ts))"
  if (( elapsed >= budget_sec )); then
    echo "[-] Budget exceeded before attempt $attempt"
    exit 124
  fi

  cmd_str="$(printf '%q ' "$@")"
  echo "[+] [$LABEL] attempt $attempt/$max_attempts"
  echo "[+] command: $cmd_str"

  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "$TIMEOUT_SEC" "$@"
    rc=$?
  else
    "$@"
    rc=$?
  fi
  set -e

  ts="$(date -Iseconds)"
  log_line="{\"timestamp\":\"$(json_escape "$ts")\",\"label\":\"$(json_escape "$LABEL")\",\"attempt\":$attempt,\"max_attempts\":$max_attempts,\"timeout_sec\":$TIMEOUT_SEC,\"exit_code\":$rc,\"elapsed_sec\":$elapsed,\"command\":\"$(json_escape "$cmd_str")\"}"
  echo "$log_line" >> "$LOG_FILE"

  if [[ "$rc" -eq 0 ]]; then
    echo "[+] [$LABEL] success on attempt $attempt"
    exit 0
  fi

  if (( attempt < max_attempts )); then
    sleep_sec="$((BACKOFF_SEC * attempt))"
    echo "[!] [$LABEL] failed with code $rc, retry in ${sleep_sec}s"
    sleep "$sleep_sec"
  else
    echo "[-] [$LABEL] failed after $max_attempts attempts"
    exit "$rc"
  fi
done
