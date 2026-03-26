#!/usr/bin/env bash
set -euo pipefail

required_cmds=(curl awk sed grep)
optional_cmds=(ffuf jq python3 nuclei nmap httpie gau waybackurls paramspider linkfinder feroxbuster wfuzz)

missing=0

echo "[+] Web CTF preflight"
echo "[+] Checking required commands"
for cmd in "${required_cmds[@]}"; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "  [ok] %s\n" "$cmd"
  else
    printf "  [missing] %s\n" "$cmd"
    missing=1
  fi
done

echo "[+] Checking optional commands"
for cmd in "${optional_cmds[@]}"; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "  [ok] %s\n" "$cmd"
  else
    printf "  [skip] %s\n" "$cmd"
  fi
done

if command -v docker >/dev/null 2>&1; then
  echo "  [ok] docker"
else
  echo "  [skip] docker"
fi

if [[ "$missing" -ne 0 ]]; then
  echo "[-] Required tools missing. Install required commands before solving."
  exit 1
fi

echo "[+] Preflight passed"
