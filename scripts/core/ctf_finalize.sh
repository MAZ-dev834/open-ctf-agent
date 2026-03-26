#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ctf_finalize.sh --project <workspace/project-dir>
  ctf_finalize.sh --all [--work-root <dir>]

Behavior:
- Finalize only successful projects (flag or flag.txt exists)
- Keep top-level items only: attachments/ solve.py writeup.md flag.txt
- Move any other top-level files/dirs into attachments/
USAGE
}

WORK_ROOT="./workspace/active"
PROJECT=""
MODE=""
ATTACH_DIR="attachments"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      MODE="project"
      PROJECT="$2"
      shift 2
      ;;
    --all)
      MODE="all"
      shift
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
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  usage
  exit 1
fi

# Backward-compatible fallback when old layout still exists.
if [[ "$WORK_ROOT" == "./workspace/active" && ! -d "$WORK_ROOT" && -d "./ctf-work" ]]; then
  WORK_ROOT="./ctf-work"
fi

finalize_one() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0

  if [[ ! -f "$dir/flag.txt" && ! -f "$dir/flag" ]]; then
    echo "[skip] $dir (no flag file yet)"
    return 0
  fi

  if [[ -f "$dir/flag" && ! -f "$dir/flag.txt" ]]; then
    mv "$dir/flag" "$dir/flag.txt"
  elif [[ -f "$dir/flag" && -f "$dir/flag.txt" ]]; then
    rm -f "$dir/flag"
  fi

  if [[ ! -f "$dir/solve.py" ]]; then
    if [[ -f "$dir/exploit.py" ]]; then
      mv "$dir/exploit.py" "$dir/solve.py"
    else
      cat > "$dir/solve.py" <<'PY'
#!/usr/bin/env python3
"""Solve script placeholder."""

# Fill with final exploit/solver logic.
PY
      chmod +x "$dir/solve.py"
    fi
  fi

  if [[ ! -f "$dir/writeup.md" ]]; then
    local title
    title="$(basename "$dir")"
    cat > "$dir/writeup.md" <<MD
# ${title} 题解

## 摘要
- 题型:
- 目标:
- Flag 格式:
- 结果:

## 分析
- 根因:
- 关键观察:
- 约束:

## 解题过程
1. 
2. 
3. 

## 试错与迭代
- 失败点与原因:
- 改动点:
- 经验:

## 复现
```bash
python3 solve.py
```

## 环境
- OS:
- 工具:
MD
  fi

  if [[ -d "$dir/题目附件" && ! -d "$dir/$ATTACH_DIR" ]]; then
    mv "$dir/题目附件" "$dir/$ATTACH_DIR"
  fi

  mkdir -p "$dir/$ATTACH_DIR"
  # Migrate legacy attachment dirs into the final attach dir.
  # When ATTACH_DIR is itself "attachments", avoid deleting it.
  if [[ "$ATTACH_DIR" != "attachments" && -d "$dir/attachments" ]]; then
    find "$dir/attachments" -mindepth 1 -maxdepth 1 -exec mv {} "$dir/$ATTACH_DIR/" \;
    rmdir "$dir/attachments" || true
  fi
  if [[ "$ATTACH_DIR" != "题目附件" && -d "$dir/题目附件" ]]; then
    find "$dir/题目附件" -mindepth 1 -maxdepth 1 -exec mv {} "$dir/$ATTACH_DIR/" \;
    rmdir "$dir/题目附件" || true
  fi

  # Move any non-standard top-level items into final attachment dir.
  while IFS= read -r item; do
    local base
    base="$(basename "$item")"
    case "$base" in
      "$ATTACH_DIR"|solve.py|writeup.md|flag.txt)
        ;;
      *)
        mv "$item" "$dir/$ATTACH_DIR/"
        ;;
    esac
  done < <(find "$dir" -mindepth 1 -maxdepth 1)

  echo "[ok] finalized $dir"
  find "$dir" -mindepth 1 -maxdepth 1 -printf '  - %f\n' | sort
}

if [[ "$MODE" == "project" ]]; then
  finalize_one "$PROJECT"
else
  [[ -d "$WORK_ROOT" ]] || { echo "Work root not found: $WORK_ROOT"; exit 1; }
  while IFS= read -r d; do
    finalize_one "$d"
  done < <(find "$WORK_ROOT" -mindepth 1 -maxdepth 1 -type d | sort)
fi
