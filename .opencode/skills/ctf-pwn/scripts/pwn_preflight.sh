#!/usr/bin/env bash
set -euo pipefail

REQUIRE_MCP=0
if [[ "${1:-}" == "--require-mcp" ]]; then
  REQUIRE_MCP=1
fi

echo "[+] Pwn preflight"

required_cmds=(file checksec strings readelf objdump nm gdb python3)
missing=0
for c in "${required_cmds[@]}"; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "  [ok] $c"
  else
    echo "  [missing] $c"
    missing=1
  fi
done

has_pwntools=0
if python3 - <<'PY' >/dev/null 2>&1
import pwn
import pwnlib
print(getattr(pwnlib, "__version__", "unknown"))
PY
then
  echo "  [ok] pwntools"
  has_pwntools=1
else
  if [[ "$REQUIRE_MCP" -eq 1 ]]; then
    echo "  [warn] pwntools missing locally; expecting MCP pwntools instead"
  else
    echo "  [missing] pwntools (pip install pwntools)"
    missing=1
  fi
fi

plugin="none"
if [[ -f "$HOME/.gdbinit" ]]; then
  if rg -q "pwndbg" "$HOME/.gdbinit" 2>/dev/null; then
    plugin="pwndbg"
  elif rg -q "gef" "$HOME/.gdbinit" 2>/dev/null; then
    plugin="gef"
  elif rg -q "peda" "$HOME/.gdbinit" 2>/dev/null; then
    plugin="peda"
  fi
fi

echo "  [info] gdb plugin: $plugin"

if [[ "$REQUIRE_MCP" -eq 1 ]]; then
  if [[ -x ./scripts/mcp/mcp_healthcheck.sh ]]; then
    ./scripts/mcp/mcp_healthcheck.sh pwn-re
  else
    echo "[-] scripts/mcp/mcp_healthcheck.sh not found"
    exit 1
  fi
else
  if [[ -x ./scripts/mcp/mcp_healthcheck.sh ]]; then
    ./scripts/mcp/mcp_healthcheck.sh || true
  fi
fi

if [[ "$missing" -ne 0 ]]; then
  echo "[-] Preflight failed"
  exit 1
fi

echo "[+] Preflight passed"
