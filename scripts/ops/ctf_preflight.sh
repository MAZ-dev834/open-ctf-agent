#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

EVENT_DIR="${EVENT_DIR:-}"
REQUIRE_AUTH="${REQUIRE_AUTH:-1}"
CHECK_MCP="${CHECK_MCP:-0}"
CHECK_PATH_SANITY="${CHECK_PATH_SANITY:-1}"
MAX_UNKNOWN_LATEST_PCT="${MAX_UNKNOWN_LATEST_PCT:-5}"
MAX_SUBMIT_RATELIMIT_PCT="${MAX_SUBMIT_RATELIMIT_PCT:-30}"
MAX_DUP_KEYS="${MAX_DUP_KEYS:-0}"

usage() {
  cat <<'USAGE'
Usage:
  ctf_preflight.sh [--event-dir <dir>] [--require-auth 0|1] [--check-mcp 0|1] [--check-path-sanity 0|1]

Env overrides:
  EVENT_DIR
  REQUIRE_AUTH (default 1)
  CHECK_MCP (default 0)
  CHECK_PATH_SANITY (default 1)
  MAX_UNKNOWN_LATEST_PCT (default 5)
  MAX_SUBMIT_RATELIMIT_PCT (default 30)
  MAX_DUP_KEYS (default 0)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --event-dir)
      EVENT_DIR="$2"
      shift 2
      ;;
    --require-auth)
      REQUIRE_AUTH="$2"
      shift 2
      ;;
    --check-mcp)
      CHECK_MCP="$2"
      shift 2
      ;;
    --check-path-sanity)
      CHECK_PATH_SANITY="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[preflight] unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

echo "== CTF Preflight =="
echo "- root: $ROOT_DIR"
if [[ -f "$ROOT_DIR/.env.example" ]]; then
  echo "- env example: $ROOT_DIR/.env.example"
fi

missing=0
warn=0

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[FAIL] missing command: $cmd"
    missing=$((missing + 1))
  else
    echo "[ OK ] command: $cmd"
  fi
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[FAIL] missing file: $path"
    missing=$((missing + 1))
  else
    echo "[ OK ] file: $path"
  fi
}

echo "[1/6] core commands"
require_cmd python3
require_cmd bash

echo "[cap] runtime capability matrix"
for cmd in opencode docker tesseract convert file strings sqlite3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "[cap] $cmd=present"
  else
    echo "[cap] $cmd=missing"
  fi
done
python3 - <<'PY'
from scripts.core.runtime_config import runtime_capabilities
caps = runtime_capabilities()
for key in sorted(caps):
    print(f"[cap] {key}={caps[key]}")
PY

echo "[2/6] core scripts"
require_file scripts/ops/ctf_health_report.py
require_file scripts/ops/ctf_path_sanity.py
require_file scripts/submit/ctf_pipeline_submit_gate.py
require_file scripts/submit/ctf_submit_candidates.py
require_file scripts/index/ctf_index_build.py
require_file scripts/index/ctf_index_query.py

echo "[3/6] auth checks"
BASE_URL="${CTFD_BASE_URL:-}"
SESSION="${CTFD_SESSION:-}"
TOKEN="${CTFD_TOKEN:-}"
if [[ -n "$EVENT_DIR" && -f "$EVENT_DIR/.env" ]]; then
  # shellcheck disable=SC1090
  source "$EVENT_DIR/.env"
  BASE_URL="${CTFD_BASE_URL:-$BASE_URL}"
  SESSION="${CTFD_SESSION:-$SESSION}"
  TOKEN="${CTFD_TOKEN:-$TOKEN}"
  echo "[ OK ] loaded env: $EVENT_DIR/.env"
fi

if [[ "$REQUIRE_AUTH" == "1" ]]; then
  if [[ -z "$BASE_URL" ]]; then
    echo "[FAIL] missing CTFD_BASE_URL (env or --event-dir/.env)"
    missing=$((missing + 1))
  else
    echo "[ OK ] CTFD_BASE_URL present"
  fi
  if [[ -z "$SESSION" && -z "$TOKEN" ]]; then
    echo "[FAIL] missing CTFD_SESSION/CTFD_TOKEN"
    missing=$((missing + 1))
  else
    echo "[ OK ] auth token/session present"
  fi
else
  echo "[ .. ] auth check skipped (REQUIRE_AUTH=0)"
fi

echo "[4/6] path sanity"
if [[ "$CHECK_PATH_SANITY" == "1" ]]; then
  if python3 scripts/ops/ctf_path_sanity.py --root "$ROOT_DIR" --max-depth 2 >/dev/null 2>&1; then
    echo "[ OK ] workspace path sanity passed"
  else
    echo "[FAIL] suspicious path names detected; run: python3 scripts/ops/ctf_path_sanity.py --root \"$ROOT_DIR\""
    missing=$((missing + 1))
  fi
else
  echo "[ .. ] path sanity check skipped (CHECK_PATH_SANITY=0)"
fi

echo "[5/6] health thresholds"
HR_ARGS=(--json)
if [[ -n "$EVENT_DIR" ]]; then
  HR_ARGS+=(--event-dir "$EVENT_DIR")
fi
HR_JSON="$(python3 scripts/ops/ctf_health_report.py "${HR_ARGS[@]}")"
if python3 - "$HR_JSON" "$MAX_UNKNOWN_LATEST_PCT" "$MAX_SUBMIT_RATELIMIT_PCT" "$MAX_DUP_KEYS" <<'PY'
import json,sys
data=json.loads(sys.argv[1])
max_unknown=float(sys.argv[2])
max_rl=float(sys.argv[3])
max_dup=float(sys.argv[4])
dup=float(data["workspace"]["duplicate_project_keys"])
unknown=float(data["memory"]["unknown_latest_pct"])
rl=float(data["submit"]["submit_ratelimit_pct"])
print(f"[info] duplicate_project_keys={dup:g} (max {max_dup:g})")
print(f"[info] unknown_latest_pct={unknown:g} (max {max_unknown:g})")
print(f"[info] submit_ratelimit_pct={rl:g} (max {max_rl:g})")
flag=0
if dup>max_dup:
    print("[warn] duplicate keys over threshold")
    flag=1
if unknown>max_unknown:
    print("[warn] unknown latest pct over threshold")
    flag=1
if rl>max_rl:
    print("[warn] submit ratelimit pct over threshold")
    flag=1
sys.exit(flag)
PY
then
  :
else
  warn=$((warn + 1))
fi

echo "[6/6] optional MCP"
if [[ "$CHECK_MCP" == "1" ]]; then
  if [[ -x scripts/mcp/mcp_healthcheck.sh ]]; then
    if scripts/mcp/mcp_healthcheck.sh pwn-re >/dev/null 2>&1; then
      echo "[ OK ] MCP pwn-re healthcheck passed"
    else
      echo "[warn] MCP pwn-re healthcheck failed"
      warn=$((warn + 1))
    fi
  else
    echo "[warn] scripts/mcp/mcp_healthcheck.sh not executable"
    warn=$((warn + 1))
  fi
else
  echo "[ .. ] MCP check skipped (CHECK_MCP=0)"
fi

echo "[hint] docs entrypoints: docs/README.md docs/PARAMS.md docs/TOOLS.md"

echo "== Preflight Summary =="
echo "- hard_failures: $missing"
echo "- warnings: $warn"

if [[ "$missing" -gt 0 ]]; then
  exit 1
fi
exit 0
