#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_index(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def filt(rows: list[dict], args) -> list[dict]:
    out = []
    for r in rows:
        if args.project and args.project.lower() not in str(r.get("project_name", "")).lower():
            continue
        if args.competition and args.competition.lower() not in str(r.get("competition", "")).lower():
            continue
        if args.id is not None and str(r.get("challenge_id", "")) != str(args.id):
            continue
        if args.category and args.category.lower() not in str(r.get("category", "")).lower():
            continue
        if args.status == "solved" and not bool(r.get("has_flag")):
            continue
        if args.status == "unsolved" and bool(r.get("has_flag")):
            continue
        if args.low_conf_only and float(r.get("confidence", 0.0) or 0.0) >= args.low_conf_threshold:
            continue
        out.append(r)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Query workspace project index.")
    p.add_argument("--index", default="./shared/ctf-index/projects_index.jsonl")
    p.add_argument("--project", default="")
    p.add_argument("--competition", default="")
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--category", default="")
    p.add_argument("--status", choices=["all", "solved", "unsolved"], default="all")
    p.add_argument("--low-conf-only", action="store_true")
    p.add_argument("--low-conf-threshold", type=float, default=0.8)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    rows = load_index(Path(args.index).resolve())
    out = filt(rows, args)[: args.limit]

    if args.json:
        print(json.dumps({"count": len(out), "rows": out}, ensure_ascii=False))
        return 0

    print(f"count: {len(out)}")
    for r in out:
        print(
            f"- {r.get('project_name')} | comp={r.get('competition') or '-'} | "
            f"id={r.get('challenge_id') or '-'} | name={r.get('challenge_name') or '-'} | "
            f"cat={r.get('category') or '-'} | conf={r.get('confidence', 0)} | solved={bool(r.get('has_flag'))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
