#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path


def run_cmd(cmd: str, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, out


def extract_flag(text: str, pattern: str) -> str:
    if not pattern or pattern == "FLAG_REGEX_HERE":
        return ""
    m = re.search(pattern, text)
    return m.group(0) if m else ""


def parse_success_rate(text: str) -> tuple[int, int]:
    m = re.search(r"success_rate\s*=\s*(\d+)\s*/\s*(\d+)", text)
    if not m:
        return -1, -1
    return int(m.group(1)), int(m.group(2))


def parse_json_blob(text: str) -> dict:
    # best-effort JSON extraction from output
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return {}
    try:
        return json.loads(text[s : e + 1])
    except Exception:
        return {}


def has_misc_provenance(output: str) -> bool:
    blob = parse_json_blob(output)
    if not isinstance(blob, dict):
        return False
    if "provenance" in blob and blob.get("provenance"):
        return True
    if "provenance_head" in blob and blob.get("provenance_head"):
        return True
    if "artifacts" in blob and blob.get("artifacts"):
        return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Admission gate for stable vs incubating memory tier.")
    p.add_argument("--project", required=True)
    p.add_argument("--category", default="", choices=["", "pwn", "rev", "crypto", "misc", "forensics", "osint", "malware"])
    p.add_argument("--flag-pattern", required=True)
    p.add_argument("--solve-cmd", default="python3 solve.py")
    p.add_argument("--verify-cmd", default="python3 verify.py")
    p.add_argument("--replay-runs", type=int, default=3)
    p.add_argument("--min-success-rate", type=float, default=1.0)
    p.add_argument("--require-provenance", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    project = Path(args.project).resolve()
    if not project.exists():
        raise SystemExit(f"project not found: {project}")

    category = args.category
    if not category:
        meta = project / "challenge.json"
        if meta.exists():
            try:
                category = str(json.loads(meta.read_text(encoding="utf-8", errors="ignore")).get("category", "")).lower()
            except Exception:
                category = ""

    # 1) Replay consistency
    replay_flags = []
    replay_ok = 0
    for _ in range(args.replay_runs):
        rc, out = run_cmd(args.solve_cmd, project)
        flag = extract_flag(out, args.flag_pattern)
        replay_flags.append(flag)
        if rc == 0 and flag:
            replay_ok += 1

    replay_rate = replay_ok / max(1, args.replay_runs)
    consistent = len({f for f in replay_flags if f}) == 1 and replay_ok > 0

    # 2) Verify stage
    verify_cmd = f"{args.verify_cmd} --pattern {shlex.quote(args.flag_pattern)}"
    vrc, vout = run_cmd(verify_cmd, project)
    vx, vy = parse_success_rate(vout)
    verify_rate = (vx / vy) if vx >= 0 and vy > 0 else (1.0 if vrc == 0 else 0.0)

    # 3) Provenance gate (misc by default when requested)
    provenance_ok = True
    if args.require_provenance or category in {"misc", "forensics", "osint", "malware"}:
        rc, out = run_cmd(args.solve_cmd, project)
        provenance_ok = has_misc_provenance(out)

    stable = (
        replay_rate >= args.min_success_rate
        and verify_rate >= args.min_success_rate
        and consistent
        and provenance_ok
    )

    decision = {
        "project": str(project),
        "category": category or "unknown",
        "stable": stable,
        "tier": "stable" if stable else "incubating",
        "replay_rate": round(replay_rate, 3),
        "verify_rate": round(verify_rate, 3),
        "consistent_flag": consistent,
        "provenance_ok": provenance_ok,
        "replay_flags": replay_flags,
    }

    if args.json:
        print(json.dumps(decision, ensure_ascii=False, indent=2))
    else:
        print(f"tier={decision['tier']} replay_rate={decision['replay_rate']} verify_rate={decision['verify_rate']} consistent={decision['consistent_flag']} provenance={decision['provenance_ok']}")
        if replay_flags:
            print(f"flags={replay_flags}")

    raise SystemExit(0 if stable else 2)


if __name__ == "__main__":
    main()
