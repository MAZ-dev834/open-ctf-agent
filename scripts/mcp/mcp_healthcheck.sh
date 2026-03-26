#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'USAGE'
Usage:
  mcp_healthcheck.sh [default|pwn-re]

Check whether OpenCode MCP servers are configured and enabled.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

PROFILE="${1:-default}"
REQUIRED_PWN_RE=("ctf-radare2" "ctf-ghidra")
OPTIONAL_PWN_RE=("ctf-gdb")

echo "[+] Checking OpenCode MCP registration"
list_output="$(opencode mcp list)"
echo "$list_output"

if echo "$list_output" | grep -q "No MCP servers configured"; then
  if [[ "$PROFILE" == "pwn-re" ]]; then
    echo "[-] pwn-re profile requires MCP servers to be configured."
    exit 1
  fi
  echo "[+] No MCP configured (expected for current setup)"
  exit 0
fi

if echo "$list_output" | grep -q "failed"; then
  echo "[-] One or more MCP servers failed to start."
  exit 1
fi

if [[ "$PROFILE" == "pwn-re" ]]; then
  for name in "${REQUIRED_PWN_RE[@]}"; do
    if ! echo "$list_output" | grep -q "$name"; then
      echo "[-] missing MCP server in config: $name"
      exit 1
    fi
    if echo "$list_output" | grep -q "$name .*disabled"; then
      echo "[-] required MCP server is disabled: $name"
      echo "    run ./scripts/mcp/mcp_toggle_pwn_re.sh enable"
      exit 1
    fi
  done

  for name in "${OPTIONAL_PWN_RE[@]}"; do
    if ! echo "$list_output" | grep -q "$name"; then
      echo "[!] optional MCP server not configured: $name"
      continue
    fi
    if echo "$list_output" | grep -q "$name .*disabled"; then
      echo "[!] optional MCP server is disabled: $name"
    fi
  done

  echo "[+] pwn-re MCP profile is healthy"
  exit 0
fi

echo "[+] MCP health check passed"
