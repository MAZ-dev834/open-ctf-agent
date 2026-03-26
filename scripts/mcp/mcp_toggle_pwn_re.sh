#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 enable|disable"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

MODE="$1"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$ROOT_DIR/.opencode/opencode.json"
TMP="$(mktemp)"

case "$MODE" in
  enable)
    VALUE=true
    ;;
  disable)
    VALUE=false
    ;;
  *)
    usage
    exit 1
    ;;
esac

jq \
  --argjson value "$VALUE" \
  '.mcp["ctf-radare2"].enabled = $value
   | .mcp["ctf-ghidra"].enabled = $value
   | .mcp["ctf-gdb"].enabled = $value' \
  "$CONFIG" > "$TMP"

mv "$TMP" "$CONFIG"

echo "[+] Set pwn/re MCP servers to enabled=$VALUE"
