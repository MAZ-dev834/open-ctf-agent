#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from ctf_meta import normalize_project_key
except Exception:  # pragma: no cover
    import sys

    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.learn.ctf_meta import normalize_project_key

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:  # pragma: no cover
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.core.ctf_paths import resolve_work_root

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def workspace_metrics(ctf_work: Path) -> dict:
    dirs = [d for d in ctf_work.iterdir() if d.is_dir()] if ctf_work.exists() else []
    keys = [normalize_project_key(d.name) for d in dirs]
    dup = sum(1 for c in Counter(keys).values() if c > 1)
    unsolved_dirs = [d for d in dirs if not ((d / "flag.txt").exists() or (d / "flag").exists())]
    unsolved_artifact_complete = 0
    for d in unsolved_dirs:
        required = [
            d / "writeup.md",
            d / "logs" / "evidence.md",
            d / "logs" / "tried_paths.md",
            d / "logs" / "checkpoint.md",
        ]
        if all(p.exists() for p in required):
            unsolved_artifact_complete += 1
    return {
        "projects_dirs_total": len(dirs),
        "projects_with_flag": sum(1 for d in dirs if (d / "flag.txt").exists()),
        "projects_with_solve": sum(1 for d in dirs if (d / "solve.py").exists()),
        "projects_with_runbook": sum(1 for d in dirs if (d / "runbook.md").exists()),
        "duplicate_project_keys": dup,
        "unsolved_projects_total": len(unsolved_dirs),
        "unsolved_artifact_complete": unsolved_artifact_complete,
        "unsolved_artifact_complete_pct": round(100.0 * unsolved_artifact_complete / max(1, len(unsolved_dirs)), 2),
    }


def memory_metrics(index_path: Path) -> dict:
    rows = load_jsonl(index_path)
    latest = {}
    for r in rows:
        key = str(r.get("project_key", "")).strip() or normalize_project_key(
            r.get("project", "")
        )
        if not key:
            continue
        prev = latest.get(key)
        if prev is None or str(r.get("timestamp", "")) >= str(prev.get("timestamp", "")):
            latest[key] = r
    latest_rows = list(latest.values())
    unknown_latest = sum(1 for r in latest_rows if r.get("category") == "unknown")
    return {
        "memory_records_total": len(rows),
        "memory_latest_records": len(latest_rows),
        "unknown_latest_count": unknown_latest,
        "unknown_latest_pct": round(
            100.0 * unknown_latest / max(1, len(latest_rows)), 2
        ),
    }


def submit_metrics(submissions_path: Path | None) -> dict:
    if submissions_path is None:
        return {
            "submissions_total": 0,
            "submissions_ratelimited": 0,
            "submit_ratelimit_pct": 0.0,
            "submissions_incorrect": 0,
        }
    rows = load_jsonl(submissions_path)
    rl = 0
    bad = 0
    for r in rows:
        data = (r.get("response") or {}).get("data", {}) if isinstance(r.get("response"), dict) else {}
        st = str(data.get("status", ""))
        if st == "ratelimited" or int(r.get("http_status") or 0) == 429:
            rl += 1
        if st == "incorrect":
            bad += 1
    total = len(rows)
    return {
        "submissions_total": total,
        "submissions_ratelimited": rl,
        "submit_ratelimit_pct": round(100.0 * rl / max(1, total), 2),
        "submissions_incorrect": bad,
    }


def has_flag_file(ch_dir: Path) -> bool:
    if (ch_dir / "flag.txt").exists() or (ch_dir / "flag").exists():
        return True
    for sub in ("workspace", "ctf-work"):
        base = ch_dir / sub
        if not base.exists():
            continue
        try:
            for p in base.rglob("flag.txt"):
                return True
        except Exception:
            continue
    return False


def event_challenge_stats(event_dir: Path) -> dict:
    status_path = event_dir / "status.json"
    if not status_path.exists():
        return {
            "event": event_dir.name,
            "challenges_total": 0,
            "challenges_solved": 0,
            "challenges_solved_pct": 0.0,
        }
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        status = {}
    if not isinstance(status, dict):
        status = {}
    challenge_dirs = []
    for _, v in status.items():
        if isinstance(v, dict) and v.get("challenge_dir"):
            challenge_dirs.append(Path(str(v.get("challenge_dir"))))
    total = len(challenge_dirs)
    solved = sum(1 for d in challenge_dirs if d.exists() and has_flag_file(d))
    return {
        "event": event_dir.name,
        "challenges_total": total,
        "challenges_solved": solved,
        "challenges_solved_pct": round(100.0 * solved / max(1, total), 2),
    }


def list_event_dirs(events_root: Path) -> list[Path]:
    if not events_root.exists():
        return []
    return sorted([p for p in events_root.iterdir() if (p / "status.json").exists()])


def event_submission_coverage(event_dir: Path | None, submissions_path: Path | None) -> dict:
    if event_dir is None or not (event_dir / "status.json").exists():
        return {
            "event_challenges_total": 0,
            "event_submission_coverage_missing": 0,
            "event_submission_coverage_missing_pct": 0.0,
        }
    try:
        status = json.loads((event_dir / "status.json").read_text(encoding="utf-8"))
    except Exception:
        status = {}
    if not isinstance(status, dict):
        status = {}
    challenge_ids = set()
    for k, v in status.items():
        if isinstance(v, dict) and v.get("id") is not None:
            challenge_ids.add(int(v.get("id")))
            continue
        try:
            challenge_ids.add(int(k))
        except Exception:
            pass
    submitted_ids = set()
    for row in load_jsonl(submissions_path) if submissions_path else []:
        cid = row.get("challenge_id")
        try:
            submitted_ids.add(int(cid))
        except Exception:
            continue
    total = len(challenge_ids)
    missing = len([x for x in challenge_ids if x not in submitted_ids])
    return {
        "event_challenges_total": total,
        "event_submission_coverage_missing": missing,
        "event_submission_coverage_missing_pct": round(100.0 * missing / max(1, total), 2),
    }


def resolve_submissions_path(submissions: str | None, event_dir: str | None) -> Path | None:
    if submissions:
        return Path(submissions).resolve()
    if event_dir:
        return (Path(event_dir) / "submissions.jsonl").resolve()
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Unified health report for workspace/memory/submission quality.")
    p.add_argument("--ctf-work", default="./workspace/active")
    p.add_argument("--memory-index", default="./shared/skill-memory/memory_index.jsonl")
    p.add_argument("--submissions", default=None)
    p.add_argument("--event-dir", default=None, help="Event directory containing submissions.jsonl")
    p.add_argument("--events-root", default="./events", help="Root directory containing event folders")
    p.add_argument("--per-event", action="store_true", help="Include per-event stats under events/")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    submissions_path = resolve_submissions_path(args.submissions, args.event_dir)
    event_dir = Path(args.event_dir).resolve() if args.event_dir else None
    ctf_work = resolve_work_root(args.ctf_work)
    report = {
        "workspace": workspace_metrics(ctf_work),
        "memory": memory_metrics(Path(args.memory_index).resolve()),
        "submit": submit_metrics(submissions_path),
        "event_submit": event_submission_coverage(event_dir, submissions_path),
    }
    if args.per_event:
        events_root = Path(args.events_root).resolve()
        per_event = []
        totals = {
            "events_total": 0,
            "challenges_total": 0,
            "challenges_solved": 0,
            "submissions_total": 0,
            "submissions_ratelimited": 0,
            "submissions_incorrect": 0,
            "submit_ratelimit_pct": 0.0,
        }
        for ev in list_event_dirs(events_root):
            ev_submit = submit_metrics(resolve_submissions_path(None, str(ev)))
            ev_cov = event_submission_coverage(ev, resolve_submissions_path(None, str(ev)))
            ev_ch = event_challenge_stats(ev)
            row = {
                **ev_ch,
                **{
                    "submissions_total": ev_submit["submissions_total"],
                    "submissions_ratelimited": ev_submit["submissions_ratelimited"],
                    "submissions_incorrect": ev_submit["submissions_incorrect"],
                    "submit_ratelimit_pct": ev_submit["submit_ratelimit_pct"],
                    "submission_coverage_missing": ev_cov["event_submission_coverage_missing"],
                    "submission_coverage_missing_pct": ev_cov["event_submission_coverage_missing_pct"],
                },
            }
            per_event.append(row)
            totals["events_total"] += 1
            totals["challenges_total"] += row["challenges_total"]
            totals["challenges_solved"] += row["challenges_solved"]
            totals["submissions_total"] += row["submissions_total"]
            totals["submissions_ratelimited"] += row["submissions_ratelimited"]
            totals["submissions_incorrect"] += row["submissions_incorrect"]
        totals["submit_ratelimit_pct"] = round(
            100.0 * totals["submissions_ratelimited"] / max(1, totals["submissions_total"]), 2
        )
        totals["challenges_solved_pct"] = round(
            100.0 * totals["challenges_solved"] / max(1, totals["challenges_total"]), 2
        )
        report["events_overview"] = totals
        report["events"] = per_event

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    print("== CTF Health Report ==")
    print("[workspace]")
    for k, v in report["workspace"].items():
        print(f"- {k}: {v}")
    print("[memory]")
    for k, v in report["memory"].items():
        print(f"- {k}: {v}")
    print("[submit]")
    for k, v in report["submit"].items():
        print(f"- {k}: {v}")
    print("[event_submit]")
    for k, v in report["event_submit"].items():
        print(f"- {k}: {v}")
    if args.per_event:
        print("[events_overview]")
        for k, v in report.get("events_overview", {}).items():
            print(f"- {k}: {v}")
        print("[events]")
        for row in report.get("events", []):
            print(
                f"- {row['event']}: total={row['challenges_total']} "
                f"solved={row['challenges_solved']} "
                f"solved_pct={row['challenges_solved_pct']} "
                f"submit_total={row['submissions_total']} "
                f"rl_pct={row['submit_ratelimit_pct']} "
                f"missing_submit_pct={row['submission_coverage_missing_pct']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
