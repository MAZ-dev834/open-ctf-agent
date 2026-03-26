#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:
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


def norm_items(items: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def append_block(path: Path, lines: list[str]) -> None:
    content = "\n".join(lines) + "\n"
    if path.exists() and path.read_text(encoding="utf-8", errors="ignore").strip():
        content = "\n" + content
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


def main() -> int:
    p = argparse.ArgumentParser(description="Record evidence-driven steps and tried paths under project logs.")
    p.add_argument("--project", required=True, help="Project path or name under workspace/active")
    p.add_argument(
        "--mode",
        default="step",
        choices=["step", "attempt", "closure", "pivot"],
        help="Record type",
    )
    p.add_argument("--stage", default="", help="Stage label, e.g. 0/1/2 or recon/model/closure")
    p.add_argument("--status", default="", help="Status label, e.g. ok/blocked/failed/partial")
    p.add_argument("--hypothesis", action="append", default=[], help="Current hypothesis (repeatable)")
    p.add_argument("--evidence", action="append", default=[], help="Concrete evidence (repeatable)")
    p.add_argument("--action", action="append", default=[], help="Action taken (repeatable)")
    p.add_argument("--result", action="append", default=[], help="Observed result (repeatable)")
    p.add_argument("--tried-path", action="append", default=[], help="Path/model/payload already tried (repeatable)")
    p.add_argument("--rejected", action="append", default=[], help="Rejected path and reason (repeatable)")
    p.add_argument("--next", dest="next_steps", action="append", default=[], help="Next step (repeatable)")
    p.add_argument("--note", action="append", default=[], help="Extra notes (repeatable)")
    p.add_argument("--artifact", action="append", default=[], help="High-value artifact touched/validated (repeatable)")
    p.add_argument("--counterevidence", action="append", default=[], help="Concrete evidence against the active path (repeatable)")
    p.add_argument("--pivot-trigger", action="append", default=[], help="What should force a pivot (repeatable)")
    p.add_argument("--transport", default="", help="Interaction transport or protocol, e.g. tcp/ws/http/ttyd")
    p.add_argument("--confidence", type=float, default=-1.0, help="Confidence for the active branch, 0..1")
    args = p.parse_args()

    project_dir = resolve_project_path(args.project)
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = log_dir / "evidence.md"
    tried_path = log_dir / "tried_paths.md"
    attempts_path = log_dir / "attempts.jsonl"

    ts = dt.datetime.now().isoformat(timespec="seconds")
    header = f"## {ts} [mode={args.mode}]"
    if args.stage:
        header += f" [stage={args.stage}]"
    if args.status:
        header += f" [status={args.status}]"

    lines = [header]
    for label, values in [
        ("hypothesis", norm_items(args.hypothesis)),
        ("evidence", norm_items(args.evidence)),
        ("action", norm_items(args.action)),
        ("result", norm_items(args.result)),
        ("artifact", norm_items(args.artifact)),
        ("counterevidence", norm_items(args.counterevidence)),
        ("pivot_trigger", norm_items(args.pivot_trigger)),
        ("next", norm_items(args.next_steps)),
        ("note", norm_items(args.note)),
    ]:
        for value in values:
            lines.append(f"- {label}: {value}")
    if args.transport.strip():
        lines.append(f"- transport: {args.transport.strip()}")
    if args.confidence >= 0:
        lines.append(f"- confidence: {args.confidence:.2f}")
    if len(lines) == 1:
        lines.append("- note: evidence step")
    append_block(evidence_path, lines)

    tried_lines = [header]
    for value in norm_items(args.tried_path):
        tried_lines.append(f"- tried_path: {value}")
    for value in norm_items(args.rejected):
        tried_lines.append(f"- rejected: {value}")
    if len(tried_lines) > 1:
        append_block(tried_path, tried_lines)

    attempt = {
        "timestamp": ts,
        "mode": args.mode,
        "stage": args.stage.strip(),
        "status": args.status.strip(),
        "hypothesis": norm_items(args.hypothesis),
        "evidence": norm_items(args.evidence),
        "action": norm_items(args.action),
        "result": norm_items(args.result),
        "artifact": norm_items(args.artifact),
        "counterevidence": norm_items(args.counterevidence),
        "pivot_trigger": norm_items(args.pivot_trigger),
        "tried_path": norm_items(args.tried_path),
        "rejected": norm_items(args.rejected),
        "next": norm_items(args.next_steps),
        "note": norm_items(args.note),
        "transport": args.transport.strip(),
        "confidence": (round(float(args.confidence), 2) if args.confidence >= 0 else None),
    }
    with attempts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(attempt, ensure_ascii=False) + "\n")

    print(f"[+] evidence: {evidence_path}")
    if len(tried_lines) > 1:
        print(f"[+] tried_paths: {tried_path}")
    print(f"[+] attempts: {attempts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
