#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_SCRIPT="$ROOT/.opencode/skills/ctf-web/scripts/web_recon.sh"

if [[ -x "$SKILL_SCRIPT" ]]; then
  exec "$SKILL_SCRIPT" "$@"
fi

echo "[-] Missing skill script: $SKILL_SCRIPT" >&2
exit 1
