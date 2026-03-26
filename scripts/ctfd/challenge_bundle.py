#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path


def build_task_payload(ch: dict, *, event_key: str, challenge_key: str) -> dict:
    return {
        "challenge_id": ch["id"],
        "name": ch.get("name", ""),
        "category": ch.get("category", ""),
        "event_key": event_key,
        "challenge_key": challenge_key,
        "flag_format": ch.get("flag_format", ""),
        "needs_container": bool(ch.get("needs_container", False)),
        "instance_url": ch.get("instance_url", ""),
        "connection_info": ch.get("connection_info", ""),
        "attachments": ch.get("attachments", []),
        "description": ch.get("description", ""),
        "remote_ready": bool(ch.get("remote_ready", False)),
        "remote_gate_status": ch.get("remote_gate_status", ""),
        "remote_gate_reason": ch.get("remote_gate_reason", ""),
        "container_probe_ready": bool(ch.get("container_probe_ready", False)),
        "has_remote_target": bool(ch.get("has_remote_target", False)),
        "interactive_risk": ch.get("interactive_risk", "none"),
        "submit_disabled": bool(ch.get("submit_disabled", False)),
        "recommended_agent": ch.get("recommended_agent", "ctf"),
        "context_query_text": ch.get("context_query_text", ""),
        "memory_recommendations": ch.get("memory_recommendations", []),
        "prior_same_challenge_history": ch.get("prior_same_challenge_history", []),
        "failure_watchlist": ch.get("failure_watchlist", []),
        "image_guard": ch.get("image_guard", []),
        "image_ocr_hits": ch.get("image_ocr_hits", []),
        "execution_profile": ch.get("execution_profile", ""),
        "execution_profile_prompt_path": ch.get("execution_profile_prompt_path", ""),
        "subagent_profile": ch.get("execution_profile", ch.get("subagent_profile", "")),
        "subagent_prompt_path": ch.get("execution_profile_prompt_path", ch.get("subagent_prompt_path", "")),
    }


def build_context_payload(
    ch: dict,
    *,
    ch_dir: Path,
    event_key: str,
    case_state: dict,
) -> dict:
    return {
        "schema_version": 1,
        "challenge_id": ch.get("id"),
        "name": ch.get("name", ""),
        "category": ch.get("category", ""),
        "event_key": event_key,
        "challenge_dir": str(ch_dir),
        "description": ch.get("description", ""),
        "attachments": ch.get("attachments", []),
        "target": ch.get("target", ""),
        "tags": ch.get("tags", []),
        "author": ch.get("author", ""),
        "flag_format": ch.get("flag_format", ""),
        "needs_container": bool(ch.get("needs_container", False)),
        "instance_url": ch.get("instance_url", ""),
        "connection_info": ch.get("connection_info", ""),
        "remote_ready": bool(ch.get("remote_ready", False)),
        "remote_gate_status": ch.get("remote_gate_status", ""),
        "remote_gate_reason": ch.get("remote_gate_reason", ""),
        "container_probe_ready": bool(ch.get("container_probe_ready", False)),
        "has_remote_target": bool(ch.get("has_remote_target", False)),
        "interactive_risk": ch.get("interactive_risk", "none"),
        "submit_disabled": bool(ch.get("submit_disabled", False)),
        "recommended_agent": ch.get("recommended_agent", "ctf"),
        "context_query_text": ch.get("context_query_text", ""),
        "memory_recommendations": ch.get("memory_recommendations", []),
        "prior_same_challenge_history": ch.get("prior_same_challenge_history", []),
        "failure_watchlist": ch.get("failure_watchlist", []),
        "image_guard": ch.get("image_guard", []),
        "image_ocr_hits": ch.get("image_ocr_hits", []),
        "execution_profile": ch.get("execution_profile", ""),
        "execution_profile_prompt_path": ch.get("execution_profile_prompt_path", ""),
        "subagent_profile": ch.get("execution_profile", ch.get("subagent_profile", "")),
        "subagent_prompt_path": ch.get("execution_profile_prompt_path", ch.get("subagent_prompt_path", "")),
        "submit_policy": {
            "score_required": True,
            "default_strategy": "balanced",
        },
        "case_state": case_state,
        "updated_at": time.time(),
    }


def render_prompt(ch: dict) -> str:
    attachments = []
    targets = []
    for x in ch.get("attachments", []):
        if Path(str(x)).is_absolute():
            attachments.append(str(x))
        elif "://" in str(x) or ":" in str(x):
            targets.append(str(x))
        else:
            attachments.append(str(Path(ch["challenge_dir"]) / str(x)))

    lines = [
        "Title: " + (ch.get("name") or ""),
        "Category (if known): " + (ch.get("category") or ""),
        "Flag format: " + (ch.get("flag_format") or ""),
        "Description:",
        ch.get("description") or "",
        "Target URL or host:port:",
    ]
    if ch.get("instance_url"):
        lines.append(ch["instance_url"])
    elif ch.get("connection_info"):
        lines.append(ch["connection_info"])
    elif targets:
        lines.extend(targets)
    lines += [
        "Attachments (absolute paths):",
    ]
    if attachments:
        lines.extend(attachments)
    lines += [
        "Constraints (time, tool limits, etc.):",
        "- Use available local scripts in this workspace.",
        f"- Use work root: {str(ch.get('work_root') or '')}",
        f"- Remote readiness: {'ready' if ch.get('remote_ready') else 'not_ready'} ({ch.get('remote_gate_reason','')})",
        "- If remote readiness is not_ready, do local/static solving first and do not assume remote exploitability until target is reachable.",
        "- Never use Read on image/binary/media files. Inspect them locally with file/exiftool/strings/binwalk/PIL/OpenCV/OCR scripts and only send concise text findings back into the session.",
        "- If a prior branch already read a .png/.jpg/.jpeg/.gif/.bmp/.tif/.tiff/.webp/.pdf or other binary file into the model context, treat that session as contaminated: stop and restart from a clean summary.",
        f"- Recommended specialist agent: {ch.get('recommended_agent', 'ctf')}",
        f"- Interactive risk level: {ch.get('interactive_risk', 'none')}",
        "- For high/moderate interactive risk, prioritize throttle+budget+short sessions before brute force.",
    ]
    submit_disabled = bool(ch.get("submit_disabled"))
    if submit_disabled:
        lines += [
            "- This is a regression/local-only challenge run. Do NOT call submit gate or submit to any platform.",
            f"- If you recover a strong candidate, write it to: {str(Path(ch['challenge_dir']) / 'flag.txt')}",
            "- Keep concise local evidence in solve_report/writeup artifacts only.",
        ]
    else:
        lines += [
            f"- Pipeline submit gate (must): test candidate flags by running scripts/submit/ctf_pipeline_submit_gate.py --challenge-dir \"{str(Path(ch['challenge_dir']))}\" --id {ch.get('id')} --flag \"<candidate>\"",
            "- Candidate score is required by default submit policy (unless allow-override is explicitly enabled).",
            "- Prefer score-thresholded submit for ranked candidates: add --candidate-score <0..1> --min-candidate-score <threshold>.",
            "- For candidate batches, use scripts/submit/ctf_submit_candidates.py --strategy balanced with candidates.json (flag+score).",
            f"- If gate returns ok=true/correct|already_solved, then write final flag to: {str(Path(ch['challenge_dir']) / 'flag.txt')}",
            f"- If gate fails, do NOT write flag.txt; keep notes in {str(Path(ch['challenge_dir']) / 'flag_low.txt')}",
            "- Write writeup.md only after successful submit gate.",
            "- If a flag is found, provide concise evidence and readiness to submit.",
        ]
    execution_profile = str(ch.get("execution_profile") or ch.get("subagent_profile") or "").strip()
    execution_profile_prompt_path = str(
        ch.get("execution_profile_prompt_path") or ch.get("subagent_prompt_path") or ""
    ).strip()
    execution_profile_prompt_text = str(
        ch.get("execution_profile_prompt_text") or ch.get("subagent_prompt_text") or ""
    ).strip()
    lines.append("Selected execution profile:")
    if execution_profile:
        lines.append(f"- profile: {execution_profile}")
        if execution_profile_prompt_path:
            lines.append(f"- source: {execution_profile_prompt_path}")
        if execution_profile_prompt_text:
            lines.append("- profile instructions:")
            for raw in execution_profile_prompt_text.splitlines():
                text = str(raw).rstrip()
                if text:
                    lines.append(f"  {text}")
    else:
        lines.append("- none")
    recs = ch.get("memory_recommendations") or []
    lines.append("Top memory recommendations:")
    if recs:
        for rec in recs[:3]:
            lines.append(f"- {rec.get('project','?')} score={rec.get('score','?')} conf={rec.get('confidence','?')}")
    else:
        lines.append("- none")
    prior_hist = ch.get("prior_same_challenge_history") or []
    lines.append("Prior same-challenge history:")
    if prior_hist:
        for item in prior_hist[:3]:
            flags = []
            if item.get("has_flag"):
                flags.append("flag")
            if item.get("has_solve"):
                flags.append("solve.py")
            if item.get("has_flag_low"):
                flags.append("flag_low")
            if item.get("has_writeup"):
                flags.append("writeup")
            status_bits = ",".join(flags) if flags else "no_artifacts"
            lines.append(
                f"- event={item.get('event_key','?')} match={item.get('match_reason','?')} "
                f"status={item.get('submission_status') or item.get('outcome') or 'unknown'} "
                f"artifacts={status_bits}"
            )
            if item.get("summary"):
                lines.append(f"  summary: {item.get('summary')}")
            if item.get("challenge_dir"):
                lines.append(f"  dir: {item.get('challenge_dir')}")
    else:
        lines.append("- none")
    watch = ch.get("failure_watchlist") or []
    lines.append("Recent failure watchlist:")
    if watch:
        for item in watch[:3]:
            sigs = item.get("failure_signals") or []
            lines.append(f"- {item.get('project','?')} score={item.get('score','?')} signals={','.join(str(x) for x in sigs[:3])}")
    else:
        lines.append("- none")
    guard = ch.get("image_guard") or []
    lines.append("Image guard results:")
    if guard:
        for item in guard[:5]:
            status = item.get("status", "unknown")
            inp = item.get("input", "")
            repaired = item.get("repaired_path", "")
            tail = f" repaired={repaired}" if repaired else ""
            if inp:
                try:
                    inp = Path(inp).name
                except Exception:
                    pass
            lines.append(f"- {inp} status={status}{tail}")
    else:
        lines.append("- none")
    ocr_hits = ch.get("image_ocr_hits") or []
    lines.append("Image text scan results:")
    if ocr_hits:
        for item in ocr_hits[:8]:
            inp = item.get("input", "")
            if inp:
                try:
                    inp = Path(inp).name
                except Exception:
                    pass
            candidates = item.get("candidates") or []
            engine = item.get("best_engine") or "?"
            variant = item.get("best_variant") or "?"
            if candidates:
                lines.append(f"- {inp} engine={engine}/{variant} candidates={'; '.join(str(x) for x in candidates[:3])}")
            else:
                lines.append(f"- {inp} engine={engine}/{variant} candidates=none")
        lines.append("- If an image already yields a flag-like candidate, stop broad solving and enter submit-gate closure mode.")
    else:
        lines.append("- none")
    return "\n".join(lines).strip() + "\n"
