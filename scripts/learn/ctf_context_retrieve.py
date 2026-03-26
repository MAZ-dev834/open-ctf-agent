#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

try:
    from scripts.learn.ctf_meta import normalize_project_key
except Exception:  # pragma: no cover
    from ctf_meta import normalize_project_key  # type: ignore


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def canonical_category(raw: str) -> str:
    c = normalize_text(raw)
    mapping = {
        "web exploitation": "web",
        "web": "web",
        "pwn": "pwn",
        "binary exploitation": "pwn",
        "rev": "rev",
        "reverse engineering": "rev",
        "crypto": "crypto",
        "cryptography": "crypto",
        "misc": "misc",
        "miscellaneous": "misc",
        "forensics": "forensics",
        "forensic": "forensics",
        "dfir": "forensics",
        "digital forensics": "forensics",
        "osint": "osint",
        "geoint": "osint",
        "geo": "osint",
        "threat intel": "osint",
        "threat intelligence": "osint",
        "malware": "malware",
        "hardware": "forensics",
        "stego": "forensics",
        "steganography": "forensics",
    }
    if c in mapping:
        return mapping[c]
    if "web" in c:
        return "web"
    if "crypto" in c:
        return "crypto"
    if "reverse" in c or c == "rev":
        return "rev"
    if "pwn" in c or "binary exploitation" in c:
        return "pwn"
    if "malware" in c:
        return "malware"
    if "osint" in c or "geoint" in c or c == "geo":
        return "osint"
    if any(x in c for x in ("forensic", "hardware", "stego", "dfir")):
        return "forensics"
    if "misc" in c:
        return "misc"
    return "unknown"


def challenge_key_string(name: str, category: str) -> str:
    name_key = normalize_text(name)
    cat_key = normalize_text(category)
    return f"{cat_key}/{name_key}" if name_key else ""


def read_brief_text(path_obj: Path, *, max_lines: int = 6, max_chars: int = 420) -> str:
    if not path_obj.exists():
        return ""
    try:
        lines = []
        for raw in path_obj.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            if len(lines) >= max_lines:
                break
        return " | ".join(lines)[:max_chars].strip()
    except Exception:
        return ""


def extract_evidence_snippets(project_dir: Path, *, limit: int = 8) -> list[str]:
    evidence_path = project_dir / "logs" / "evidence.md"
    if not evidence_path.exists():
        return []
    out: list[str] = []
    prefixes = ("- evidence:", "- hypothesis:", "- counterevidence:", "- next:", "- action:", "- result:")
    try:
        for raw in evidence_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line.startswith(prefixes):
                continue
            if len(line) > 220:
                line = line[:220]
            out.append(line)
            if len(out) >= limit:
                break
    except Exception:
        return []
    return out


def build_query_text(ch: dict) -> str:
    parts: list[str] = []
    for key in ("name", "description", "category", "connection_info", "instance_url", "flag_format"):
        value = str(ch.get(key) or "").strip()
        if value:
            parts.append(value)
    attachments = ch.get("attachments") or []
    attach_names = [Path(str(x)).name for x in attachments if str(x).strip()]
    if attach_names:
        parts.append("attachments: " + " ".join(attach_names[:6]))
    ch_dir = Path(ch.get("challenge_dir", "")).resolve()
    if ch_dir.exists():
        snippets = extract_evidence_snippets(ch_dir, limit=8)
        if snippets:
            parts.append("known evidence: " + " ".join(snippets))
    text = "\n".join(x for x in parts if x)
    return text[:4000]


def _run_json_cmd(cmd: list[str], *, timeout_sec: int = 25) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except Exception:
        return {}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
        except Exception:
            return {}
    return {}


def collect_prior_same_challenge_history(ch: dict, *, events_root: Path, limit: int = 3) -> list[dict]:
    current_dir = Path(ch.get("challenge_dir", "")).resolve()
    current_event = current_dir.parents[1].name if len(current_dir.parents) >= 2 else ""
    want_key = str(ch.get("challenge_key") or challenge_key_string(ch.get("name", ""), ch.get("category", ""))).strip().lower()
    want_name = normalize_project_key(str(ch.get("name", ""))).strip().lower()
    want_cat = canonical_category(ch.get("category", ""))
    if not events_root.exists():
        return []

    hits = []
    for task_path in events_root.rglob("task.json"):
        task_dir = task_path.parent.resolve()
        if task_dir == current_dir:
            continue
        try:
            task = json.loads(task_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        cand_key = str(task.get("challenge_key") or "").strip().lower()
        cand_name = normalize_project_key(str(task.get("name", ""))).strip().lower()
        cand_cat = canonical_category(task.get("category", ""))
        if want_key and cand_key == want_key:
            match_reason = "challenge_key"
        elif want_name and cand_name == want_name and cand_cat == want_cat:
            match_reason = "name+category"
        else:
            continue

        event_key = str(task.get("event_key") or (task_dir.parents[1].name if len(task_dir.parents) >= 2 else ""))
        if current_event and event_key == current_event:
            continue

        flag_path = task_dir / "flag.txt"
        flag_low_path = task_dir / "flag_low.txt"
        solve_path = task_dir / "solve.py"
        writeup_path = task_dir / "writeup.md"
        evidence_path = task_dir / "logs" / "evidence.md"
        solve_report_path = task_dir / "solve_report.json"
        submission_status = ""
        outcome = ""
        if solve_report_path.exists():
            try:
                rep = json.loads(solve_report_path.read_text(encoding="utf-8", errors="ignore"))
                submission_status = str(rep.get("submission_status") or "")
                outcome = str(rep.get("outcome") or "")
            except Exception:
                pass

        summary_parts = []
        evidence_brief = read_brief_text(evidence_path)
        flag_low_brief = read_brief_text(flag_low_path)
        if evidence_brief:
            summary_parts.append(f"evidence={evidence_brief}")
        if flag_low_brief:
            summary_parts.append(f"flag_low={flag_low_brief}")
        hits.append(
            {
                "event_key": event_key,
                "challenge_dir": str(task_dir),
                "match_reason": match_reason,
                "submission_status": submission_status,
                "outcome": outcome,
                "has_flag": flag_path.exists(),
                "has_flag_low": flag_low_path.exists(),
                "has_solve": solve_path.exists(),
                "has_writeup": writeup_path.exists(),
                "summary": " | ".join(summary_parts)[:700],
            }
        )

    hits.sort(
        key=lambda item: (
            1 if item.get("has_flag") else 0,
            1 if item.get("submission_status") in {"correct", "already_solved"} else 0,
            1 if item.get("has_solve") else 0,
            1 if item.get("has_flag_low") else 0,
            1 if item.get("has_writeup") else 0,
            item.get("event_key", ""),
        ),
        reverse=True,
    )
    return hits[:limit]


def retrieve_challenge_context(
    ch: dict,
    *,
    repo_root: Path,
    memory_script: Path,
    failure_script: Path,
    limit: int = 3,
) -> dict:
    query_text = build_query_text(ch)
    category = canonical_category(ch.get("category", ""))
    rec_cmd = [
        "python3",
        str(memory_script),
        "--text",
        query_text,
        "--category",
        category,
        "--limit",
        str(limit),
        "--json",
    ]
    fail_cmd = [
        "python3",
        str(failure_script),
        "--text",
        query_text,
        "--category",
        category,
        "--limit",
        str(limit),
        "--json",
    ]
    rec_payload = _run_json_cmd(rec_cmd, timeout_sec=25)
    fail_payload = _run_json_cmd(fail_cmd, timeout_sec=25)
    return {
        "query_text": query_text,
        "memory_recommendations": rec_payload.get("recommendations") if isinstance(rec_payload, dict) else [],
        "failure_watchlist": fail_payload.get("watchlist") if isinstance(fail_payload, dict) else [],
        "prior_same_challenge_history": collect_prior_same_challenge_history(
            ch,
            events_root=repo_root / "events",
            limit=limit,
        ),
    }

