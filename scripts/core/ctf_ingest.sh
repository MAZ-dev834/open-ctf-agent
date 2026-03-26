#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  ctf_ingest.sh --title <title> --flag-format <regex> [options]

Options:
  --category <name>         Challenge category (default: unknown)
  --description <text>      Challenge description or notes
  --target <url|host:port>  Target endpoint
  --attachment <path|url>   Attachment path or URL (repeatable)
  --work-root <dir>         Work root (default: ./workspace/active)
USAGE
}

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

slugify() {
  local input="$1"
  printf '%s' "$input" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/--+/-/g'
}

extract_if_archive() {
  local file_path="$1"
  local extract_root="$2"
  local base
  base="$(basename "$file_path")"

  case "$base" in
    *.zip)
      if command -v unzip >/dev/null 2>&1; then
        mkdir -p "$extract_root"
        unzip -o "$file_path" -d "$extract_root" >/dev/null || true
      fi
      ;;
    *.tar.gz|*.tgz)
      mkdir -p "$extract_root"
      tar -xzf "$file_path" -C "$extract_root" >/dev/null 2>&1 || true
      ;;
    *.tar.bz2|*.tbz2)
      mkdir -p "$extract_root"
      tar -xjf "$file_path" -C "$extract_root" >/dev/null 2>&1 || true
      ;;
    *.tar)
      mkdir -p "$extract_root"
      tar -xf "$file_path" -C "$extract_root" >/dev/null 2>&1 || true
      ;;
    *.7z)
      if command -v 7z >/dev/null 2>&1; then
        mkdir -p "$extract_root"
        7z x -y "$file_path" "-o$extract_root" >/dev/null || true
      fi
      ;;
  esac
}

TITLE=""
CATEGORY="unknown"
DESCRIPTION=""
FLAG_FORMAT=""
TARGET=""
WORK_ROOT="./workspace/active"
ATTACHMENTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)
      TITLE="$2"
      shift 2
      ;;
    --category)
      CATEGORY="$2"
      shift 2
      ;;
    --description)
      DESCRIPTION="$2"
      shift 2
      ;;
    --flag-format)
      FLAG_FORMAT="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --attachment)
      ATTACHMENTS+=("$2")
      shift 2
      ;;
    --work-root)
      WORK_ROOT="$2"
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

if [[ -z "$TITLE" || -z "$FLAG_FORMAT" ]]; then
  echo "--title and --flag-format are required" >&2
  usage
  exit 1
fi

# Backward-compatible fallback when old layout still exists.
if [[ "$WORK_ROOT" == "./workspace/active" && ! -d "$WORK_ROOT" && -d "./ctf-work" ]]; then
  WORK_ROOT="./ctf-work"
fi

slug="$(slugify "$TITLE")"
if [[ -z "$slug" ]]; then
  slug="challenge"
fi

work_dir="$WORK_ROOT/$slug"
if [[ -e "$work_dir" ]]; then
  ts="$(date +%Y%m%d_%H%M%S)"
  work_dir="${work_dir}_${ts}"
fi
attachments_dir="$work_dir/attachments"
extract_dir="$attachments_dir/extracted"
logs_dir="$work_dir/logs"
artifacts_dir="$work_dir/artifacts"

mkdir -p "$attachments_dir" "$extract_dir" "$logs_dir" "$artifacts_dir"

for src in "${ATTACHMENTS[@]}"; do
  if [[ "$src" =~ ^https?:// ]]; then
    file_name="$(basename "${src%%\?*}")"
    if [[ -z "$file_name" || "$file_name" == "" || "$file_name" == "/" ]]; then
      file_name="downloaded.bin"
    fi
    dst="$attachments_dir/$file_name"
    curl -fsSL "$src" -o "$dst"
    extract_if_archive "$dst" "$extract_dir/${file_name%.*}"
  else
    if [[ ! -e "$src" ]]; then
      echo "Attachment not found: $src" >&2
      exit 1
    fi
    file_name="$(basename "$src")"
    dst="$attachments_dir/$file_name"
    cp -a "$src" "$dst"
    extract_if_archive "$dst" "$extract_dir/${file_name%.*}"
  fi
done

created_at="$(date -Iseconds)"

cat > "$work_dir/challenge.json" <<JSON
{
  "title": "$(json_escape "$TITLE")",
  "slug": "$(json_escape "$slug")",
  "category": "$(json_escape "$CATEGORY")",
  "description": "$(json_escape "$DESCRIPTION")",
  "flag_format": "$(json_escape "$FLAG_FORMAT")",
  "target": "$(json_escape "$TARGET")",
  "created_at": "$(json_escape "$created_at")"
}
JSON

cat > "$work_dir/runbook.md" <<RUNBOOK
# Challenge Runbook

- Title: $TITLE
- Category: $CATEGORY
- Description: $DESCRIPTION
- Flag format regex: $FLAG_FORMAT
- Target: $TARGET
- Created at: $created_at

## Paths
- Metadata: ./challenge.json
- Attachments: ./attachments
- Extracted: ./attachments/extracted
- Logs: ./logs
- Artifacts: ./artifacts

<!-- RUNBOOK-NOTES:START -->
## Auto Notes

- (none yet)
<!-- RUNBOOK-NOTES:END -->

<!-- EVIDENCE-STATUS:START -->
## Evidence Status

- Current hypothesis: (none yet)
- Locked evidence: (none yet)
- Rejected paths: see `./logs/tried_paths.md`
- Detailed step log: see `./logs/evidence.md`
- Attempt ledger: see `./logs/attempts.jsonl`
<!-- EVIDENCE-STATUS:END -->

RUNBOOK

echo "[+] Challenge workspace ready: $work_dir"
echo "[+] Metadata: $work_dir/challenge.json"
echo "[+] Runbook: $work_dir/runbook.md"

# Auto lane selector to reduce overhead on easy tasks.
lane_script="$ROOT_DIR/scripts/core/ctf_lane_select.py"
if [[ -f "$lane_script" ]]; then
  lane_json_file="$work_dir/.lane_reco.json"
  python3 "$lane_script" --project "$work_dir" --json > "$lane_json_file" || true
  if [[ -s "$lane_json_file" ]]; then
    python3 - "$work_dir/runbook.md" "$lane_json_file" <<'PY'
import json
import sys
from pathlib import Path

runbook = Path(sys.argv[1])
rec_path = Path(sys.argv[2])
text = runbook.read_text(encoding="utf-8", errors="ignore")
data = json.loads(rec_path.read_text(encoding="utf-8"))

start = "<!-- LANE-RECOMMEND:START -->"
end = "<!-- LANE-RECOMMEND:END -->"

lines = []
lines.append("## Lane Recommendation")
lines.append("")
lines.append(f"- Lane: `{data.get('lane', 'unknown')}`")
lines.append(f"- File count: {data.get('file_count', 0)}")
lines.append(f"- Total size: {data.get('total_size', 0)}")
lines.append(f"- Risk hits: {data.get('risk_hits', 0)}")
lines.append(f"- Heavy hits: {data.get('heavy_hits', 0)}")
reasons = data.get("reasons", []) or []
if reasons:
    lines.append("- Reasons:")
    for item in reasons:
        lines.append(f"  - {item}")

payload = "\n".join(lines)

if start in text and end in text and text.index(start) < text.index(end):
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    out = f"{head}{start}\n{payload}\n{end}{tail}"
else:
    if not text.endswith("\n"):
        text += "\n"
    out = f"{text}\n{start}\n{payload}\n{end}\n"

runbook.write_text(out, encoding="utf-8")
PY
  fi
  rm -f "$lane_json_file"
fi

# Auto-suggest high-confidence memory hits for faster first iteration.
recommend_script="$ROOT_DIR/scripts/learn/ctf_memory_recommend.py"
failure_script="$ROOT_DIR/scripts/learn/ctf_failure_check.py"
if [[ -f "$recommend_script" ]]; then
  seed_text_file="$work_dir/.memory_seed.txt"
  rec_json_file="$work_dir/.memory_reco.json"
  {
    echo "$TITLE"
    if [[ -n "$DESCRIPTION" ]]; then
      echo "$DESCRIPTION"
    fi
  } > "$seed_text_file"
  echo "[+] Memory recommendations:"
  python3 "$recommend_script" --text-file "$seed_text_file" --limit 5 || true
  python3 "$recommend_script" --text-file "$seed_text_file" --limit 5 --json > "$rec_json_file" || true
  if [[ -s "$rec_json_file" ]]; then
    python3 - "$work_dir/runbook.md" "$rec_json_file" <<'PY'
import json
import sys
from pathlib import Path

runbook = Path(sys.argv[1])
rec_path = Path(sys.argv[2])
text = runbook.read_text(encoding="utf-8", errors="ignore")
data = json.loads(rec_path.read_text(encoding="utf-8"))
recs = data.get("recommendations", [])
actions = data.get("next_actions", []) or []
keywords = data.get("search_keywords", []) or []

start = "<!-- RECOMMENDED-PATTERNS:START -->"
end = "<!-- RECOMMENDED-PATTERNS:END -->"
lines = []
lines.append("## Recommended Patterns")
lines.append("")
lines.append(f"- Inferred category: `{data.get('inferred_category', 'unknown')}`")
lines.append(f"- Selected category: `{data.get('selected_category', 'unknown')}`")
if actions:
    lines.append("- Next actions:")
    for act in actions[:4]:
        lines.append(f"  - {act}")
if keywords:
    lines.append("- Search keywords:")
    for kw in keywords[:6]:
        lines.append(f"  - {kw}")
if not recs:
    lines.append("- No high-confidence recommendations yet.")
else:
    lines.append("- Top memories:")
    for rec in recs:
        lines.append(
            f"  - `{rec.get('project')}` ({rec.get('category')}, conf={rec.get('confidence')}, score={rec.get('score')}, penalty={rec.get('risk_penalty', 0)})"
        )
        for p in (rec.get("patterns") or [])[:2]:
            lines.append(f"    - {p}")

payload = "\n".join(lines)

if start in text and end in text and text.index(start) < text.index(end):
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    out = f"{head}{start}\n{payload}\n{end}{tail}"
else:
    if not text.endswith("\n"):
        text += "\n"
    out = f"{text}\n{start}\n{payload}\n{end}\n"

runbook.write_text(out, encoding="utf-8")
PY
  fi
  rm -f "$seed_text_file"
  rm -f "$rec_json_file"
fi

if [[ -f "$failure_script" ]]; then
  fail_seed_file="$work_dir/.failure_seed.txt"
  fail_json_file="$work_dir/.failure_watchlist.json"
  {
    echo "$TITLE"
    if [[ -n "$DESCRIPTION" ]]; then
      echo "$DESCRIPTION"
    fi
  } > "$fail_seed_file"
  echo "[+] Failure watchlist:"
  python3 "$failure_script" --category "$CATEGORY" --text-file "$fail_seed_file" --limit 5 || true
  python3 "$failure_script" --category "$CATEGORY" --text-file "$fail_seed_file" --limit 5 --json > "$fail_json_file" || true
  if [[ -s "$fail_json_file" ]]; then
    python3 - "$work_dir/runbook.md" "$fail_json_file" <<'PY'
import json
import sys
from pathlib import Path

runbook = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
text = runbook.read_text(encoding="utf-8", errors="ignore")

start = "<!-- FAILURE-WATCHLIST:START -->"
end = "<!-- FAILURE-WATCHLIST:END -->"

lines = []
lines.append("## Failure Watchlist")
lines.append("")
watch = payload.get("watchlist", [])
if not watch:
    lines.append("- No recent related failure patterns.")
else:
    lines.append("- Similar failure-prone paths:")
    for item in watch:
        lines.append(
            f"  - `{item.get('project')}` ({item.get('category')}, {item.get('status')}, tier={item.get('memory_tier')}, score={item.get('score')})"
        )
        for p in (item.get("patterns") or [])[:2]:
            lines.append(f"    - {p}")

signals = payload.get("common_failure_signals", [])
if signals:
    lines.append("- Common failure signals:")
    for item in signals[:5]:
        lines.append(f"  - ({item.get('count')}x) {item.get('signal')}")

block = "\n".join(lines)

if start in text and end in text and text.index(start) < text.index(end):
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    out = f"{head}{start}\n{block}\n{end}{tail}"
else:
    if not text.endswith("\n"):
        text += "\n"
    out = f"{text}\n{start}\n{block}\n{end}\n"

runbook.write_text(out, encoding="utf-8")
PY
  fi
  rm -f "$fail_seed_file"
  rm -f "$fail_json_file"
fi
