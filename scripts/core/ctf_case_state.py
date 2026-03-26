#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.core.ctf_paths import resolve_work_root
    from scripts.core.ctf_artifact_index import build_artifact_index
except Exception:
    from scripts.core.ctf_paths import resolve_work_root  # type: ignore
    from scripts.core.ctf_artifact_index import build_artifact_index  # type: ignore


TS_RE = re.compile(r"^##\s+([0-9T:+-]{19,})")
HEADER_STAGE_RE = re.compile(r"\[stage=([^\]]+)\]")
HEADER_STATUS_RE = re.compile(r"\[status=([^\]]+)\]")
ITEM_RE = re.compile(r"^-\s+([a-zA-Z_]+):\s*(.+)$")


def resolve_project_path(project: str) -> Path:
    raw = Path(project).expanduser()
    if raw.is_dir():
        return raw.resolve()
    base = resolve_work_root(None)
    cand = base / project
    if cand.exists() and cand.is_dir():
        return cand.resolve()
    raise SystemExit(f"project not found: {project}")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _parse_iso(ts: str) -> int | None:
    try:
        return int(dt.datetime.fromisoformat(ts).timestamp())
    except Exception:
        return None


def classify_attempt_failure(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").strip().lower()
    text = " ".join(
        [
            " ".join(str(x) for x in (row.get("counterevidence") or [])),
            " ".join(str(x) for x in (row.get("rejected") or [])),
            " ".join(str(x) for x in (row.get("note") or [])),
            str(row.get("transport") or ""),
        ]
    ).lower()
    if status == "ok":
        return "ok"
    if "unknown command" in text or "repl" in text or "ttyd" in text or "websocket" in text:
        return "interface"
    if "no such file or directory" in text or "stale_context" in text or "canonical dir mismatch" in text:
        return "path"
    if "bad gateway" in text or "upstream" in text:
        return "remote"
    if "rate-limit" in text or "rate limited" in text or "ratelimited" in text:
        return "submit"
    if "incorrect" in text or "candidate quality" in text:
        return "candidate"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if status in {"failed", "pivot", "blocked"}:
        return status
    return "other"


def summarize_attempt_failures(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classes: list[str] = []
    consecutive = 0
    consecutive_class = ""
    for row in rows:
        cls = classify_attempt_failure(row)
        classes.append(cls)
    for cls in reversed(classes):
        if cls == "ok":
            break
        if not consecutive_class:
            consecutive_class = cls
            consecutive = 1
            continue
        if cls == consecutive_class:
            consecutive += 1
        else:
            break
    counts: dict[str, int] = {}
    for cls in classes:
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "classes": classes,
        "counts": counts,
        "recent_consecutive_class": consecutive_class,
        "recent_consecutive_count": consecutive,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = _read_text(path)
    if not text.strip():
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_markdown_log(path: Path) -> list[dict[str, Any]]:
    text = _read_text(path)
    if not text.strip():
        return []
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = TS_RE.match(line)
        if m:
            if current:
                entries.append(current)
            header = line.strip()
            current = {
                "header": header,
                "timestamp": _parse_iso(m.group(1)),
                "stage": (HEADER_STAGE_RE.search(header).group(1).strip() if HEADER_STAGE_RE.search(header) else ""),
                "status": (HEADER_STATUS_RE.search(header).group(1).strip() if HEADER_STATUS_RE.search(header) else ""),
                "items": {},
            }
            continue
        if not current:
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).strip().lower(), m.group(2).strip()
        current.setdefault("items", {}).setdefault(key, []).append(value)
    if current:
        entries.append(current)
    return entries


def parse_runbook(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"title": "", "category": "", "current_hypothesis": "", "locked_evidence": ""}
    text = _read_text(path)
    if not text:
        return out
    patterns = {
        "title": r"^-\s*Title:\s*(.+)$",
        "category": r"^-\s*Category:\s*(.+)$",
        "current_hypothesis": r"^-\s*Current hypothesis:\s*(.+)$",
        "locked_evidence": r"^-\s*Locked evidence:\s*(.+)$",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, flags=re.M)
        if m:
            out[key] = m.group(1).strip()
    return out


def load_runbook(project_dir: Path) -> dict[str, Any]:
    for rel in ("runbook.md", "attachments/runbook.md", "题目附件/runbook.md"):
        path = project_dir / rel
        if path.exists():
            return parse_runbook(path)
    return {"title": "", "category": "", "current_hypothesis": "", "locked_evidence": ""}


def _project_metadata(project_dir: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {"id": None, "name": "", "category": ""}
    for rel in ("challenge.json", "task.json", "attachments/challenge.json", "题目附件/challenge.json"):
        p = project_dir / rel
        if not p.exists():
            continue
        try:
            data = json.loads(_read_text(p))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if meta["id"] is None and data.get("id") is not None:
            meta["id"] = data.get("id")
        if not meta["name"]:
            meta["name"] = str(data.get("name") or data.get("title") or "").strip()
        if not meta["category"]:
            meta["category"] = str(data.get("category") or "").strip()
    rb = load_runbook(project_dir)
    if not meta["name"]:
        meta["name"] = rb.get("title", "")
    if not meta["category"]:
        meta["category"] = rb.get("category", "")
    return meta


def find_project_for_challenge(challenge: dict[str, Any], work_root: Path | None = None) -> Path | None:
    root = resolve_work_root(work_root)
    if not root.exists():
        return None
    target_id = str(challenge.get("id") or "").strip()
    target_name = str(challenge.get("name") or "").strip().lower()
    target_category = str(challenge.get("category") or "").strip().lower()
    scored: list[tuple[int, float, Path]] = []
    for d in root.iterdir():
        if not d.is_dir() or d.name == "_archive":
            continue
        meta = _project_metadata(d)
        score = 0.0
        if target_id and meta.get("id") is not None and str(meta.get("id")) == target_id:
            score += 8.0
        name = str(meta.get("name") or "").strip().lower()
        if target_name and name:
            if name == target_name:
                score += 6.0
            elif target_name in name or name in target_name:
                score += 3.0
        cat = str(meta.get("category") or "").strip().lower()
        if target_category and cat == target_category:
            score += 1.5
        if score <= 0:
            continue
        scored.append((int(d.stat().st_mtime), score, d))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return scored[0][2].resolve()


def _latest_ts(*values: int | None) -> int | None:
    vals = [v for v in values if isinstance(v, int)]
    return max(vals) if vals else None


def pick_execution_plan(category: str, action: str, current: dict[str, Any], router: dict[str, Any]) -> dict[str, Any]:
    cat = str(category or "").strip().lower()
    specialist = {
        "web": "ctf-web",
        "pwn": "ctf-pwn",
        "crypto": "ctf-crypto",
        "rev": "ctf-rev",
        "reverse": "ctf-rev",
        "forensics": "ctf-forensics",
        "osint": "ctf-osint",
        "malware": "ctf-malware",
    }.get(cat, "ctf-misc")
    role = "solver"
    agent = specialist
    opening = "Continue the highest-confidence branch in the current challenge and keep evidence updated."
    if action == "research":
        role = "researcher"
        agent = specialist if cat in {"osint", "crypto", "forensics", "malware", "misc"} else "ctf"
        opening = "Switch to evidence-gathering mode. Use external retrieval first, collect authoritative sources, and update the active hypothesis before deeper execution."
    elif action == "verify":
        role = "verifier"
        agent = specialist
        opening = "Enter verification mode. Do not broaden recon. Test the current candidate, replay the current path, and disprove weak hypotheses before any expansion."
    elif action == "pivot":
        role = "planner"
        agent = "ctf"
        opening = "Current branch is weak or stalled. Summarize evidence, rejected paths, and propose the next best branch before running new heavy actions."
    elif action == "solved":
        role = "verifier"
        agent = specialist
        opening = "A flag already exists. Verify reproducibility, confirm provenance, and only then finalize writeup or submission steps."
    elif router.get("should_search"):
        role = "researcher"
        agent = specialist if cat in {"osint", "crypto", "forensics", "malware", "misc"} else "ctf"
        opening = "The search router is ON. Start with external retrieval to strengthen evidence before broad local execution."
    stage = str((current or {}).get("stage") or "").strip()
    return {
        "role": role,
        "agent": agent,
        "stage": stage,
        "opening_instruction": opening,
    }


def build_case_state(project_dir: Path, *, category: str = "", has_flag: bool = False) -> dict[str, Any]:
    runbook = load_runbook(project_dir)
    evidence_entries = parse_markdown_log(project_dir / "logs" / "evidence.md")
    tried_entries = parse_markdown_log(project_dir / "logs" / "tried_paths.md")
    checkpoint_entries = parse_markdown_log(project_dir / "logs" / "checkpoint.md")
    attempt_entries = load_jsonl(project_dir / "logs" / "attempts.jsonl")
    artifact_index = build_artifact_index(project_dir, limit=8)

    last_evidence = evidence_entries[-1] if evidence_entries else {}
    last_checkpoint = checkpoint_entries[-1] if checkpoint_entries else {}
    last_tried = tried_entries[-1] if tried_entries else {}
    last_attempt = attempt_entries[-1] if attempt_entries else {}

    evidence_count = len(evidence_entries)
    checkpoint_count = len(checkpoint_entries)
    tried_count = sum(len((ent.get("items") or {}).get("tried_path", [])) for ent in tried_entries)
    rejected_count = sum(len((ent.get("items") or {}).get("rejected", [])) for ent in tried_entries)
    hypothesis_count = sum(len((ent.get("items") or {}).get("hypothesis", [])) for ent in evidence_entries + checkpoint_entries)

    current_stage = str(last_checkpoint.get("stage") or last_evidence.get("stage") or "").strip()
    current_status = str(last_checkpoint.get("status") or last_evidence.get("status") or "").strip()
    last_evidence_ts = last_evidence.get("timestamp")
    last_checkpoint_ts = last_checkpoint.get("timestamp")
    last_tried_ts = last_tried.get("timestamp")
    latest_activity_ts = _latest_ts(last_evidence_ts, last_checkpoint_ts, last_tried_ts, int(project_dir.stat().st_mtime))
    now_ts = int(dt.datetime.now().timestamp())
    stall_minutes = max(0, int((now_ts - latest_activity_ts) / 60)) if latest_activity_ts else None

    effective_category = str(category or runbook.get("category") or "").strip().lower()
    needs_external_research = effective_category in {"osint", "crypto", "forensics", "misc", "malware"}
    has_flag_file = has_flag or (project_dir / "flag.txt").exists() or (project_dir / "flag").exists()
    last_next = (last_checkpoint.get("items") or {}).get("next", []) or (last_evidence.get("items") or {}).get("next", [])
    last_hypothesis = (last_checkpoint.get("items") or {}).get("hypothesis", []) or (last_evidence.get("items") or {}).get("hypothesis", [])
    last_evidence_items = (last_checkpoint.get("items") or {}).get("evidence", []) or (last_evidence.get("items") or {}).get("evidence", [])
    top_artifacts = artifact_index.get("items") or []
    artifact_paths = [str(item.get("path") or "") for item in top_artifacts[:3] if str(item.get("path") or "").strip()]
    recent_attempts = attempt_entries[-5:]
    attempt_failure_summary = summarize_attempt_failures(recent_attempts)
    pivot_signals = 0
    interface_mismatch = False
    overexploration = False
    known_transports: list[str] = []
    counterevidence_items: list[str] = []
    for row in recent_attempts:
        transport = str(row.get("transport") or "").strip()
        if transport and transport not in known_transports:
            known_transports.append(transport)
        for item in row.get("counterevidence") or []:
            s = str(item).strip()
            if s:
                counterevidence_items.append(s)
        if row.get("pivot_trigger"):
            pivot_signals += len(row.get("pivot_trigger") or [])
        merged = " ".join(
            [
                " ".join(str(x) for x in (row.get("result") or [])),
                " ".join(str(x) for x in (row.get("counterevidence") or [])),
                " ".join(str(x) for x in (row.get("rejected") or [])),
            ]
        ).lower()
        if "unknown command" in merged or "[b" in merged or "repl" in merged or "ttyd" in merged or "websocket" in merged:
            interface_mismatch = True
        if any(tok in merged for tok in ["distribution only", "histogram only", "image enhancement only", "no validation"]):
            overexploration = True
    consecutive_failure_class = str(attempt_failure_summary.get("recent_consecutive_class") or "")
    consecutive_failure_count = int(attempt_failure_summary.get("recent_consecutive_count") or 0)

    action = "continue"
    reasons: list[str] = []
    confidence = 0.55

    if has_flag_file:
        action = "solved"
        reasons.append("flag.txt already present")
        confidence = 0.98
    elif consecutive_failure_count >= 2 and consecutive_failure_class in {"interface", "path", "candidate"}:
        action = "pivot"
        reasons.append(f"repeated {consecutive_failure_class} failures x{consecutive_failure_count}")
        confidence = 0.91
    elif consecutive_failure_count >= 3 and consecutive_failure_class in {"timeout", "remote", "failed", "blocked", "other"}:
        action = "pivot"
        reasons.append(f"repeated {consecutive_failure_class} failures x{consecutive_failure_count}")
        confidence = 0.87
    elif interface_mismatch:
        action = "pivot"
        reasons.append("interaction evidence suggests wrong transport/protocol layer")
        confidence = 0.92
    elif current_status in {"pivot", "blocked"}:
        action = "pivot"
        reasons.append(f"latest checkpoint status={current_status}")
        confidence = 0.86
    elif pivot_signals >= 2:
        action = "pivot"
        reasons.append("recent attempts accumulated explicit pivot triggers")
        confidence = 0.84
    elif evidence_count == 0 and needs_external_research:
        action = "research"
        reasons.append(f"category={effective_category} benefits from external retrieval")
        confidence = 0.82
    elif top_artifacts and evidence_count <= 1:
        action = "continue"
        reasons.append("artifact-first: validate highest-value local outputs before broader exploration")
        confidence = 0.76
    elif evidence_count == 0 and checkpoint_count == 0:
        action = "continue"
        reasons.append("no structured evidence yet; start minimal triage")
        confidence = 0.62
    elif stall_minutes is not None and stall_minutes >= 30 and needs_external_research:
        action = "research"
        reasons.append(f"stalled for {stall_minutes}m without fresh evidence")
        confidence = 0.83
    elif stall_minutes is not None and stall_minutes >= 30:
        action = "pivot"
        reasons.append(f"stalled for {stall_minutes}m without fresh evidence")
        confidence = 0.8
    elif tried_count + rejected_count >= 4 and evidence_count <= 2:
        action = "research" if needs_external_research else "pivot"
        reasons.append("many rejected paths with weak evidence accumulation")
        confidence = 0.78
    elif current_stage == "2" and evidence_count >= 3:
        action = "verify"
        reasons.append("late-stage work should prioritize closure and verification")
        confidence = 0.72
    else:
        reasons.append("recent evidence exists; continue current branch")

    should_search = False
    search_reasons: list[str] = []
    if not has_flag_file:
        if needs_external_research and evidence_count == 0:
            should_search = True
            search_reasons.append("category-first retrieval rule")
        if stall_minutes is not None and stall_minutes >= 15:
            should_search = True
            search_reasons.append(f"stall>{stall_minutes}m")
        if effective_category == "osint":
            should_search = True
            search_reasons.append("osint always search-first")

    role_plan = [
        {"role": "planner", "goal": "Summarize evidence, choose stage, decide continue/pivot/research/verify."},
        {"role": "solver", "goal": "Execute the current highest-confidence branch only."},
        {"role": "researcher", "goal": "Use external sources when router triggers or local evidence is weak."},
        {"role": "verifier", "goal": "Validate candidate flags or disprove the active hypothesis before expansion."},
    ]
    execution = pick_execution_plan(effective_category, action, {"stage": current_stage, "status": current_status, "hypothesis": last_hypothesis[:3], "evidence": last_evidence_items[:4], "next": last_next[:4]}, {"should_search": should_search, "reasons": search_reasons})
    opening = execution.get("opening_instruction") or ""
    if action == "continue" and artifact_paths:
        opening += " Start by validating these local artifacts in order: " + ", ".join(artifact_paths[:3]) + "."
    if action == "pivot" and interface_mismatch:
        opening += " Treat the current interface as contaminated; switch transport/protocol before any more timing tweaks."
    execution["opening_instruction"] = opening.strip()

    return {
        "project_dir": str(project_dir),
        "runbook": runbook,
        "counts": {
            "evidence_entries": evidence_count,
            "checkpoint_entries": checkpoint_count,
            "tried_paths": tried_count,
            "rejected_paths": rejected_count,
            "hypotheses": hypothesis_count,
            "attempt_entries": len(attempt_entries),
        },
        "latest": {
            "activity_ts": latest_activity_ts,
            "evidence_ts": last_evidence_ts,
            "checkpoint_ts": last_checkpoint_ts,
            "tried_ts": last_tried_ts,
            "stall_minutes": stall_minutes,
            "transport": str(last_attempt.get("transport") or "").strip(),
        },
        "current": {
            "stage": current_stage,
            "status": current_status,
            "hypothesis": last_hypothesis[:3],
            "evidence": last_evidence_items[:4],
            "counterevidence": counterevidence_items[-3:],
            "next": last_next[:4],
        },
        "artifact_focus": {
            "top_candidates": top_artifacts,
            "total_candidates": artifact_index.get("total_candidates", 0),
        },
        "attempt_summary": {
            "recent": recent_attempts,
            "known_transports": known_transports,
            "pivot_signals": pivot_signals,
            "interface_mismatch": interface_mismatch,
            "overexploration": overexploration,
            "failure_classes": attempt_failure_summary.get("classes", []),
            "failure_counts": attempt_failure_summary.get("counts", {}),
            "recent_consecutive_class": consecutive_failure_class,
            "recent_consecutive_count": consecutive_failure_count,
        },
        "decision": {
            "action": action,
            "reasons": reasons,
            "confidence": round(confidence, 2),
        },
        "research_router": {
            "should_search": should_search,
            "reasons": search_reasons,
        },
        "role_plan": role_plan,
        "execution": execution,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build structured case state + decision for a CTF project.")
    ap.add_argument("--project", help="Project path or name under workspace/active")
    ap.add_argument("--challenge-json", help="Optional challenge json file to locate project")
    ap.add_argument("--json", action="store_true", help="Print JSON")
    args = ap.parse_args()

    project_dir: Path | None = None
    category = ""
    has_flag = False
    if args.project:
        project_dir = resolve_project_path(args.project)
    elif args.challenge_json:
        data = json.loads(_read_text(Path(args.challenge_json)))
        if not isinstance(data, dict):
            raise SystemExit("invalid challenge json")
        project_dir = find_project_for_challenge(data)
        category = str(data.get("category") or "")
        has_flag = bool(data.get("flag_present") or data.get("flag_value"))
    if not project_dir:
        raise SystemExit("project not found")

    state = build_case_state(project_dir, category=category, has_flag=has_flag)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print(f"project={state['project_dir']}")
        print(f"decision={state['decision']['action']} confidence={state['decision']['confidence']}")
        print(f"stall_minutes={state['latest']['stall_minutes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
