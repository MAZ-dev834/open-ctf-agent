#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"
COPY_ENV=1
WITH_WEB_TOOLS=0
WITH_PWN_RE_TOOLS=0
WITH_OPENCODE_PLUGIN=0

usage() {
  cat <<'USAGE'
Usage:
  setup_env.sh [--venv <dir>|--no-venv] [--no-env-copy] [--with-web-tools] [--with-pwn-re-tools] [--with-opencode-plugin]

What it does:
  1. Create a Python virtualenv (default: ./.venv)
  2. Install Python requirements
  3. Copy .env.example -> .env.local if missing
  4. Create local runtime directories: events/ workspace/ runtime/

Optional extras:
  --with-web-tools         Run scripts/core/install_web_tools.sh
  --with-pwn-re-tools      Run scripts/mcp/install_pwn_re_tools.sh
  --with-opencode-plugin   Install .opencode plugin deps via bun or npm

Examples:
  ./scripts/ops/setup_env.sh
  ./scripts/ops/setup_env.sh --with-web-tools
  ./scripts/ops/setup_env.sh --with-pwn-re-tools --with-opencode-plugin
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --no-venv)
      VENV_DIR=""
      shift
      ;;
    --no-env-copy)
      COPY_ENV=0
      shift
      ;;
    --with-web-tools)
      WITH_WEB_TOOLS=1
      shift
      ;;
    --with-pwn-re-tools)
      WITH_PWN_RE_TOOLS=1
      shift
      ;;
    --with-opencode-plugin)
      WITH_OPENCODE_PLUGIN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[setup] unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

echo "== open-ctf-agent setup =="
echo "- root: $ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[FAIL] python3 not found" >&2
  exit 1
fi

PIP_CMD=(python3 -m pip)
if [[ -n "$VENV_DIR" ]]; then
  echo "[1/5] creating virtualenv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  PIP_CMD=(python -m pip)
  "${PIP_CMD[@]}" install --upgrade pip
else
  echo "[1/5] skipping virtualenv"
fi

echo "[2/5] installing Python requirements"
"${PIP_CMD[@]}" install -r requirements.txt

echo "[3/5] preparing local config"
if [[ "$COPY_ENV" == "1" ]]; then
  if [[ ! -f .env.local ]]; then
    cp .env.example .env.local
    echo "[ OK ] created .env.local from .env.example"
  else
    echo "[ .. ] keeping existing .env.local"
  fi
else
  echo "[ .. ] env copy skipped"
fi

echo "[4/5] creating local runtime directories"
mkdir -p \
  events \
  workspace/active \
  workspace/archive \
  workspace/study \
  runtime \
  logs

echo "[5/5] optional extras"
if [[ "$WITH_WEB_TOOLS" == "1" ]]; then
  bash scripts/core/install_web_tools.sh
else
  echo "[ .. ] web tools skipped"
fi

if [[ "$WITH_PWN_RE_TOOLS" == "1" ]]; then
  bash scripts/mcp/install_pwn_re_tools.sh
else
  echo "[ .. ] pwn/re tools skipped"
fi

if [[ "$WITH_OPENCODE_PLUGIN" == "1" ]]; then
  if command -v bun >/dev/null 2>&1; then
    (cd .opencode && bun install)
  elif command -v npm >/dev/null 2>&1; then
    (cd .opencode && npm install)
  else
    echo "[warn] bun/npm not found, skip .opencode plugin install"
  fi
else
  echo "[ .. ] opencode plugin install skipped"
fi

cat <<'NEXT'

Next steps:
  1. Edit .env.local and fill your model API settings.
  2. Optionally adjust .opencode/opencode.json for your preferred provider/model IDs.
  3. Run ./scripts/ops/ctf_preflight.sh --require-auth 0 --check-mcp 0
NEXT
