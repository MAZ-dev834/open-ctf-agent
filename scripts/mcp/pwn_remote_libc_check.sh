#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  pwn_remote_libc_check.sh --project <workspace/project-dir>

Output:
- Prints whether remote libc/ld appears to be provided by attachments.
- Lists matching lines from scripts/Docker configs.
USAGE
}

PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT="$2"
      shift 2
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

if [[ -z "$PROJECT" ]]; then
  usage
  exit 1
fi

if [[ ! -d "$PROJECT" ]]; then
  echo "Project dir not found: $PROJECT" >&2
  exit 1
fi

ROOTS=(
  "$PROJECT"
  "$PROJECT/题目附件"
  "$PROJECT/attachments"
  "$PROJECT/attachments/extracted"
  "$PROJECT/题目附件/extracted"
)

PATTERN='LD_PRELOAD|LD_LIBRARY_PATH|--library-path|ld-linux|ld-2\\.\\d+\\.so|libc\\.so|glibc|patchelf'
FILES_PATTERN='(start|run|launch|entry|init|server|xinetd|nsjail|docker|compose|Dockerfile|service).*'

found=0
confirmed=0

echo "[+] Remote libc/ld check for project: $PROJECT"

for root in "${ROOTS[@]}"; do
  [[ -d "$root" ]] || continue
  if rg -n -S "$FILES_PATTERN" "$root" >/dev/null 2>&1; then
    :
  fi
  matches="$(rg -n -S "$PATTERN" "$root" 2>/dev/null || true)"
  if [[ -n "$matches" ]]; then
    found=1
    echo "== Matches in $root =="
    echo "$matches"
    if echo "$matches" | rg -q -i 'LD_PRELOAD|--library-path|ld-2\\.|ld-linux'; then
      confirmed=1
    fi
  fi
done

if [[ "$confirmed" -eq 1 ]]; then
  echo "[RESULT] confirmed: attachments likely define remote libc/ld"
elif [[ "$found" -eq 1 ]]; then
  echo "[RESULT] possible: references found but not definitive"
else
  echo "[RESULT] unknown: no libc/ld hints found in attachments"
fi
