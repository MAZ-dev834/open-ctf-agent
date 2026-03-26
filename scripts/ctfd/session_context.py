#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_challenge_solve_report(ch_dir: Path) -> dict:
    path = ch_dir / "solve_report.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def trim_items(values, limit: int = 3) -> list[str]:
    items = []
    for value in values or []:
        text = str(value).strip()
        if not text:
            continue
        items.append(text)
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def load_recent_attempts(ch_dir: Path, limit: int = 5) -> list[dict]:
    path = ch_dir / "logs" / "attempts.jsonl"
    if not path.exists():
        return []
    rows = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows[-limit:]


def build_session_message(
    *,
    ch: dict,
    ch_dir: Path,
    case_state: dict,
    solve_report: dict,
    recent_attempts: list[dict],
    search_friendly: bool,
    canonical_category_func,
    resume_session_id: str = "",
) -> str:
    decision = case_state.get("decision") or {}
    current = case_state.get("current") or {}
    execution = case_state.get("execution") or {}
    router = case_state.get("research_router") or {}
    latest = case_state.get("latest") or {}

    action = str(decision.get("action") or "continue").strip()
    reasons = trim_items(decision.get("reasons"), limit=3)
    hypothesis = trim_items(current.get("hypothesis"), limit=3)
    evidence = trim_items(current.get("evidence"), limit=4)
    counterevidence = trim_items(current.get("counterevidence"), limit=3)
    next_steps = trim_items(current.get("next"), limit=3)
    search_reasons = trim_items(router.get("reasons"), limit=3)
    opening = str(execution.get("opening_instruction") or "").strip()
    stall_minutes = latest.get("stall_minutes")
    last_outcome = str(solve_report.get("outcome") or "").strip()
    last_failure = str(solve_report.get("failure_reason") or "").strip()
    last_trace = trim_items(solve_report.get("decision_trace"), limit=5)
    best_next = str(solve_report.get("highest_value_next_command") or "").strip()
    submission_status = str(solve_report.get("submission_status") or "").strip()
    execution_profile = str(ch.get("execution_profile") or ch.get("subagent_profile") or "").strip()
    execution_profile_prompt_path = str(
        ch.get("execution_profile_prompt_path") or ch.get("subagent_prompt_path") or ""
    ).strip()

    if not reasons:
        last_attempt = recent_attempts[-1] if recent_attempts else {}
        reasons = trim_items(
            (last_attempt.get("pivot_trigger") or []) + (last_attempt.get("counterevidence") or []),
            limit=3,
        )
        if not reasons and last_failure:
            reasons = [f"last_failure={last_failure}"]
    if not evidence and solve_report.get("oracle_summary"):
        evidence = trim_items(solve_report.get("oracle_summary"), limit=4)
    if not counterevidence and recent_attempts:
        merged_counter = []
        for row in reversed(recent_attempts):
            merged_counter.extend(row.get("counterevidence") or [])
        counterevidence = trim_items(merged_counter, limit=3)
    if not next_steps:
        merged_next = []
        for row in reversed(recent_attempts):
            merged_next.extend(row.get("next") or [])
        next_steps = trim_items(merged_next, limit=3)
    if not opening:
        if action == "pivot":
            opening = "Current branch is weak or repetitive. Summarize what failed, choose one new branch, and avoid repeating the same session path."
        elif action == "research":
            opening = "Switch into evidence-first research mode. Search the exact stalled technical point and convert findings into a concrete next step."
        elif action == "verify":
            opening = "Stay narrow. Verify the current candidate or replay path before broadening."
        else:
            opening = "Continue from the strongest current branch instead of restarting from generic recon."
    if not action or action == "continue":
        if last_failure in {"session_timeout", "session_failed"}:
            action = "pivot"
        elif router.get("should_search"):
            action = "research"
    if not hypothesis and recent_attempts:
        merged_h = []
        for row in reversed(recent_attempts):
            merged_h.extend(row.get("hypothesis") or [])
        hypothesis = trim_items(merged_h, limit=3)
    current_cat = str(canonical_category_func(ch.get("category", "")) or "").strip()
    if current_cat and current_cat != "unknown":
        fallback_hypothesis = f"pipeline run for {ch.get('name','')} ({current_cat})"
        if not hypothesis:
            hypothesis = [fallback_hypothesis]
        else:
            normalized = []
            replaced = False
            for item in hypothesis:
                if "(unknown)" in item and not replaced:
                    normalized.append(fallback_hypothesis)
                    replaced = True
                else:
                    normalized.append(item)
            hypothesis = trim_items(normalized, limit=3)
    if stall_minutes is None and recent_attempts:
        stall_minutes = ""

    mode_line = (
        f"Resume the existing session for challenge {ch.get('id')} ({ch.get('name','')})."
        if resume_session_id
        else f"Start a fresh session for challenge {ch.get('id')} ({ch.get('name','')})."
    )
    lines = [mode_line]
    lines.append(
        "Use web_prompt.txt as the primary task statement, task.json for structured fields, and challenge_context.json for pipeline state."
    )
    lines.append(
        "Treat this as pipeline mode even if shell-visible env vars are absent. pipeline_env.json / pipeline_env.sh are authoritative fallbacks."
    )
    lines.append(f"Authoritative challenge workspace: {ch_dir}")
    if execution_profile:
        lines.append(f"Selected execution profile: {execution_profile}.")
        if execution_profile_prompt_path:
            lines.append(f"Execution profile source: {execution_profile_prompt_path}")
    lines.append(
        "If you need shell env vars, run `source ./pipeline_env.sh` from the attached challenge directory before executing dependent commands."
    )
    lines.append("Do not restart from zero. First read the attached files, then continue from the current decision state below.")
    lines.append(f"Current decision: action={action}.")
    if opening:
        lines.append(f"Opening instruction: {opening}")
    if reasons:
        lines.append("Why this action now:")
        for item in reasons:
            lines.append(f"- {item}")
    if hypothesis:
        lines.append("Current hypothesis:")
        for item in hypothesis:
            lines.append(f"- {item}")
    if evidence:
        lines.append("Locked evidence:")
        for item in evidence:
            lines.append(f"- {item}")
    if counterevidence:
        lines.append("Counterevidence / failed signals:")
        for item in counterevidence:
            lines.append(f"- {item}")
    if next_steps:
        lines.append("Existing next steps from logs:")
        for item in next_steps:
            lines.append(f"- {item}")
    if best_next:
        lines.append(f"Highest-value next command from solve_report: {best_next}")
    if last_outcome or last_failure or submission_status:
        lines.append(
            f"Last recorded outcome: outcome={last_outcome or 'unknown'} failure_reason={last_failure or 'none'} submission_status={submission_status or 'none'}."
        )
    if last_trace:
        lines.append("Recent decision trace:")
        for item in last_trace:
            lines.append(f"- {item}")
    if router.get("should_search") and (
        action == "research" or search_friendly or canonical_category_func(ch.get("category", "")) in {"osint", "crypto", "forensics", "misc", "malware"}
    ):
        lines.append("External search is currently justified. Search the stalled technical point, not the challenge title/event name.")
        if search_reasons:
            for item in search_reasons:
                lines.append(f"- search_reason: {item}")
    if stall_minutes not in (None, ""):
        lines.append(f"Observed stall time: {stall_minutes} minutes.")
    lines.append("Your first response must be:")
    lines.append("1. Summarize the current state in 3 short bullets.")
    lines.append("2. Name the single best next step based on the evidence above.")
    lines.append("3. Execute that step immediately, unless challenge_context.json clearly invalidates it.")
    lines.append("Work only on this challenge and keep outputs under the attached challenge directory.")
    return "\n".join(lines)
