#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:
    # Fallback for direct execution
    from ctf_paths import resolve_work_root  # type: ignore


def resolve_project_path(project: str) -> Path:
    raw = Path(project).expanduser()
    if raw.is_dir():
        return raw.resolve()
    base = resolve_work_root(None)
    cand = base / project
    if cand.exists() and cand.is_dir():
        return cand.resolve()
    raise SystemExit(f"project not found: {project}")


def _norm_items(items: list[str] | None) -> list[str]:
    if not items:
        return []
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Write a checkpoint entry to logs/checkpoint.md")
    p.add_argument("--project", required=True, help="Project path or name under workspace/active")
    p.add_argument("--stage", default="", help="Stage label, e.g., 0/1/2 or verify/primitive/chain")
    p.add_argument("--status", default="", help="Status label, e.g., pivot/blocked/ok")
    p.add_argument("--hypothesis", action="append", default=[], help="Hypothesis (repeatable)")
    p.add_argument("--evidence", action="append", default=[], help="Evidence (repeatable)")
    p.add_argument("--eliminated", action="append", default=[], help="Eliminated hypotheses (repeatable)")
    p.add_argument("--next", dest="next_steps", action="append", default=[], help="Next steps (repeatable)")
    p.add_argument("--search-space", default="", help="Remaining search space")
    p.add_argument("--note", action="append", default=[], help="Notes (repeatable)")
    args = p.parse_args()

    project_dir = resolve_project_path(args.project)
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "checkpoint.md"

    ts = dt.datetime.now().isoformat(timespec="seconds")
    header = f"## {ts}"
    if args.stage:
        header += f" [stage={args.stage}]"
    if args.status:
        header += f" [status={args.status}]"

    lines = [header]

    def add_items(label: str, items: list[str]) -> None:
        for item in items:
            lines.append(f"- {label}: {item}")

    add_items("hypothesis", _norm_items(args.hypothesis))
    add_items("evidence", _norm_items(args.evidence))
    add_items("eliminated", _norm_items(args.eliminated))
    add_items("next", _norm_items(args.next_steps))

    if args.search_space:
        lines.append(f"- search_space: {args.search_space.strip()}")

    add_items("note", _norm_items(args.note))

    if len(lines) == 1:
        lines.append("- note: checkpoint")

    content = "\n".join(lines) + "\n"
    if path.exists() and path.read_text(encoding="utf-8", errors="ignore").strip():
        content = "\n" + content
    with path.open("a", encoding="utf-8") as f:
        f.write(content)

    print(f"[+] checkpoint: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
