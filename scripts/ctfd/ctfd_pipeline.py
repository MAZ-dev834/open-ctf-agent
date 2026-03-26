#!/usr/bin/env python3
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    from scripts.learn.ctf_context_retrieve import retrieve_challenge_context
    from scripts.core.ctf_paths import challenge_workspace_dirs, pick_challenge_workspace, resolve_work_root
    from scripts.core.runtime_config import (
        default_agent_model,
        default_first_blood_model,
        default_opencode_config_path,
        repo_root,
    )
    from scripts.core.ctf_case_state import build_case_state
    from scripts.ctfd.challenge_bundle import (
        build_context_payload,
        build_task_payload,
        render_prompt,
    )
    from scripts.ctfd.session_context import (
        build_session_message as compose_session_message,
        load_challenge_solve_report,
        load_recent_attempts,
    )
    from scripts.ctfd.session_store import (
        append_session_record as append_session_record_store,
        find_duplicate_active_session as find_duplicate_active_session_store,
        find_latest_recorded_session_id as find_latest_recorded_session_id_store,
    )
    from scripts.ctfd.session_lifecycle import (
        acquire_lock as lifecycle_acquire_lock,
        close_orphan_duplicate_session as lifecycle_close_orphan_duplicate_session,
        install_lock_signal_handlers as lifecycle_install_lock_signal_handlers,
        release_lock as lifecycle_release_lock,
        should_skip_for_duplicate_session as lifecycle_should_skip_for_duplicate_session,
        validate_resumable_session_agent as lifecycle_validate_resumable_session_agent,
    )
    from scripts.ctfd.run_state import (
        finalize_attempt_outputs as finalize_attempt_outputs_state,
        record_preflight_failure as record_preflight_failure_state,
        record_session_phase as record_session_phase_state,
        update_remote_readiness_status as update_remote_readiness_status_state,
        update_run_budget as update_run_budget_state,
    )
    from scripts.ctfd.run_context import PipelineRunContext
    from scripts.ctfd.dispatch_planner import prepare_challenge_dispatch
    from scripts.ctfd.challenge_runner import execute_challenge_run
    from scripts.ctfd.prompt_runtime import compose_pipeline_prompt
    from scripts.ctfd.repair_event_state import repair_event_state
    from scripts.ctfd.opencode_adapter import (
        find_opencode_session_record,
        get_opencode_session_agent_state,
        resolve_opencode_attach_url,
        resolve_opencode_session_for_active_record as adapter_resolve_opencode_session_for_active_record,
        should_attach_opencode_server,
    )
except Exception:  # pragma: no cover
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.learn.ctf_context_retrieve import retrieve_challenge_context
    from scripts.core.ctf_paths import challenge_workspace_dirs, pick_challenge_workspace, resolve_work_root
    from scripts.core.runtime_config import (
        default_agent_model,
        default_first_blood_model,
        default_opencode_config_path,
        repo_root,
    )
    from scripts.core.ctf_case_state import build_case_state
    from scripts.ctfd.challenge_bundle import (
        build_context_payload,
        build_task_payload,
        render_prompt,
    )
    from scripts.ctfd.session_context import (
        build_session_message as compose_session_message,
        load_challenge_solve_report,
        load_recent_attempts,
    )
    from scripts.ctfd.session_store import (
        append_session_record as append_session_record_store,
        find_duplicate_active_session as find_duplicate_active_session_store,
        find_latest_recorded_session_id as find_latest_recorded_session_id_store,
    )
    from scripts.ctfd.session_lifecycle import (
        acquire_lock as lifecycle_acquire_lock,
        close_orphan_duplicate_session as lifecycle_close_orphan_duplicate_session,
        install_lock_signal_handlers as lifecycle_install_lock_signal_handlers,
        release_lock as lifecycle_release_lock,
        should_skip_for_duplicate_session as lifecycle_should_skip_for_duplicate_session,
        validate_resumable_session_agent as lifecycle_validate_resumable_session_agent,
    )
    from scripts.ctfd.run_state import (
        finalize_attempt_outputs as finalize_attempt_outputs_state,
        record_preflight_failure as record_preflight_failure_state,
        record_session_phase as record_session_phase_state,
        update_remote_readiness_status as update_remote_readiness_status_state,
        update_run_budget as update_run_budget_state,
    )
    from scripts.ctfd.run_context import PipelineRunContext
    from scripts.ctfd.dispatch_planner import prepare_challenge_dispatch
    from scripts.ctfd.challenge_runner import execute_challenge_run
    from scripts.ctfd.prompt_runtime import compose_pipeline_prompt
    from scripts.ctfd.repair_event_state import repair_event_state
    from scripts.ctfd.opencode_adapter import (
        find_opencode_session_record,
        get_opencode_session_agent_state,
        resolve_opencode_attach_url,
        resolve_opencode_session_for_active_record as adapter_resolve_opencode_session_for_active_record,
        should_attach_opencode_server,
    )


def parse_bool_zh(value):
    v = (value or "").strip().lower()
    return v in {"yes", "true", "1", "y", "shi", "是"}


def submissions_disabled_for_challenge(args, ch: dict | None = None) -> bool:
    ch = ch or {}
    env_toggle = str(os.getenv("CTF_PIPELINE_DISABLE_SUBMIT", "")).strip().lower()
    if env_toggle in {"1", "true", "on", "yes"}:
        return True
    event_name = str(getattr(args, "competition", "") or "").strip().lower()
    out_root_name = str(getattr(args, "out_root", "") or "").strip().lower()
    regression_source = str(ch.get("regression_source") or "").strip()
    if regression_source:
        return True
    if "archive-regression" in event_name or "archive-regression" in out_root_name:
        return True
    return False


def load_env_file(path):
    out = {}
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except Exception:
        return {}
    return out


def update_env_file(path, updates):
    if not path:
        return
    current = load_env_file(path)
    for k, v in updates.items():
        if v is None or v == "":
            continue
        current[k] = str(v)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(current.keys()):
            f.write(f"{k}={current[k]}\n")


def parse_challenge_txt(path):
    meta = {
        "name": "",
        "category": "",
        "flag_format": "",
        "needs_container": False,
        "description": "",
        "target_or_attachments": [],
        "instance_url": "",
    }
    section = ""
    desc_lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("题目名称:"):
                meta["name"] = line.split(":", 1)[1].strip()
                section = ""
                continue
            if line.startswith("类别:"):
                meta["category"] = line.split(":", 1)[1].strip()
                section = ""
                continue
            if line.startswith("Flag 格式:"):
                meta["flag_format"] = line.split(":", 1)[1].strip()
                section = ""
                continue
            if line.startswith("需要启动容器:"):
                val = line.split(":", 1)[1].strip()
                meta["needs_container"] = parse_bool_zh(val)
                section = ""
                continue
            if line.startswith("容器地址:"):
                meta["instance_url"] = line.split(":", 1)[1].strip()
                continue
            if line == "描述:":
                section = "desc"
                continue
            if line == "目标地址或附件:":
                section = "target"
                continue

            if section == "desc":
                desc_lines.append(line)
            elif section == "target":
                value = line.strip()
                if value.startswith("- "):
                    value = value[2:].strip()
                if value:
                    meta["target_or_attachments"].append(value)

    meta["description"] = "\n".join(desc_lines).strip()
    return meta


def parse_id_from_dirname(dirname):
    m = re.match(r"^(\d+)\s+-\s+", dirname)
    if not m:
        return None
    return int(m.group(1))


def parse_int_set(expr):
    ids = set()
    if not expr:
        return ids
    for token in re.split(r"[,\s]+", str(expr).strip()):
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                a, b = int(parts[0]), int(parts[1])
                lo, hi = (a, b) if a <= b else (b, a)
                ids.update(range(lo, hi + 1))
                continue
        if token.isdigit():
            ids.add(int(token))
    return ids


def parse_category_set(values):
    cats = set()
    for raw in values or []:
        for token in str(raw).split(","):
            token = token.strip()
            if token:
                if token.lower() == "all":
                    cats.add("all")
                else:
                    cats.add(canonical_category(token))
    return cats


def normalize_text(s):
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def challenge_key(name, category):
    return (normalize_text(name), normalize_text(category))


def canonical_category(raw):
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




def category_specificity(cat: str) -> int:
    c = canonical_category(cat)
    return {
        "unknown": 0,
        "misc": 1,
        "web": 2,
        "pwn": 2,
        "rev": 2,
        "crypto": 2,
        "forensics": 3,
        "osint": 3,
        "malware": 3,
    }.get(c, 0)


def build_session_title(competition: str, category: str, name: str) -> str:
    return f"{competition} + {category} + {name}"


def recommended_agent_for_category(raw_cat):
    cat = canonical_category(raw_cat)
    return {
        "web": "ctf-web",
        "pwn": "ctf-pwn",
        "rev": "ctf-rev",
        "crypto": "ctf-crypto",
        "forensics": "ctf-forensics",
        "osint": "ctf-osint",
        "malware": "ctf-malware",
        "misc": "ctf-misc",
        "unknown": "ctf-main",
    }.get(cat, "ctf-main")


def resolve_agent_name(raw_agent: str) -> str:
    agent = str(raw_agent or "").strip()
    if agent == "ctf-main":
        return "ctf"
    return agent


def detect_interactive_risk(ch):
    text = " ".join(
        [
            str(ch.get("name", "")),
            str(ch.get("description", "")),
            " ".join(str(x) for x in (ch.get("attachments") or [])),
            str(ch.get("connection_info", "")),
            str(ch.get("instance_url", "")),
        ]
    ).lower()
    hits = 0
    keywords = [
        "oracle",
        "pow",
        "query",
        "cooldown",
        "rate limit",
        "timeout",
        "session",
        "disconnect",
        "staged",
        "layer",
        "interactive",
        "verify",
    ]
    for kw in keywords:
        if kw in text:
            hits += 1
    if hits >= 4:
        return "high"
    if hits >= 2:
        return "moderate"
    return "none"


def run_json_cmd(cmd, timeout_sec=20):
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_sec)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    out = (proc.stdout or "").strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except Exception:
        line = out.splitlines()[-1]
        try:
            return json.loads(line)
        except Exception:
            return {}


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
SCAN_SKIP_DIRS = {"artifacts", "logs", "runtime", "__pycache__", "node_modules", ".git"}
SESSIONS_FILE = "sessions.jsonl"
EVENT_INDEX_FILE = "event_index.json"
def collect_local_attachments(ch):
    paths = []
    for x in ch.get("attachments", []) or []:
        if os.path.isabs(x):
            p = Path(x)
            if p.exists():
                paths.append(p)
        elif "://" in x or ":" in x:
            continue
        else:
            p = Path(ch.get("challenge_dir", "")) / x
            if p.exists():
                paths.append(p)
    return paths


def guard_images_for_attachments(ch, *, timeout_sec: int = 45):
    results = []
    guard_path = Path(__file__).resolve().parents[1] / "core" / "ctf_image_guard.py"
    timeout_sec = max(3, int(timeout_sec or 45))
    for p in collect_local_attachments(ch):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        payload = run_json_cmd(
            ["python3", str(guard_path), "--input", str(p), "--json"],
            timeout_sec=timeout_sec,
        )
        if isinstance(payload, dict) and payload.get("status"):
            results.append(payload)
    return results


FLAG_PATTERNS = [
    re.compile(r"[A-Za-z0-9_]{0,24}\{[^{}\n]{1,256}\}"),
    re.compile(r"[A-Za-z0-9_]{1,48}\{[A-Za-z0-9_]{2,256}"),
    re.compile(r"_[A-Za-z0-9_]{2,256}\}"),
]


def _iter_workspace_images(root: Path) -> list[Path]:
    found = []
    if not root.exists():
        return found
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        lowered = {part.lower() for part in p.parts}
        if lowered & SCAN_SKIP_DIRS:
            continue
        found.append(p)
    return found


def collect_challenge_images(ch):
    seen = set()
    out = []
    for p in collect_local_attachments(ch):
        if p.suffix.lower() in IMAGE_EXTS and str(p) not in seen:
            out.append(p)
            seen.add(str(p))
    work_root = pick_challenge_workspace(Path(ch.get("challenge_dir", "")))
    for p in _iter_workspace_images(work_root):
        if str(p) not in seen:
            out.append(p)
            seen.add(str(p))
    return out


def _extract_flag_like_candidates(*texts):
    out = []
    seen = set()
    for text in texts:
        if not text:
            continue
        norm = re.sub(r"\s+", "", str(text))
        for pat in FLAG_PATTERNS:
            for m in pat.finditer(norm):
                cand = m.group(0)
                if not cand or cand in seen:
                    continue
                seen.add(cand)
                out.append(cand)
    return out


def scan_images_for_challenge(ch, *, timeout_sec: int = 90):
    results = []
    script = Path(__file__).resolve().parents[1] / "core" / "ocr_pipeline.py"
    if not script.exists():
        return results
    timeout_sec = max(3, int(timeout_sec or 90))
    for p in collect_challenge_images(ch):
        key = hashlib.sha1(str(p).encode("utf-8", errors="ignore")).hexdigest()[:12]
        out_dir = pick_challenge_workspace(Path(ch.get("challenge_dir", ""))) / "artifacts" / "ocr" / key
        report_path = out_dir / "ocr_report.json"
        cached_report = None
        if report_path.exists():
            try:
                if report_path.stat().st_mtime >= p.stat().st_mtime:
                    cached_report = json.loads(report_path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                cached_report = None
        if cached_report is not None:
            top = cached_report.get("top") or []
            candidates = []
            for item in top[:3]:
                candidates.extend(
                    _extract_flag_like_candidates(
                        item.get("normalized_text", ""),
                        item.get("text", ""),
                    )
                )
            best_engine = str(top[0].get("engine") or "") if top else ""
            best_variant = str(top[0].get("variant") or "") if top else ""
            results.append(
                {
                    "input": str(p),
                    "out_dir": str(out_dir),
                    "engine_status": cached_report.get("engine_status") or {},
                    "best_engine": best_engine,
                    "best_variant": best_variant,
                    "candidates": candidates[:5],
                }
            )
            continue
        cmd = [
            "python3",
            str(script),
            "--input",
            str(p),
            "--out-dir",
            str(out_dir),
            "--goal",
            "flag",
            "--max-variants",
            "4",
            "--top",
            "3",
            "--save-variants",
        ]
        flag_fmt = str(ch.get("flag_format") or "").strip()
        if flag_fmt and "{" in flag_fmt and "}" in flag_fmt:
            prefix = re.escape(flag_fmt.split("{", 1)[0])
            cmd += ["--flag-regex", rf"{prefix}\{{[^}}]+\}}"]
        try:
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_sec)
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        if not report_path.exists():
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        top = report.get("top") or []
        candidates = []
        for item in top[:3]:
            candidates.extend(
                _extract_flag_like_candidates(
                    item.get("normalized_text", ""),
                    item.get("text", ""),
                )
            )
        best_engine = ""
        best_variant = ""
        if top:
            best_engine = str(top[0].get("engine") or "")
            best_variant = str(top[0].get("variant") or "")
        results.append(
            {
                "input": str(p),
                "out_dir": str(out_dir),
                "engine_status": report.get("engine_status") or {},
                "best_engine": best_engine,
                "best_variant": best_variant,
                "candidates": candidates[:5],
            }
        )
    return results


def append_session_record(out_root: Path, payload: dict) -> None:
    append_session_record_store(out_root, SESSIONS_FILE, payload)


def load_event_index(out_root: Path) -> dict:
    path = out_root / EVENT_INDEX_FILE
    if not path.exists():
        return {"event": {}, "challenges": {}, "updated_at": time.time()}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {"event": {}, "challenges": {}, "updated_at": time.time()}


def save_event_index(out_root: Path, index: dict) -> None:
    path = out_root / EVENT_INDEX_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    index["updated_at"] = time.time()
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_event_index(
    out_root: Path,
    ch: dict,
    *,
    status_entry: dict | None = None,
    session_entry: dict | None = None,
    competition: str = "",
):
    index = load_event_index(out_root)
    event = index.setdefault("event", {})
    if competition:
        event["competition"] = competition
    event["event_dir"] = str(out_root)

    challenges = index.setdefault("challenges", {})
    key = str(ch.get("id", ""))
    rec = challenges.setdefault(
        key,
        {
            "id": ch.get("id"),
            "name": ch.get("name", ""),
            "category": ch.get("category", ""),
            "challenge_dir": ch.get("challenge_dir", ""),
            "status": "unknown",
            "session_count": 0,
        },
    )
    rec["name"] = ch.get("name", rec.get("name", ""))
    rec["category"] = ch.get("category", rec.get("category", ""))
    rec["challenge_dir"] = ch.get("challenge_dir", rec.get("challenge_dir", ""))
    if status_entry:
        if status_entry.get("solved"):
            rec["status"] = "solved"
        elif status_entry.get("submission_status"):
            rec["status"] = status_entry.get("submission_status")
        rec["submission_status"] = status_entry.get("submission_status")
        rec["last_submit_ts"] = status_entry.get("last_submit_ts")
    if session_entry:
        rec["last_session"] = {
            "session_uid": session_entry.get("session_uid"),
            "opencode_session_id": session_entry.get("opencode_session_id"),
            "phase": session_entry.get("phase"),
            "ts": session_entry.get("ts"),
            "returncode": session_entry.get("returncode"),
            "timed_out": session_entry.get("timed_out"),
            "agent": session_entry.get("agent"),
            "model": session_entry.get("model"),
        }
        phase = str(session_entry.get("phase") or "").lower()
        if phase == "start":
            rec["active_session_uid"] = session_entry.get("session_uid")
            rec["active_opencode_session_id"] = session_entry.get("opencode_session_id", "")
            rec["active_session_ts"] = session_entry.get("ts")
        elif phase == "bind":
            if rec.get("active_session_uid") == session_entry.get("session_uid"):
                rec["active_opencode_session_id"] = session_entry.get("opencode_session_id", "")
        elif phase == "end":
            if rec.get("active_session_uid") == session_entry.get("session_uid"):
                rec["active_session_uid"] = ""
                rec["active_opencode_session_id"] = ""
                rec["active_session_ts"] = None
        if session_entry.get("phase") == "end":
            rec["session_count"] = int(rec.get("session_count", 0)) + 1

    challenges[key] = rec
    save_event_index(out_root, index)


def enrich_challenge_context(ch):
    ctx = retrieve_challenge_context(
        ch,
        repo_root=repo_root(),
        memory_script=Path(__file__).resolve().parents[1] / "learn" / "ctf_memory_recommend.py",
        failure_script=Path(__file__).resolve().parents[1] / "learn" / "ctf_failure_check.py",
        limit=3,
    )
    ch["context_query_text"] = str(ctx.get("query_text") or "")
    recs = ctx.get("memory_recommendations") or []
    watch = ctx.get("failure_watchlist") or []
    prior = ctx.get("prior_same_challenge_history") or []
    ch["memory_recommendations"] = recs if isinstance(recs, list) else []
    ch["failure_watchlist"] = watch if isinstance(watch, list) else []
    ch["prior_same_challenge_history"] = prior if isinstance(prior, list) else []
    ch["interactive_risk"] = detect_interactive_risk(ch)
    ch["recommended_agent"] = recommended_agent_for_category(ch.get("category", ""))
    return ch

def is_candidate_flag_path(path_obj):
    lowered_parts = {p.lower() for p in path_obj.parts}
    banned = {
        "attachments",
        "题目附件",
        "extracted",
        "artifacts",
        "logs",
        "__pycache__",
        ".git",
    }
    return not (lowered_parts & banned)


def find_local_flag_files(ch):
    ch_dir = Path(ch.get("challenge_dir", ""))
    if not ch_dir.exists():
        return []
    root_candidates = [ch_dir / "flag.txt", ch_dir / "flag"]
    scoped_candidates = []
    for work_dir in challenge_workspace_dirs(ch_dir):
        if work_dir.exists():
            scoped_candidates.extend([p for p in work_dir.rglob("flag.txt") if is_candidate_flag_path(p)])
            scoped_candidates.extend([p for p in work_dir.rglob("flag") if is_candidate_flag_path(p)])
    seen = set()
    ordered = []
    for p in root_candidates + scoped_candidates:
        try:
            rp = str(p.resolve())
        except Exception:
            rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        if p.exists() and p.is_file():
            ordered.append(p)
    ordered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return ordered


def build_work_flag_index(work_root):
    root = resolve_work_root(work_root, legacy_fallback=True)
    if not root.exists() or not root.is_dir():
        return {}
    index = {}
    for item in root.iterdir():
        if not item.is_dir():
            continue
        meta_candidates = [
            item / "challenge.json",
            item / "attachments" / "challenge.json",
            item / "题目附件" / "challenge.json",
        ]
        meta = next((m for m in meta_candidates if m.exists() and m.is_file()), None)
        if meta is None:
            continue
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = payload.get("title", "")
        category = payload.get("category", "")
        key = challenge_key(title, category)
        if not key[0]:
            continue
        flag_paths = [item / "flag.txt", item / "flag"]
        flag_paths = [p for p in flag_paths if p.exists() and p.is_file()]
        if not flag_paths:
            continue
        best = max(flag_paths, key=lambda p: p.stat().st_mtime)
        mtime = best.stat().st_mtime
        prev = index.get(key)
        if prev is None or mtime > prev["mtime"]:
            index[key] = {"path": best, "mtime": mtime}
    return index


def _extract_submit_status(record):
    status = ""
    message = ""
    if not isinstance(record, dict):
        return status, message
    resp = record.get("response")
    if isinstance(resp, dict):
        data = resp.get("data") or {}
        if isinstance(data, dict):
            status = str(data.get("status") or "")
            message = str(data.get("message") or "")
    elif isinstance(resp, str):
        low = resp.lower()
        if "already_solved" in low:
            status = "already_solved"
        elif "correct" in low:
            status = "correct"
        elif "incorrect" in low:
            status = "incorrect"
        elif "ratelimited" in low:
            status = "ratelimited"
        message = low
    if not status:
        status = str(record.get("status") or "")
    if not message:
        message = str(record.get("message") or "")
    return status.lower(), message.lower()


def build_solved_index_from_logs(out_root):
    log_path = Path(out_root) / "submissions.jsonl"
    if not log_path.exists():
        return {}
    latest = {}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                ch_id = rec.get("challenge_id", rec.get("id"))
                try:
                    ch_id = int(ch_id)
                except Exception:
                    continue
                ts = rec.get("ts")
                try:
                    ts = float(ts) if ts is not None else 0.0
                except Exception:
                    ts = 0.0
                prev = latest.get(ch_id)
                if prev is None or ts >= float(prev.get("ts", 0.0)):
                    status, msg = _extract_submit_status(rec)
                    latest[ch_id] = {
                        "ts": ts,
                        "http_status": rec.get("http_status"),
                        "submission_status": status,
                        "message": msg,
                    }
    except Exception:
        return {}
    return latest


def load_challenges_from_status(out_root):
    status_path = out_root / "status.json"
    if not status_path.exists():
        return []
    with open(status_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    challenges = []
    for key, item in data.items():
        ch_id = item.get("id")
        if ch_id is None:
            try:
                ch_id = int(key)
            except Exception:
                continue
        ch_dir = item.get("challenge_dir", "")
        txt_path = Path(ch_dir) / "challenge.txt" if ch_dir else None
        parsed = {}
        if txt_path and txt_path.exists():
            parsed = parse_challenge_txt(txt_path)
        challenges.append(
            {
                "id": int(ch_id),
                "name": item.get("name") or parsed.get("name", ""),
                "category": item.get("category") or parsed.get("category", ""),
                "flag_format": parsed.get("flag_format", ""),
                "needs_container": bool(item.get("needs_container", parsed.get("needs_container", False))),
                "instance_url": item.get("instance_url", parsed.get("instance_url", "")),
                "connection_info": item.get("connection_info", ""),
                "attachments": item.get("attachments", parsed.get("target_or_attachments", [])),
                "challenge_dir": ch_dir,
                "description": parsed.get("description", ""),
                "provider_probes": item.get("provider_probes", []),
                "provider_probe_count": item.get("provider_probe_count", 0),
            }
        )
    return challenges


def load_status_index(out_root):
    status_path = out_root / "status.json"
    if not status_path.exists():
        return {}
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_status_index(out_root, status):
    status_path = out_root / "status.json"
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def rewrite_path_prefix(value, old_prefix: str, new_prefix: str):
    if not old_prefix or not new_prefix or old_prefix == new_prefix:
        return value
    if isinstance(value, str):
        if value == old_prefix:
            return new_prefix
        prefix = old_prefix + os.sep
        if value.startswith(prefix):
            return new_prefix + value[len(old_prefix):]
        return value
    if isinstance(value, list):
        return [rewrite_path_prefix(v, old_prefix, new_prefix) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_path_prefix(v, old_prefix, new_prefix) for k, v in value.items()}
    return value


def resolve_current_challenge_dir(out_root: Path, ch: dict, status_index: dict | None = None, event_index: dict | None = None):
    ch_id = ch.get("id")
    if ch_id is None:
        return None
    key = str(ch_id)
    status_index = status_index if isinstance(status_index, dict) else load_status_index(out_root)
    event_index = event_index if isinstance(event_index, dict) else load_event_index(out_root)
    candidates = []
    current = str(ch.get("challenge_dir", "") or "").strip()
    idx_rec = {}
    if isinstance(event_index, dict):
        idx_rec = (event_index.get("challenges") or {}).get(key, {}) or {}
        if isinstance(idx_rec, dict):
            cand = str(idx_rec.get("challenge_dir", "") or "").strip()
            if cand:
                candidates.append(cand)
    status_rec = status_index.get(key, {}) if isinstance(status_index, dict) else {}
    if isinstance(status_rec, dict):
        cand = str(status_rec.get("challenge_dir", "") or "").strip()
        if cand:
            candidates.append(cand)
    if current:
        candidates.append(current)
    seen = set()
    uniq = []
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        uniq.append(cand)
    for cand in uniq:
        if Path(cand).exists():
            return cand
    return uniq[0] if uniq else None


def reconcile_challenge_runtime_paths(out_root: Path, ch: dict, status_index: dict, event_index: dict):
    resolved_dir = resolve_current_challenge_dir(out_root, ch, status_index=status_index, event_index=event_index)
    if not resolved_dir:
        return {"ok": False, "reason": "missing_challenge_dir", "message": "challenge_dir unresolved"}
    old_dir = str(ch.get("challenge_dir", "") or "").strip()
    changed = False
    if old_dir and old_dir != resolved_dir:
        ch["attachments"] = rewrite_path_prefix(ch.get("attachments", []), old_dir, resolved_dir)
        changed = True
    ch["challenge_dir"] = resolved_dir
    ch["resolved_challenge_dir"] = resolved_dir
    status_rec = status_index.setdefault(str(ch["id"]), {})
    idx_challenges = event_index.setdefault("challenges", {})
    idx_rec = idx_challenges.setdefault(str(ch["id"]), {"id": ch.get("id")})
    idx_name = str(idx_rec.get("name", "") or "").strip()
    status_name = str(status_rec.get("name", "") or "").strip() if isinstance(status_rec, dict) else ""
    cur_name = str(ch.get("name", "") or "").strip()
    if idx_name and cur_name != idx_name:
        ch["name"] = idx_name
        changed = True
    elif status_name and not cur_name:
        ch["name"] = status_name
        changed = True

    idx_cat = str(idx_rec.get("category", "") or "").strip()
    status_cat = str(status_rec.get("category", "") or "").strip() if isinstance(status_rec, dict) else ""
    cur_cat = str(ch.get("category", "") or "").strip()
    if not cur_cat:
        if idx_cat:
            ch["category"] = idx_cat
            changed = True
        elif status_cat:
            ch["category"] = status_cat
            changed = True
    else:
        cur_spec = category_specificity(cur_cat)
        idx_spec = category_specificity(idx_cat)
        status_spec = category_specificity(status_cat)
        if idx_cat and idx_spec > cur_spec:
            ch["category"] = idx_cat
            changed = True
        elif status_cat and status_spec > category_specificity(str(ch.get("category", "") or "").strip()):
            ch["category"] = status_cat
            changed = True
    if isinstance(status_rec, dict):
        if str(status_rec.get("challenge_dir", "") or "").strip() != resolved_dir:
            status_rec["challenge_dir"] = resolved_dir
            changed = True
        for field in ("name", "category"):
            value = ch.get(field)
            if value and status_rec.get(field) != value:
                status_rec[field] = value
                changed = True
    if str(idx_rec.get("challenge_dir", "") or "").strip() != resolved_dir:
        idx_rec["challenge_dir"] = resolved_dir
        changed = True
    for field in ("name", "category"):
        value = ch.get(field)
        if value and idx_rec.get(field) != value:
            idx_rec[field] = value
            changed = True
    return {"ok": True, "resolved_dir": resolved_dir, "changed": changed, "stale_context": bool(old_dir and old_dir != resolved_dir)}


def find_flag_path(ch_dir: Path) -> str:
    for cand in (ch_dir / "flag.txt", ch_dir / "flag"):
        if cand.exists():
            try:
                if cand.read_text(encoding="utf-8", errors="ignore").strip():
                    return str(cand)
            except Exception:
                return str(cand)
    return ""


def write_solve_report(ch, session_uid, agent_name, model, run_meta, status_entry, run_start_ts, run_end_ts):
    ch_dir = Path(ch.get("challenge_dir", ""))
    if not ch_dir:
        return
    flag_path = find_flag_path(ch_dir)
    writeup_path = ch_dir / "writeup.md"
    submission_status = ""
    submit_message = ""
    if isinstance(status_entry, dict):
        submission_status = str(status_entry.get("submission_status") or status_entry.get("last_submit_status") or "")
        submit_message = str(status_entry.get("message") or status_entry.get("last_submit_message") or "")
    submit_ok = submission_status in {"correct", "already_solved"} and "incorrect" not in submission_status
    if submit_ok:
        outcome = "solved"
    elif run_meta and run_meta.get("preflight_failed"):
        outcome = "preflight_failed"
    elif flag_path:
        outcome = "flag_found_unsubmitted"
    elif run_meta and run_meta.get("timed_out"):
        outcome = "timeout"
    elif run_meta and run_meta.get("returncode") not in (None, 0):
        outcome = "session_failed"
    else:
        outcome = "unsolved"

    oracle_info = summarize_oracle_signals(ch_dir)
    artifact_info = collect_artifact_health(ch_dir)
    next_candidates = []
    next_candidates.extend(_norm_list(oracle_info.get("next_steps")))
    next_candidates.extend(_norm_list(artifact_info.get("next_steps")))

    decision_trace = []
    decision_trace.append(f"remote_gate_status={ch.get('remote_gate_status','')}")
    if ch.get("remote_gate_reason"):
        decision_trace.append(f"remote_gate_reason={ch.get('remote_gate_reason')}")
    if flag_path:
        decision_trace.append(f"flag_path={flag_path}")
    if submission_status:
        decision_trace.append(f"submission_status={submission_status}")
    if submit_message:
        decision_trace.append(f"submission_message={submit_message}")
    if run_meta and run_meta.get("timed_out"):
        decision_trace.append("session_timeout=true")
    if run_meta and run_meta.get("preflight_failed"):
        decision_trace.append("preflight_failed=true")
    if run_meta and run_meta.get("failure_reason"):
        decision_trace.append(f"failure_reason={run_meta.get('failure_reason')}")
    if run_meta and run_meta.get("message"):
        decision_trace.append(f"message={run_meta.get('message')}")
    if ch.get("resolved_challenge_dir"):
        decision_trace.append(f"resolved_challenge_dir={ch.get('resolved_challenge_dir')}")
    if ch.get("execution_profile"):
        decision_trace.append(f"execution_profile={ch.get('execution_profile')}")
    elif ch.get("subagent_profile"):
        decision_trace.append(f"subagent_profile={ch.get('subagent_profile')}")
    if run_meta and run_meta.get("returncode") not in (None, 0):
        decision_trace.append(f"session_returncode={run_meta.get('returncode')}")
    decision_trace.extend(_norm_list(oracle_info.get("decision_trace")))
    decision_trace.extend(_norm_list(artifact_info.get("decision_trace")))

    if outcome == "preflight_failed":
        failure_reason = str((run_meta or {}).get("failure_reason") or "preflight_failed")
    elif outcome == "timeout":
        failure_reason = "session_timeout"
    elif outcome == "session_failed":
        failure_reason = "session_failed"
    elif outcome == "unsolved" and submission_status and "incorrect" in submission_status:
        failure_reason = "submission_incorrect"
    elif outcome == "unsolved" and not flag_path:
        failure_reason = "no_flag_found"
    else:
        failure_reason = ""

    report = {
        "schema_version": 2,
        "challenge_id": ch.get("id"),
        "name": ch.get("name", ""),
        "category": ch.get("category", ""),
        "event": ch.get("event", ""),
        "challenge_dir": str(ch_dir),
        "session_uid": session_uid,
        "agent": agent_name,
        "execution_profile": str(ch.get("execution_profile") or ""),
        "execution_profile_prompt_path": str(ch.get("execution_profile_prompt_path") or ""),
        "subagent_profile": str(ch.get("subagent_profile") or ""),
        "subagent_prompt_path": str(ch.get("subagent_prompt_path") or ""),
        "model": model,
        "run_start_ts": run_start_ts,
        "run_end_ts": run_end_ts,
        "elapsed_sec": round(float(run_end_ts - run_start_ts), 3) if run_end_ts and run_start_ts else 0.0,
        "returncode": run_meta.get("returncode") if isinstance(run_meta, dict) else None,
        "timed_out": bool(run_meta.get("timed_out")) if isinstance(run_meta, dict) else False,
        "flag_path": flag_path,
        "writeup_path": str(writeup_path) if writeup_path.exists() else "",
        "submission_status": submission_status,
        "submission_message": submit_message,
        "outcome": outcome,
        "failure_reason": failure_reason,
        "oracle_summary": _norm_list(oracle_info.get("evidence"))[:3],
        "artifact_health": _norm_list(artifact_info.get("notes"))[:6],
        "highest_value_next_command": next_candidates[0] if next_candidates else "",
        "decision_trace": _norm_list(decision_trace),
        "updated_at": time.time(),
    }
    try:
        (ch_dir / "solve_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        return


def detect_transport_hint(ch):
    text = " ".join(
        [
            str(ch.get("connection_info", "")),
            str(ch.get("instance_url", "")),
            " ".join(str(x) for x in (ch.get("attachments") or [])),
            str(ch.get("description", "")),
        ]
    ).lower()
    if "ttyd" in text:
        return "ttyd"
    if "websocket" in text or "ws://" in text or "wss://" in text:
        return "websocket"
    if "http://" in text or "https://" in text:
        return "http"
    if "nc " in text or "socat " in text or re.search(r"[a-z0-9_.-]+:\d+", text):
        return "tcp"
    return ""


def load_jsonl_rows(path: Path, limit: int = 50):
    rows = []
    if not path.exists():
        return rows
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return rows
    for raw in lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _norm_list(values):
    out = []
    for value in values or []:
        s = str(value).strip()
        if s:
            out.append(s)
    return out


def _latest_nonzero_offset(path: Path):
    try:
        data = path.read_bytes()
    except Exception:
        return None
    for idx in range(len(data) - 1, -1, -1):
        if data[idx] != 0:
            return idx
    return None


def collect_artifact_health(ch_dir: Path):
    workspace = ch_dir / "workspace"
    candidates = []
    patterns = [
        "recovered*.jpg",
        "recovered*.jpeg",
        "recovered*.png",
        "recovered*.bin",
        "recover_*.bin",
        "decoded*.png",
        "*.decoded.png",
    ]
    seen = set()
    for pattern in patterns:
        for base in (workspace, ch_dir):
            if not base.exists():
                continue
            for cand in sorted(base.glob(pattern)):
                if cand.is_file() and cand not in seen:
                    seen.add(cand)
                    candidates.append(cand)

    artifacts = []
    evidence = []
    notes = []
    next_steps = []
    decision_trace = []
    best_partial = None

    for cand in candidates[:8]:
        try:
            size = cand.stat().st_size
        except Exception:
            continue
        last_nonzero = _latest_nonzero_offset(cand)
        zero_tail = None
        if last_nonzero is None:
            zero_tail = size
            health = f"{cand.name} size={size} all_zero=true"
        else:
            zero_tail = max(0, size - last_nonzero - 1)
            health = f"{cand.name} size={size} last_nonzero={last_nonzero} zero_tail={zero_tail}"
            if zero_tail >= max(256, size // 20):
                score = (last_nonzero, -zero_tail)
                if best_partial is None or score > best_partial[0]:
                    best_partial = (score, last_nonzero)
        artifacts.append(str(cand))
        notes.append(health)
        decision_trace.append(f"artifact_health={health}")
        if last_nonzero is not None and size > 0 and zero_tail and zero_tail >= max(256, size // 20):
            evidence.append(f"{cand.name} recovered only to byte {last_nonzero}; remaining tail still zero-filled")
            next_steps.append(f"continue recovery beyond byte {last_nonzero + 1} for {cand.name}")

    parsed_path = workspace / "parsed_submitk.json"
    solve_py = workspace / "solve.py"
    if parsed_path.exists() and solve_py.exists() and best_partial is not None:
        try:
            parsed = json.loads(parsed_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            parsed = {}
        pt_len = int(parsed.get("plaintext_len") or 0)
        if pt_len > 0:
            start_byte = best_partial[1] + 1
            start_block = (start_byte + 15) // 16
            end_block = min(start_block + 255, max(0, (pt_len + 15) // 16 - 1))
            if start_block <= end_block:
                next_steps.append(
                    f"python3 {solve_py} --step 2 --workers 12 --recover-range {start_block}:{end_block} --recover-out recover_{start_block}_{end_block}.bin"
                )
                decision_trace.append(
                    f"artifact_recovery_range={start_block}:{end_block} from_byte={start_byte} plaintext_len={pt_len}"
                )

    return {
        "artifacts": _norm_list(artifacts),
        "evidence": _norm_list(evidence),
        "notes": _norm_list(notes),
        "next_steps": _norm_list(next_steps),
        "decision_trace": _norm_list(decision_trace),
    }


def summarize_oracle_signals(ch_dir: Path):
    log_paths = [
        ch_dir / "workspace" / "logs" / "attempts.jsonl",
        ch_dir / "logs" / "attempts.jsonl",
    ]
    keywords = ("oracle", "sha256", "hash", "prefix", "cbc", "ciphertext", "plaintext", "recover")
    evidence = []
    notes = []
    next_steps = []
    decision_trace = []

    for log_path in log_paths:
        rows = load_jsonl_rows(log_path, limit=60)
        for row in reversed(rows):
            parts = []
            for key in ("hypothesis", "evidence", "result", "next", "note", "artifact"):
                parts.extend(_norm_list(row.get(key)))
            joined = " ".join(parts).lower()
            if not joined or not any(k in joined for k in keywords):
                continue
            hypothesis = _norm_list(row.get("hypothesis"))
            row_evidence = _norm_list(row.get("evidence"))
            row_next = _norm_list(row.get("next"))
            row_notes = _norm_list(row.get("note"))
            if hypothesis:
                notes.append(f"oracle_summary={hypothesis[0]}")
                decision_trace.append(f"oracle_hypothesis={hypothesis[0]}")
            if row_evidence:
                evidence.extend(row_evidence[:2])
            if row_next:
                next_steps.extend(row_next[:2])
            if row_notes:
                notes.extend(row_notes[:2])
            decision_trace.append(f"oracle_log={log_path}")
            return {
                "evidence": _norm_list(evidence),
                "notes": _norm_list(notes),
                "next_steps": _norm_list(next_steps),
                "decision_trace": _norm_list(decision_trace),
            }

    return {"evidence": [], "notes": [], "next_steps": [], "decision_trace": []}


def maybe_record_attempt(args, ch, run_meta, status_entry, run_start_ts, run_end_ts):
    ch_dir = str(ch.get("challenge_dir", "") or "").strip()
    if not ch_dir or not Path(ch_dir).exists():
        return

    submission_status = ""
    submit_message = ""
    if isinstance(status_entry, dict):
        submission_status = str(status_entry.get("submission_status") or status_entry.get("last_submit_status") or "")
        submit_message = str(status_entry.get("message") or status_entry.get("last_submit_message") or "")

    challenge_dir = Path(ch_dir)
    oracle_info = summarize_oracle_signals(challenge_dir)
    artifact_info = collect_artifact_health(challenge_dir)
    flag_path = find_flag_path(challenge_dir)
    solved = bool(flag_path) or submission_status in {"correct", "already_solved"}
    mode = "closure" if solved else "attempt"
    status = "ok" if solved else "failed"
    category_norm = canonical_category(ch.get("category", ""))
    hypothesis = [f"pipeline run for {ch.get('name','')} ({category_norm})"]
    evidence = []
    counterevidence = []
    pivot_trigger = []
    rejected = []
    tried_paths = []
    next_steps = []
    notes = []
    artifacts = []

    if ch.get("remote_gate_status"):
        notes.append(f"remote_gate_status={ch.get('remote_gate_status')}")
    if ch.get("remote_gate_reason"):
        notes.append(f"remote_gate_reason={ch.get('remote_gate_reason')}")
    if submission_status:
        evidence.append(f"submission_status={submission_status}")
    if submit_message:
        notes.append(f"submission_message={submit_message}")
    if flag_path:
        evidence.append(f"flag_path={flag_path}")

    substantive_evidence = []
    substantive_evidence.extend(_norm_list(oracle_info.get("evidence"))[:3])
    substantive_evidence.extend(_norm_list(artifact_info.get("evidence"))[:3])
    evidence.extend(substantive_evidence)
    notes.extend(_norm_list(oracle_info.get("notes"))[:3])
    notes.extend(_norm_list(artifact_info.get("notes"))[:4])
    next_steps.extend(_norm_list(oracle_info.get("next_steps"))[:2])
    next_steps.extend(_norm_list(artifact_info.get("next_steps"))[:2])
    artifacts.extend(_norm_list(artifact_info.get("artifacts"))[:4])

    message = str((run_meta or {}).get("message") or "")
    failure_reason = str((run_meta or {}).get("failure_reason") or "")
    timed_out = bool((run_meta or {}).get("timed_out"))
    returncode = (run_meta or {}).get("returncode")
    transport = detect_transport_hint(ch)

    if timed_out:
        status = "blocked"
        counterevidence.append("session timed out before closure")
        pivot_trigger.append("same branch timed out; require narrower replay or branch cut")
        next_steps.append("run session autoreview and cut repeated branch churn before another full session")
    if (run_meta or {}).get("preflight_failed"):
        status = "pivot"
        counterevidence.append(f"preflight_failed={failure_reason or 'true'}")
        pivot_trigger.append("workspace/task context invalid; repair paths before relaunch")
        next_steps.append("repair challenge_dir/task/prompt path consistency")
    if returncode not in (None, 0) and not timed_out and not (run_meta or {}).get("preflight_failed"):
        status = "failed"
        counterevidence.append(f"session returncode={returncode}")
        next_steps.append("inspect solve_report.json and session logs before retry")
    if failure_reason:
        rejected.append(f"{failure_reason}: {message or 'pipeline failure'}")
    if message:
        low = message.lower()
        if "unknown command" in low:
            status = "pivot"
            counterevidence.append(message)
            pivot_trigger.append("REPL or wrong input layer is swallowing control bytes")
            next_steps.append("switch transport/protocol instead of tuning sleeps")
        elif "no such file or directory" in low:
            status = "pivot"
            counterevidence.append(message)
            pivot_trigger.append("stale path/canonical dir mismatch")
            next_steps.append("repair canonical challenge path before another run")
        elif "bad gateway" in low:
            status = "blocked"
            counterevidence.append(message)
            pivot_trigger.append("remote upstream unstable")
            next_steps.append("re-probe remote readiness before more solve attempts")
    if submission_status == "incorrect":
        status = "failed"
        counterevidence.append("submitted candidate was incorrect")
        pivot_trigger.append("candidate quality insufficient; require stronger evidence before submit")
        next_steps.append("stop blind submission and strengthen local evidence")
    elif submission_status == "ratelimited":
        status = "blocked"
        counterevidence.append("submission rate-limited")
        next_steps.append("respect cooldown and avoid repeated low-confidence submits")

    if not substantive_evidence and not flag_path and submission_status not in {"correct", "already_solved", "incorrect", "ratelimited"}:
        notes.append("no_substantive_local_evidence_captured")

    if not solved and not next_steps:
        next_steps.append("validate top-ranked local artifacts before broadening exploration")
    if transport:
        notes.append(f"transport={transport}")
    if returncode is not None:
        notes.append(f"returncode={returncode}")
    elapsed = max(0.0, float(run_end_ts or 0.0) - float(run_start_ts or 0.0))
    notes.append(f"elapsed_sec={elapsed:.3f}")
    if ch.get("connection_info"):
        tried_paths.append(f"connection={str(ch.get('connection_info'))[:200]}")
    elif ch.get("instance_url"):
        tried_paths.append(f"instance={str(ch.get('instance_url'))[:200]}")

    prompt_hints = []
    if timed_out:
        prompt_hints.append("pipeline_timeout")
    if (run_meta or {}).get("preflight_failed"):
        prompt_hints.append("preflight_failed")
    if submission_status in {"incorrect", "ratelimited"}:
        prompt_hints.append(f"submit={submission_status}")
    if prompt_hints:
        rejected.append("pipeline_only:" + ",".join(prompt_hints))

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "core" / "ctf_evidence_log.py"),
        "--project",
        ch_dir,
        "--mode",
        mode,
        "--stage",
        "pipeline",
        "--status",
        status,
    ]
    for label, values in [
        ("--hypothesis", hypothesis[:3]),
        ("--evidence", evidence[:6]),
        ("--artifact", artifacts[:4]),
        ("--counterevidence", counterevidence[:5]),
        ("--pivot-trigger", pivot_trigger[:4]),
        ("--rejected", rejected[:4]),
        ("--tried-path", tried_paths[:4]),
        ("--next", next_steps[:4]),
        ("--note", notes[:8]),
    ]:
        for value in values:
            if str(value).strip():
                cmd += [label, str(value)]
    if transport:
        cmd += ["--transport", transport]
    confidence = 0.95 if solved else (0.25 if status in {"failed", "pivot"} else 0.4)
    cmd += ["--confidence", f"{confidence:.2f}"]
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=20)
    except Exception:
        return


def ensure_auto_writeup(ch, report):
    ch_dir = Path(ch.get("challenge_dir", ""))
    if not ch_dir:
        return
    writeup_path = ch_dir / "writeup.md"
    if writeup_path.exists():
        return
    outcome = report.get("outcome", "")
    if outcome not in {"solved", "flag_found_unsubmitted"}:
        return
    lines = []
    lines.append("# Writeup")
    lines.append("")
    lines.append("## 概述")
    lines.append(f"- 题目: {ch.get('name','')}")
    lines.append(f"- 分类: {ch.get('category','')}")
    lines.append("")
    lines.append("## 解题过程")
    lines.append("- 自动生成的简要记录（需要你补充完整过程）。")
    if report.get("flag_path"):
        lines.append(f"- flag 文件: `{report.get('flag_path')}`")
    if ch.get("target"):
        lines.append(f"- 目标: {ch.get('target')}")
    if ch.get("attachments"):
        lines.append("- 附件:")
        for a in ch.get("attachments") or []:
            lines.append(f"  - {a}")
    lines.append("")
    lines.append("## 试错与迭代")
    lines.append("- 待补充。")
    lines.append("")
    lines.append("## 要点总结")
    lines.append("- 待补充。")
    writeup_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _ensure_auto_writeup_from_report(ch):
    try:
        report_path = Path(ch.get("challenge_dir", "")) / "solve_report.json"
        if not report_path.exists():
            return
        report = json.loads(report_path.read_text(encoding="utf-8", errors="ignore"))
        ensure_auto_writeup(ch, report)
    except Exception:
        return


def maybe_auto_learn(ch, status_entry):
    ch_dir = Path(ch.get("challenge_dir", ""))
    if not ch_dir.exists():
        return
    writeup = ch_dir / "writeup.md"
    if not writeup.exists():
        return
    try:
        if writeup.read_text(encoding="utf-8", errors="ignore").strip() == "":
            return
    except Exception:
        return
    submission_status = ""
    if isinstance(status_entry, dict):
        submission_status = str(status_entry.get("submission_status") or status_entry.get("last_submit_status") or "")
    flag_path = find_flag_path(ch_dir)
    solved = bool(flag_path) or (submission_status in {"correct", "already_solved"} and "incorrect" not in submission_status)
    status = "solved" if solved else "unsolved"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "learn" / "ctf_learn.py"),
        "--project",
        str(ch_dir),
        "--status",
        status,
    ]
    if status == "unsolved":
        cmd += ["--source-writeup", str(writeup)]
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
    except Exception:
        return

def prune_missing_status_entries(status):
    pruned = {}
    removed = []
    for key, item in status.items():
        if not isinstance(item, dict):
            removed.append((key, "invalid_entry"))
            continue
        ch_dir = str(item.get("challenge_dir", "")).strip()
        if not ch_dir:
            removed.append((key, "missing_challenge_dir"))
            continue
        if not Path(ch_dir).exists():
            removed.append((key, "missing_dir"))
            continue
        pruned[key] = item
    return pruned, removed


def load_challenges_from_files(out_root):
    challenges = []
    for txt in out_root.rglob("challenge.txt"):
        parsed = parse_challenge_txt(txt)
        ch_dir = txt.parent
        ch_id = parse_id_from_dirname(ch_dir.name)
        if ch_id is None:
            continue
        challenges.append(
            {
                "id": ch_id,
                "name": parsed["name"],
                "category": parsed["category"],
                "flag_format": parsed["flag_format"],
                "needs_container": parsed["needs_container"],
                "instance_url": parsed["instance_url"],
                "connection_info": "",
                "attachments": parsed["target_or_attachments"],
                "challenge_dir": str(ch_dir),
                "description": parsed["description"],
                "provider_probes": [],
                "provider_probe_count": 0,
            }
        )
    return challenges


def looks_like_remote_target(value):
    s = str(value or "").strip()
    if not s:
        return False
    if "://" in s:
        return True
    if re.match(r"^nc\s+[A-Za-z0-9_.-]+\s+\d+$", s):
        return True
    if re.match(r"^socat\b.*\bTCP:[A-Za-z0-9_.-]+:\d+\b", s):
        return True
    if re.match(r"^[A-Za-z0-9_.-]+:\d+$", s):
        return True
    return False


def has_remote_target(ch):
    if looks_like_remote_target(ch.get("instance_url", "")):
        return True
    if looks_like_remote_target(ch.get("connection_info", "")):
        return True
    for x in ch.get("attachments", []):
        if looks_like_remote_target(x):
            return True
    return False


def probe_viable_count(ch):
    probes = ch.get("provider_probes") or []
    n = 0
    for pr in probes:
        try:
            sh = int(pr.get("start_http") or 0)
            ph = int(pr.get("poll_http") or 0)
        except Exception:
            sh, ph = 0, 0
        if sh not in (0, 404, 405) or ph not in (0, 404, 405):
            n += 1
    return n


def classify_probe_state(ch):
    if ch.get("instance_url"):
        return "ready"
    probes = ch.get("provider_probes") or []
    if not probes:
        return "start_failed"
    viable = probe_viable_count(ch) > 0
    if viable:
        return "probe_failed"
    any_start_seen = False
    for pr in probes:
        try:
            sh = int(pr.get("start_http") or 0)
        except Exception:
            sh = 0
        if sh and sh not in (404, 405):
            any_start_seen = True
            break
    return "probe_failed" if any_start_seen else "start_failed"


def evaluate_remote_readiness(ch):
    target = has_remote_target(ch)
    probe_state = classify_probe_state(ch)
    probe_ok = probe_state == "ready" or (probe_viable_count(ch) > 0)
    needs = bool(ch.get("needs_container"))
    if needs and not (target and probe_ok):
        if not target:
            return False, "no_target", "needs_container=true but no remote target detected", target, probe_ok
        return (
            False,
            probe_state,
            f"needs_container=true but probe state is {probe_state}",
            target,
            probe_ok,
        )
    if needs:
        return True, "ready", "container-ready", target, probe_ok
    if target:
        return True, "ready", "remote-target-present", target, probe_ok
    return False, "no_target", "no-remote-target", target, probe_ok


def resolve_event_dir_for_challenge(ch, out_root):
    cdir = Path(ch.get("challenge_dir", "")).resolve()
    root = Path(out_root).resolve()
    if (root / "status.json").exists():
        for p in [cdir] + list(cdir.parents):
            if (p / "status.json").exists():
                return p.resolve()
        return None
    return root if cdir.is_relative_to(root) else None


def enforce_event_dir_context(out_root, challenges, required=True):
    problems = []
    root = Path(out_root).resolve()
    for ch in challenges:
        ev = resolve_event_dir_for_challenge(ch, root)
        if ev is None:
            problems.append((ch.get("id"), "unresolved"))
            continue
        if ev != root:
            problems.append((ch.get("id"), f"mismatch:{ev}"))
    if problems and required:
        preview = ", ".join(f"id={cid}:{msg}" for cid, msg in problems[:5])
        raise RuntimeError(f"event dir context check failed ({len(problems)}): {preview}")
    return problems


def load_budget_state(out_root):
    p = Path(out_root) / "budget_state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "created_ts": time.time(), "global": {}, "challenges": {}}


def save_budget_state(out_root, state):
    p = Path(out_root) / "budget_state.json"
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def touch_budget_challenge(state, challenge_id):
    sid = str(challenge_id)
    ch = state.setdefault("challenges", {}).setdefault(
        sid,
        {
            "session_runs": 0,
            "session_timeouts": 0,
            "session_seconds": 0.0,
            "submit_attempts": 0,
            "submit_success": 0,
            "last_update_ts": 0.0,
        },
    )
    return ch


def estimate_difficulty(ch):
    cat = canonical_category(ch.get("category", ""))
    base = {
        "pwn": 1.25,
        "rev": 1.20,
        "web": 1.05,
        "crypto": 1.15,
        "forensics": 1.05,
        "osint": 0.95,
        "malware": 1.10,
        "misc": 1.0,
    }.get(cat, 1.0)
    desc = str(ch.get("description", ""))
    attach_n = len(ch.get("attachments", []) or [])
    base += min(0.35, max(0.0, attach_n - 2) * 0.03)
    if len(desc) > 1200:
        base += 0.1
    if bool(ch.get("needs_container")):
        base += 0.05
    return round(base, 3)


def select_execution_profile(ch):
    cat = canonical_category(ch.get("category", ""))
    skill_name = f"ctf-{cat}" if cat else ""
    if not skill_name or cat == "unknown":
        return {"profile": "", "prompt_text": "", "prompt_path": ""}
    risk = str(ch.get("interactive_risk", "none") or "none").lower()
    prior_hist = ch.get("prior_same_challenge_history") or []
    watch = ch.get("failure_watchlist") or []
    if risk in {"moderate", "high"} or prior_hist or watch:
        profile = "deep"
    elif (
        risk == "none"
        and not ch.get("has_remote_target")
        and not bool(ch.get("needs_container"))
        and len(ch.get("attachments", []) or []) <= 1
        and len(str(ch.get("description", "") or "")) <= 240
    ):
        profile = "fast"
    else:
        profile = "standard"
    prompt_path = repo_root() / ".opencode" / "skills" / skill_name / "agents" / "prompts" / f"{profile}.txt"
    prompt_text = ""
    try:
        if prompt_path.exists():
            prompt_text = prompt_path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        prompt_text = ""
    legacy_map = {"fast": "easy", "standard": "medium", "deep": "hard"}
    if not prompt_text:
        fallback_name = legacy_map.get(profile, "")
        if fallback_name:
            fallback_path = repo_root() / ".opencode" / "skills" / skill_name / "agents" / "prompts" / f"{fallback_name}.txt"
            try:
                if fallback_path.exists():
                    prompt_text = fallback_path.read_text(encoding="utf-8", errors="ignore").strip()
                    prompt_path = fallback_path
            except Exception:
                prompt_text = ""
    return {
        "profile": profile if prompt_text else "",
        "prompt_text": prompt_text,
        "prompt_path": str(prompt_path) if prompt_text else "",
    }


def auto_timeout_sec(ch, *, cap_sec: int | None = None) -> int:
    cat = canonical_category(ch.get("category", ""))
    base = {
        "web": 900,
        "misc": 900,
        "forensics": 900,
        "osint": 600,
        "crypto": 1200,
        "rev": 1200,
        "malware": 1200,
        "pwn": 1500,
    }.get(cat, 900)
    diff = estimate_difficulty(ch)
    t = int(base * max(0.8, diff))
    risk = str(ch.get("interactive_risk", "none")).lower()
    if risk == "high":
        t = int(t * 0.7)
    elif risk == "moderate":
        t = int(t * 0.85)
    t = max(300, min(t, 2400))
    if cap_sec and cap_sec > 0:
        t = min(t, int(cap_sec))
    return t


def priority_key(ch):
    cat = canonical_category(ch.get("category", ""))
    cat_rank = {
        "web": 0,
        "osint": 1,
        "forensics": 2,
        "misc": 3,
        "crypto": 4,
        "rev": 5,
        "malware": 6,
        "pwn": 7,
    }.get(cat, 8)
    diff = estimate_difficulty(ch)
    rec_hits = len(ch.get("memory_recommendations") or [])
    fail_hits = len(ch.get("failure_watchlist") or [])
    risk = {"none": 0, "moderate": 1, "high": 2}.get(ch.get("interactive_risk", "none"), 0)
    remote_penalty = 1 if (not ch.get("remote_ready") and has_remote_target(ch)) else 0
    return (
        cat_rank,
        remote_penalty,
        risk,
        -rec_hits,
        fail_hits,
        diff,
        ch.get("id", 0),
    )


def build_prompt(ch):
    prompt_input = dict(ch)
    prompt_input["work_root"] = str(pick_challenge_workspace(ch["challenge_dir"]))
    return compose_pipeline_prompt(
        category=canonical_category(ch.get("category", "")),
        challenge_prompt=render_prompt(prompt_input),
    )


def write_task_files(ch, *, precompute_images=True, image_guard_timeout_sec: int = 45, image_ocr_timeout_sec: int = 90):
    ch_dir = Path(ch["challenge_dir"])
    ch_dir.mkdir(parents=True, exist_ok=True)
    pick_challenge_workspace(ch_dir).mkdir(parents=True, exist_ok=True)
    execution = select_execution_profile(ch)
    ch["execution_profile"] = str(execution.get("profile") or "")
    ch["execution_profile_prompt_path"] = str(execution.get("prompt_path") or "")
    ch["execution_profile_prompt_text"] = str(execution.get("prompt_text") or "")
    ch["subagent_profile"] = str(ch.get("execution_profile") or "")
    ch["subagent_prompt_path"] = str(ch.get("execution_profile_prompt_path") or "")
    ch["subagent_prompt_text"] = str(ch.get("execution_profile_prompt_text") or "")
    if precompute_images:
        ch["image_guard"] = guard_images_for_attachments(ch, timeout_sec=image_guard_timeout_sec)
        ch["image_ocr_hits"] = scan_images_for_challenge(ch, timeout_sec=image_ocr_timeout_sec)
    else:
        ch.setdefault("image_guard", [])
        ch.setdefault("image_ocr_hits", [])
    ckey_name, ckey_cat = challenge_key(ch.get("name", ""), ch.get("category", ""))
    event_key = Path(ch_dir).resolve().parents[1].name if len(Path(ch_dir).resolve().parents) >= 2 else ""
    challenge_key_str = f"{ckey_cat}/{ckey_name}" if ckey_name else ""
    task = build_task_payload(ch, event_key=event_key, challenge_key=challenge_key_str)
    prompt = build_prompt(ch)
    task_path = ch_dir / "task.json"
    prompt_path = ch_dir / "web_prompt.txt"
    context_path = ch_dir / "challenge_context.json"
    env_json_path = ch_dir / "pipeline_env.json"
    env_sh_path = ch_dir / "pipeline_env.sh"
    pipeline_env = {
        "CTF_PIPELINE_MODE": "1",
        "CTFD_CHALLENGE_ID": str(ch.get("id", "")),
        "CTFD_CHALLENGE_DIR": str(ch_dir),
        "CTFD_CHALLENGE_DIR_RESOLVED": str(ch.get("resolved_challenge_dir", ch_dir)),
        "CTF_EVENT_DIR": str(ch_dir.resolve().parents[1]) if len(ch_dir.resolve().parents) >= 2 else "",
        "CTF_REMOTE_READY": "1" if ch.get("remote_ready") else "0",
        "CTF_REMOTE_GATE_REASON": str(ch.get("remote_gate_reason", "")),
    }
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(
            build_context_payload(
                ch,
                ch_dir=ch_dir,
                event_key=event_key,
                case_state=safe_case_state(ch_dir, ch.get("category", "")),
            ),
            f,
            ensure_ascii=False,
            indent=2,
        )
    with open(env_json_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_env, f, ensure_ascii=False, indent=2)
    with open(env_sh_path, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\n")
        for key in sorted(pipeline_env.keys()):
            value = str(pipeline_env[key]).replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'export {key}="{value}"\n')
    return str(task_path), str(prompt_path), str(context_path), str(env_json_path), str(env_sh_path)


def maybe_start_container(args, ch):
    if not args.start_containers:
        return
    if ch.get("instance_url"):
        return
    if not args.base:
        return
    cmd = ["python3", str(Path(__file__).resolve().parent / "start_container.py"), "--base", args.base, "--id", str(ch["id"]), "--out-root", str(args.out_root)]
    if args.session:
        cmd += ["--session", args.session]
    if args.token:
        cmd += ["--token", args.token]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"[warn] start_container timed out id={ch['id']} timeout=60s", file=sys.stderr)
        return
    if result.returncode != 0:
        print(f"[warn] start_container failed id={ch['id']} rc={result.returncode}", file=sys.stderr)
        return
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        ch["instance_url"] = payload.get("instance_url", "")
        ch["provider_probes"] = payload.get("provider_probes") or []
        ch["provider_probe_count"] = int(payload.get("provider_probe_count") or 0)
        # Do not rely only on needs_container. If probe shows no viable endpoint and
        # no instance URL, treat it as "no container available" for this challenge.
        if not ch["instance_url"]:
            probes = payload.get("provider_probes") or []
            viable = 0
            for pr in probes:
                sh = int(pr.get("start_http") or 0)
                ph = int(pr.get("poll_http") or 0)
                if sh not in (0, 404, 405) or ph not in (0, 404, 405):
                    viable += 1
            if ch.get("needs_container") and viable == 0:
                print(
                    f"[warn] id={ch['id']} marked needs_container=true but no container endpoint detected",
                    file=sys.stderr,
                )
    except Exception:
        pass


def should_use_attach_for_pipeline(session_timeout: int | None) -> bool:
    mode = str(os.getenv("OPENCODE_PIPELINE_ATTACH_MODE", "auto") or "auto").strip().lower()
    if mode in {"off", "0", "false", "no"}:
        return False
    if mode in {"on", "1", "true", "yes", "force"}:
        return True
    return not (session_timeout and session_timeout > 0)


def precompute_timeout_budget(session_timeout: int | None) -> tuple[int, int]:
    if not session_timeout or session_timeout <= 0:
        return (45, 90)
    base = max(3, int(session_timeout))
    guard_sec = max(3, min(15, base // 2 if base >= 8 else 3))
    ocr_sec = max(4, min(20, base))
    return (guard_sec, ocr_sec)


def kill_process_group(proc: subprocess.Popen, *, grace_sec: float = 1.5) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = None
    if pgid:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        end = time.time() + max(0.1, grace_sec)
        while time.time() < end:
            if proc.poll() is not None:
                return
            time.sleep(0.1)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass
    else:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace_sec)
            return
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=1.0)
    except Exception:
        pass


def cleanup_matching_opencode_runs(*, title: str, file_markers: list[str], exclude_pid: int | None = None) -> list[int]:
    title = str(title or "").strip()
    markers = [str(x).strip() for x in file_markers if str(x).strip()]
    if not title:
        return []
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    killed = []
    for raw in (out.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            pid_str, cmdline = line.split(None, 1)
            pid = int(pid_str)
        except Exception:
            continue
        if exclude_pid and pid == int(exclude_pid):
            continue
        if "opencode" not in cmdline or " run " not in cmdline:
            continue
        if title not in cmdline:
            continue
        if markers and not any(marker in cmdline for marker in markers):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except Exception:
            continue
    return killed


def launch_session(args, ch, task_path, prompt_path, context_path, env_json_path, env_sh_path):
    title = build_session_title(args.competition, ch.get("category", ""), ch.get("name", ""))
    if args.agent in {"", "auto"}:
        requested_agent = str(ch.get("recommended_agent") or "ctf-main")
    else:
        requested_agent = str(args.agent)
    agent_name = resolve_agent_name(requested_agent) or "ctf"
    if requested_agent != agent_name:
        print(f"[warn] agent '{requested_agent}' mapped to '{agent_name}'")
    # Run sessions from repo root so relative paths like ./scripts/... and ./workspace/... work.
    session_dir = str(repo_root())
    session_timeout = None
    if args.auto_timeout:
        session_timeout = auto_timeout_sec(ch, cap_sec=args.per_task_timeout_sec)
    elif args.per_task_timeout_sec and args.per_task_timeout_sec > 0:
        session_timeout = args.per_task_timeout_sec
    use_attach = False
    attach_url = resolve_opencode_attach_url()
    if should_use_attach_for_pipeline(session_timeout) and should_attach_opencode_server(attach_url):
        use_attach = True
    elif should_attach_opencode_server(attach_url) and session_timeout and session_timeout > 0:
        print(
            f"[info] skip --attach for challenge {ch['id']} because bounded timeout requires hard process cleanup",
            file=sys.stderr,
        )
    cmd = [
        "opencode",
        "run",
        "--title",
        title,
        "--agent",
        agent_name,
        "--dir",
        session_dir,
        "--file",
        prompt_path,
        "--file",
        task_path,
        "--file",
        context_path,
        "--file",
        env_json_path,
        "--file",
        env_sh_path,
    ]
    resume_session_id = str(ch.get("_resume_opencode_session_id") or "").strip()
    if resume_session_id:
        cmd += ["--session", resume_session_id]
    if use_attach:
        cmd += ["--attach", attach_url]
    effective_model = str(getattr(args, "model", "") or "").strip() or default_agent_model()
    if getattr(args, "first_blood_mode", False):
        effective_model = default_first_blood_model() or effective_model
    if effective_model:
        cmd += ["--model", effective_model]
    session_message = build_session_message(ch, resume_session_id=resume_session_id)
    cmd.append(session_message)
    print(f"[session] {title}")
    if args.dry_run:
        print("  " + " ".join(cmd))
        return
    required_paths = {
        "task_path": task_path,
        "prompt_path": prompt_path,
        "context_path": context_path,
        "env_json_path": env_json_path,
        "env_sh_path": env_sh_path,
    }
    if not all(Path(p).exists() for p in required_paths.values()):
        missing = []
        for key, value in required_paths.items():
            if not Path(value).exists():
                missing.append(f"{key}={value}")
        msg = ", ".join(missing) if missing else "session input missing"
        print(f"[warn] preflight failed for challenge {ch['id']}: {msg}", file=sys.stderr)
        return {"timed_out": False, "returncode": 97, "preflight_failed": True, "failure_reason": "stale_context", "message": msg}
    env = os.environ.copy()
    env["CTF_PIPELINE_MODE"] = "1"
    env["CTFD_CHALLENGE_ID"] = str(ch.get("id", ""))
    env["CTFD_CHALLENGE_DIR"] = str(ch.get("challenge_dir", ""))
    env["CTFD_CHALLENGE_DIR_RESOLVED"] = str(ch.get("resolved_challenge_dir", ch.get("challenge_dir", "")))
    env["CTFD_BASE_URL"] = str(args.base or "")
    env["CTFD_SESSION"] = str(args.session or "")
    env["CTFD_TOKEN"] = str(args.token or "")
    env["CTFD_MIN_INTERVAL"] = str(args.min_interval)
    env["CTFD_SUBMIT_LOG"] = str(args.out_root / "submissions.jsonl")
    env["CTF_BUDGET_STATE"] = str(args.out_root / "budget_state.json")
    env["CTF_EVENT_DIR"] = str(args.out_root)
    env["CTF_REMOTE_READY"] = "1" if ch.get("remote_ready") else "0"
    env["CTF_REMOTE_GATE_REASON"] = str(ch.get("remote_gate_reason", ""))
    env["OPENCODE_ENABLE_EXA"] = "1"
    env["OPENCODE_EXPERIMENTAL_LSP_TOOL"] = "true"
    env["OPENCODE_CONFIG"] = str(default_opencode_config_path())
    env["CTFD_MIN_CANDIDATE_SCORE"] = str(args.min_candidate_score)
    env["CTFD_ALLOW_UNSCORED_SUBMIT"] = "1" if args.allow_unscored_submit else "0"
    env["CTFD_MAX_INCORRECT_PER_CHALLENGE"] = str(args.max_incorrect_per_challenge)
    env["CTFD_SUBMIT_COOLDOWN_SEC"] = str(args.submit_cooldown_sec)
    env["CTF_PIPELINE_DISABLE_SUBMIT"] = "1" if submissions_disabled_for_challenge(args, ch) else "0"
    watch_proc = None
    watch_log = None
    if args.image_watch:
        watch_script = Path(__file__).resolve().parents[1] / "core" / "ctf_image_watch.py"
        roots = [Path(ch.get("challenge_dir", "")).resolve(), pick_challenge_workspace(ch.get("challenge_dir", "")).resolve()]
        roots = [r for r in roots if r.exists()]
        if watch_script.exists() and roots:
            watch_dir = roots[0] / "artifacts" / "image_guard"
            watch_dir.mkdir(parents=True, exist_ok=True)
            watch_log = open(watch_dir / "image_watch.log", "a", encoding="utf-8")
            watch_cmd = ["python3", str(watch_script), "--interval-sec", str(args.image_watch_interval_sec), "--max-per-scan", str(args.image_watch_max_per_scan)]
            for r in roots:
                watch_cmd += ["--root", str(r)]
            try:
                watch_proc = subprocess.Popen(watch_cmd, stdout=watch_log, stderr=watch_log)
            except Exception:
                watch_proc = None
    title_query = title
    dir_query = session_dir
    process_markers = [task_path, prompt_path, context_path, env_json_path, env_sh_path]
    def strip_attach(run_cmd):
        out = []
        i = 0
        while i < len(run_cmd):
            if run_cmd[i] == "--attach":
                i += 2
                continue
            out.append(run_cmd[i])
            i += 1
        return out

    def run_once(run_cmd):
        pre_launch_ms = int(time.time() * 1000)
        captured_sid = resume_session_id or ""
        try:
            if not resume_session_id:
                stale = cleanup_matching_opencode_runs(title=title_query, file_markers=process_markers)
                if stale:
                    print(
                        f"[info] cleaned stale opencode run(s) for challenge {ch['id']}: {','.join(str(x) for x in stale)}",
                        file=sys.stderr,
                    )
            proc = subprocess.Popen(run_cmd, env=env, start_new_session=True)
            while True:
                rc = proc.poll()
                if not captured_sid:
                    hit = find_opencode_session_record(
                        title=title_query,
                        directory=dir_query,
                        created_after_ms=(pre_launch_ms - 15000),
                    )
                    if hit:
                        captured_sid = str(hit.get("id") or "")
                if rc is not None:
                    break
                time.sleep(2.0)
                if session_timeout and (time.time() * 1000 - pre_launch_ms) > (session_timeout * 1000):
                    kill_process_group(proc)
                    if use_attach:
                        stale = cleanup_matching_opencode_runs(
                            title=title_query,
                            file_markers=process_markers,
                            exclude_pid=proc.pid,
                        )
                        if stale:
                            print(
                                f"[info] cleaned attach-backed stale run(s) after timeout for challenge {ch['id']}: {','.join(str(x) for x in stale)}",
                                file=sys.stderr,
                            )
                    raise subprocess.TimeoutExpired(cmd=run_cmd, timeout=session_timeout)
        except subprocess.TimeoutExpired:
            print(
                f"[warn] opencode run timed out for challenge {ch['id']} timeout={session_timeout}s",
                file=sys.stderr,
            )
            return {"timed_out": True, "returncode": 124, "opencode_session_id": captured_sid}
        if not captured_sid:
            hit = find_opencode_session_record(
                title=title_query,
                directory=dir_query,
                created_after_ms=(pre_launch_ms - 15000),
            )
            if hit:
                captured_sid = str(hit.get("id") or "")
        message = ""
        failure_reason = ""
        if proc.returncode != 0:
            print(f"[warn] opencode run failed for challenge {ch['id']} rc={proc.returncode}", file=sys.stderr)
            message = f"opencode_exit_rc={proc.returncode}"
            failure_reason = "opencode_start_failed" if not captured_sid else "session_failed"
        return {
            "timed_out": False,
            "returncode": proc.returncode,
            "opencode_session_id": captured_sid,
            "message": message,
            "failure_reason": failure_reason,
        }

    used_attach = "--attach" in cmd
    primary_meta = run_once(cmd)
    if (
        used_attach
        and not primary_meta.get("timed_out")
        and primary_meta.get("returncode") not in (None, 0)
        and not str(primary_meta.get("opencode_session_id") or "").strip()
    ):
        print(
            f"[warn] attach-backed opencode run failed before session bind for challenge {ch['id']}; retrying without --attach",
            file=sys.stderr,
        )
        time.sleep(2.0)
        retry_meta = run_once(strip_attach(cmd))
        retry_meta["retried_without_attach"] = True
        if retry_meta.get("returncode") in (None, 0) or retry_meta.get("opencode_session_id"):
            primary_meta = retry_meta
        else:
            retry_msg = str(retry_meta.get("message") or "").strip()
            primary_meta["message"] = (
                f"{primary_meta.get('message') or 'opencode attach launch failed'}; "
                f"retry_without_attach_failed={retry_msg or retry_meta.get('returncode')}"
            )

    if watch_proc:
        watch_proc.terminate()
        try:
            watch_proc.wait(timeout=2)
        except Exception:
            pass
    if watch_log:
        watch_log.close()
    return primary_meta


def safe_case_state(ch_dir: Path, category: str) -> dict:
    try:
        return build_case_state(ch_dir.resolve(), category=canonical_category(category))
    except Exception:
        return {}


def build_session_message(ch: dict, *, resume_session_id: str = "") -> str:
    ch_dir = Path(ch.get("challenge_dir", "")).resolve()
    case_state = safe_case_state(ch_dir, ch.get("category", ""))
    solve_report = load_challenge_solve_report(ch_dir)
    recent_attempts = load_recent_attempts(ch_dir, limit=5)
    search_friendly = canonical_category(ch.get("category", "")) in {"osint", "crypto", "forensics", "misc", "malware"}
    return compose_session_message(
        ch=ch,
        ch_dir=ch_dir,
        case_state=case_state,
        solve_report=solve_report,
        recent_attempts=recent_attempts,
        search_friendly=search_friendly,
        canonical_category_func=canonical_category,
        resume_session_id=resume_session_id,
    )


def resolve_opencode_session_for_active_record(ch, dup: dict, competition: str = "") -> str:
    recorded_title = str(dup.get("title") or "").strip()
    current_title = build_session_title(
        competition or ch.get("event", ""),
        ch.get("category", ""),
        ch.get("name", ""),
    )
    return adapter_resolve_opencode_session_for_active_record(
        dup,
        title_candidates=[recorded_title, current_title],
        directory=str(repo_root()),
    )


def resolve_resumable_session_for_challenge(args, ch, status_item: dict | None = None) -> str:
    if is_solved(ch, status_item or {}):
        return ""
    if not bool(getattr(args, "resume_incomplete_sessions", True)):
        return ""
    dup = lifecycle_should_skip_for_duplicate_session(
        allow_duplicate_sessions=getattr(args, "allow_duplicate_sessions", False),
        duplicate_session_ttl_sec=float(getattr(args, "duplicate_session_ttl_sec", 0) or 0),
        out_root=args.out_root,
        sessions_file=SESSIONS_FILE,
        challenge_id=int(ch["id"]),
        find_duplicate_active_session_func=find_duplicate_active_session_store,
    )
    if dup is not None:
        sid = resolve_opencode_session_for_active_record(ch, dup, args.competition)
        if sid:
            return sid
    latest_sid = find_latest_recorded_session_id_store(args.out_root, SESSIONS_FILE, int(ch["id"]))
    return latest_sid


def is_solved(ch, status_item):
    if isinstance(status_item, dict):
        if status_item.get("submission_status") in {"correct", "already_solved"}:
            return True
        if status_item.get("solved") is True:
            return True
        if status_item.get("solved_by_me") is True:
            return True
    return False


def read_flag_from_file(ch):
    existing = find_local_flag_files(ch)
    if not existing:
        return "", []

    existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in existing:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if content:
            return content, [str(p) for p in existing]
    return "", [str(p) for p in existing]


def build_flag_regex(flag_format):
    if not flag_format:
        return None
    s = flag_format.strip().replace("`", "")
    m = re.search(r"([A-Za-z0-9_]+)\{[^}]*\}", s)
    if m:
        prefix = m.group(1)
        return rf"{re.escape(prefix)}\{{.+\}}"
    return None


def passes_flag_gate(ch, flag):
    pattern = build_flag_regex(ch.get("flag_format", ""))
    if not pattern:
        return True
    if not re.fullmatch(pattern, flag):
        return False
    cmd = [
        "python3",
        str(Path(__file__).resolve().parents[1] / "core" / "flag_validate.py"),
        "--pattern",
        pattern,
        "--candidate",
        flag,
    ]
    try:
        res = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return False
    return res.returncode == 0


def find_solver_script(ch):
    ch_dir = Path(ch.get("challenge_dir", ""))
    direct = ch_dir / "solve.py"
    if direct.exists() and direct.is_file():
        return direct
    all_candidates = []
    for work_root in challenge_workspace_dirs(ch_dir):
        if work_root.exists():
            all_candidates.extend([p for p in work_root.rglob("solve.py") if p.is_file()])
    candidates = sorted(
        all_candidates,
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return None


def replay_verify_before_submit(ch, flag, timeout_sec=180):
    solver = find_solver_script(ch)
    if solver is None:
        return False, "solve.py not found"
    try:
        proc = subprocess.run(
            ["python3", str(solver)],
            cwd=str(solver.parent),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False, f"solve.py timeout>{timeout_sec}s"
    merged = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return False, f"solve.py rc={proc.returncode}"
    if flag and flag not in merged:
        return False, "solve.py output does not contain candidate flag"
    return True, "replay-ok"


def auto_submit_if_requested(args, ch, status, status_lock=None, budget_state=None):
    if not args.auto_submit:
        return
    if submissions_disabled_for_challenge(args, ch):
        print(f"[submit] skip id={ch['id']} (submission disabled for regression/local-only run)")
        return
    if bool(ch.get("needs_container")) and not bool(ch.get("remote_ready")):
        print(
            f"[submit] skip id={ch['id']} (needs_container but remote not ready: {ch.get('remote_gate_status','unknown')})"
        )
        return
    flag, checked_paths = read_flag_from_file(ch)
    if not flag:
        root = Path(ch["challenge_dir"])
        default_hint = [
            str(root / "flag.txt"),
            str(root / "flag"),
            str(root / "workspace" / "*" / "flag.txt"),
            str(root / "ctf-work" / "*" / "flag.txt"),
        ]
        if checked_paths:
            print(f"[submit] skip id={ch['id']} (flag file empty): {checked_paths[0]}")
        else:
            print(f"[submit] skip id={ch['id']} (no flag file, expected one of: {default_hint})")
        return
    if not passes_flag_gate(ch, flag):
        print(f"[submit] skip id={ch['id']} (flag gate failed)")
        return
    if args.require_replay:
        ok, reason = replay_verify_before_submit(ch, flag, timeout_sec=args.replay_timeout_sec)
        if not ok:
            print(f"[submit] skip id={ch['id']} (replay failed: {reason})")
            return
    cmd = [
        "python3",
        str(Path(__file__).resolve().parent / "submit_flag.py"),
        "--base",
        args.base,
        "--id",
        str(ch["id"]),
        "--flag",
        flag,
        "--min-interval",
        str(args.min_interval),
        "--log",
        str(args.out_root / "submissions.jsonl"),
        "--event-dir",
        str(args.out_root),
    ]
    if args.session:
        cmd += ["--session", args.session]
    if args.token:
        cmd += ["--token", args.token]
    if args.dry_run:
        print("[submit] " + " ".join(cmd))
        return
    if budget_state is not None:
        st = touch_budget_challenge(budget_state, ch["id"])
        st["submit_attempts"] = int(st.get("submit_attempts", 0)) + 1
        st["last_update_ts"] = time.time()
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"[warn] submit timed out id={ch['id']} timeout=60s", file=sys.stderr)
        return
    if result.returncode != 0:
        print(f"[warn] submit failed id={ch['id']} rc={result.returncode}", file=sys.stderr)
        return
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    try:
        payload = json.loads(line)
    except Exception:
        payload = {"raw": line}
    if status_lock is None:
        status_lock = threading.Lock()
    with status_lock:
        entry = status.setdefault(str(ch["id"]), {})
        entry["last_submit_ts"] = time.time()
        entry["last_submit_http"] = payload.get("http_status")
        response = payload.get("response") if isinstance(payload, dict) else None
        if isinstance(response, dict):
            # CTFd attempt API commonly returns response.data.status
            data = response.get("data") or {}
            submission_status = data.get("status")
            msg = str(data.get("message", "")).lower()
            entry["submission_status"] = submission_status
            submit_ok = submission_status == "correct" or (submission_status == "already_solved" and "incorrect" not in msg)
            if submit_ok:
                entry["solved"] = True
                if budget_state is not None:
                    st = touch_budget_challenge(budget_state, ch["id"])
                    st["submit_success"] = int(st.get("submit_success", 0)) + 1
                    st["last_update_ts"] = time.time()
        save_status_index(args.out_root, status)


def apply_backfill_from_work(backfill_root, challenges, status, out_root):
    root = Path(backfill_root).resolve()
    if not root.exists():
        raise RuntimeError(f"backfill root not found: {root}")

    challenge_map = {}
    for ch in challenges:
        key = challenge_key(ch.get("name", ""), ch.get("category", ""))
        if key[0]:
            challenge_map.setdefault(key, []).append(ch)

    best = {}
    for item in root.iterdir():
        if not item.is_dir():
            continue
        meta_candidates = [item / "challenge.json", item / "attachments" / "challenge.json", item / "题目附件" / "challenge.json"]
        meta = next((m for m in meta_candidates if m.exists() and m.is_file()), None)
        flag_paths = [item / "flag.txt", item / "flag"]
        flag_paths = [p for p in flag_paths if p.exists() and p.is_file()]
        if meta is None or not flag_paths:
            continue
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = payload.get("title", "")
        category = payload.get("category", "")
        key = challenge_key(title, category)
        if not key[0]:
            continue
        flag_path = max(flag_paths, key=lambda p: p.stat().st_mtime)
        candidate = {
            "dir": item,
            "flag_path": flag_path,
            "mtime": flag_path.stat().st_mtime,
            "title": title,
            "category": category,
        }
        old = best.get(key)
        if old is None or candidate["mtime"] > old["mtime"]:
            best[key] = candidate

    updated = 0
    unmatched = 0
    for key, cand in best.items():
        targets = challenge_map.get(key, [])
        if not targets:
            unmatched += 1
            continue
        if len(targets) > 1:
            unmatched += 1
            continue
        ch = targets[0]
        ch_dir = Path(ch.get("challenge_dir", ""))
        if not ch_dir.exists():
            ch_dir.mkdir(parents=True, exist_ok=True)
        dst = ch_dir / "flag.txt"
        try:
            content = cand["flag_path"].read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            continue
        if not content:
            continue
        if dst.exists():
            try:
                old = dst.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                old = ""
            if old == content:
                pass
            else:
                dst.write_text(content + "\n", encoding="utf-8")
        else:
            dst.write_text(content + "\n", encoding="utf-8")

        sid = str(ch["id"])
        entry = status.setdefault(sid, {})
        entry["local_flag_found"] = True
        entry["local_flag_path"] = str(dst)
        entry["local_flag_ts"] = time.time()
        challenge_txt = ch_dir / "challenge.txt"
        if not challenge_txt.exists():
            challenge_txt.write_text(
                "\n".join(
                    [
                        f"题目名称: {ch.get('name','')}",
                        f"类别: {ch.get('category','')}",
                        f"Flag 格式: {ch.get('flag_format','')}",
                        "需要启动容器: 否",
                        "描述:",
                        ch.get("description", ""),
                        "目标地址或附件:",
                    ]
                ).strip()
                + "\n",
                encoding="utf-8",
            )
        updated += 1

    save_status_index(out_root, status)
    print(f"[backfill] scanned={len(best)} updated={updated} unmatched={unmatched}")


def filtered(challenges, args):
    selected = []
    include_ids = set(args.id or [])
    include_ids |= parse_int_set(args.select)
    categories = parse_category_set(args.category)
    include_all_categories = (not categories) or ("all" in categories)
    missing_challenge_dir = []
    missing_dir = []
    for ch in challenges:
        ch_dir = str(ch.get("challenge_dir", "")).strip()
        if not ch_dir:
            missing_challenge_dir.append(ch.get("id"))
            continue
        if not Path(ch_dir).exists():
            missing_dir.append(ch.get("id"))
            continue
        if include_ids and ch["id"] not in include_ids:
            continue
        if (not include_all_categories) and (canonical_category(ch.get("category", "")) not in categories):
            continue
        selected.append(ch)
    if missing_challenge_dir:
        print(f"[warn] skipped {len(missing_challenge_dir)} entries with missing challenge_dir (use --prune-missing)")
    if missing_dir:
        print(f"[warn] skipped {len(missing_dir)} entries with missing directories (use --prune-missing)")
    return sorted(selected, key=lambda x: (x.get("category", ""), x["id"]))


def interactive_pick(challenges):
    if not challenges:
        return []
    print("[pick] available challenges:")
    for ch in challenges:
        print(f"  {ch['id']:>3} | {ch.get('category','')} | {ch.get('name','')}")
    raw = input("[pick] enter IDs (e.g. 1,3,5-8), empty=all: ").strip()
    picked = parse_int_set(raw)
    if not picked:
        return challenges
    return [ch for ch in challenges if ch["id"] in picked]


def apply_mode_defaults(args):
    mode = str(getattr(args, "mode", "match") or "match").strip().lower()
    if mode == "submit-only":
        args.submit_only = True
        args.auto_submit = True
        if int(args.workers or 1) < 1:
            args.workers = 1
    elif mode == "maint":
        # Maintenance mode should avoid surprising session launches unless the
        # caller explicitly enables normal match behavior.
        if not any(
            [
                bool(args.prune_missing),
                bool(args.backfill_from_work),
                bool(args.pull_submissions),
                bool(args.submit_only),
            ]
        ):
            args.submit_only = True
            args.auto_submit = True
    else:
        mode = "match"
    args.mode = mode


def apply_auto_run_defaults(args):
    if not bool(getattr(args, "auto_run", False)):
        return
    args.mode = "match"
    args.only_unsolved = True
    args.auto_submit = True
    args.submit_only = False
    args.auto_timeout = True
    args.pull_challenge_status = "on"
    args.pull_submissions = True
    if int(args.workers or 0) <= 1:
        args.workers = 4
    if int(args.max_active_remote or 0) <= 0:
        args.max_active_remote = 2
    if int(args.per_task_timeout_sec or 0) <= 0 or int(args.per_task_timeout_sec) == 1800:
        args.per_task_timeout_sec = 1800
    if int(args.rounds or 0) == 1:
        # 0 means "continuous rounds until exhausted/solved".
        args.rounds = 0
    if int(args.global_time_budget_min or 0) <= 0:
        args.global_time_budget_min = 480


def main():
    ap = argparse.ArgumentParser(
        description="CTFd -> opencode session pipeline",
        epilog=(
            "Recommended minimal usage:\n"
            "  Match mode:\n"
            "    python3 scripts/ctfd/ctfd_pipeline.py --out-root events/<event> --competition <event> --mode match --only-unsolved --auto-submit --workers 4 --max-active-remote 2 --auto-timeout\n\n"
            "  Submit-only mode:\n"
            "    python3 scripts/ctfd/ctfd_pipeline.py --out-root events/<event> --competition <event> --mode submit-only --only-unsolved\n\n"
            "  Maintenance mode:\n"
            "    python3 scripts/ctfd/ctfd_pipeline.py --out-root events/<event> --competition <event> --mode maint --prune-missing\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    common = ap.add_argument_group("Common Match Flags")
    selection = ap.add_argument_group("Challenge Selection")
    advanced = ap.add_argument_group("Advanced / Maintenance Flags")

    common.add_argument("--out-root", required=True, help="Challenge export root, e.g. ./events/axiom2026")
    common.add_argument("--competition", required=True, help="Competition name used in session title")
    common.add_argument(
        "--auto-run",
        action="store_true",
        help="competition autopilot: keep retrying unresolved challenges with sensible defaults until solved or budget exhausted",
    )
    common.add_argument(
        "--mode",
        choices=["match", "submit-only", "maint"],
        default="match",
        help="match=normal competition flow; submit-only=scan local flags and submit; maint=repair/sync/backfill-oriented run",
    )
    common.add_argument("--env-file", help="Custom .env path; default: <out-root>/.env")
    common.add_argument("--only-unsolved", action="store_true", help="skip solved challenges (status.json submission status)")
    common.add_argument("--auto-submit", action="store_true", help="auto submit using flag.txt after session step")
    common.add_argument("--submit-only", action="store_true", help="only scan flag files and submit; do not launch opencode sessions")
    common.add_argument("--workers", type=int, default=1, help="parallel worker count for multi-challenge pipeline runs")
    common.add_argument("--rounds", type=int, default=1, help="repeat unresolved challenges for N rounds (default: 1)")
    common.add_argument("--max-active-remote", type=int, default=2, help="limit concurrent remote-target sessions")
    common.add_argument("--auto-timeout", action="store_true", help="auto-scale per-task timeout by category/difficulty and interactive risk")
    common.add_argument("--global-time-budget-min", type=int, default=0, help="global pipeline wall-clock budget in minutes (0 disables)")
    common.add_argument("--base", help="ctfd base url used with --start-containers and submit sync")
    common.add_argument("--session", help="ctfd session for remote platform actions")
    common.add_argument("--token", help="ctfd token for remote platform actions")

    advanced.add_argument(
        "--opencode-continue",
        action="store_true",
        help="deprecated/ignored: opencode --continue resumes the last global session and is unsafe in pipeline runs",
    )
    advanced.add_argument(
        "--agent",
        default="auto",
        help="opencode agent name (default: auto route by challenge category)",
    )
    advanced.add_argument(
        "--model",
        default="",
        help="model provider/model override; default comes from CTF_MODEL / OPENAI_MODEL / MODEL",
    )
    advanced.add_argument(
        "--first-blood-mode",
        action="store_true",
        help="一血模式：优先使用 CTF_FIRST_BLOOD_MODEL；若未配置则回退到常规模型",
    )

    selection.add_argument("--category", action="append", help="category filter (repeatable or comma-separated; use 'all' for all categories)")
    selection.add_argument("--id", action="append", type=int, help="only process given challenge id (repeatable)")
    selection.add_argument("--select", help="manual challenge id selection, e.g. '1,2,5-8'")
    selection.add_argument("--interactive-select", action="store_true", help="prompt and manually pick challenge ids from filtered list")

    advanced.add_argument("--start-containers", action="store_true", help="auto start container challenges")
    advanced.add_argument("--backfill-from-work", help="one-time backfill flags from global workspace root into challenge dirs")
    advanced.add_argument("--prune-missing", action="store_true", help="remove status.json entries with missing challenge_dir/missing dirs")
    advanced.add_argument("--min-interval", type=float, default=5.0, help="submit minimum interval seconds")
    advanced.add_argument("--per-task-timeout-sec", type=int, default=1800, help="session timeout seconds per challenge (0 disables)")
    advanced.add_argument("--require-replay", choices=["on", "off"], default="on", help="require solve.py replay before auto submit")
    advanced.add_argument("--replay-timeout-sec", type=int, default=180, help="timeout for pre-submit solve.py replay")
    advanced.add_argument(
        "--event-dir-required",
        choices=["on", "off"],
        default="on",
        help="require challenge_dir to resolve back to --out-root event context",
    )
    advanced.add_argument("--dry-run", action="store_true", help="print commands without executing")
    advanced.add_argument(
        "--min-candidate-score",
        type=float,
        default=0.60,
        help="default candidate score threshold passed to submit gate via env",
    )
    advanced.add_argument(
        "--allow-unscored-submit",
        action="store_true",
        help="allow submit gate to accept candidates without score",
    )
    advanced.add_argument(
        "--max-incorrect-per-challenge",
        type=int,
        default=3,
        help="challenge-level incorrect submit limit before cooldown block",
    )
    advanced.add_argument(
        "--submit-cooldown-sec",
        type=int,
        default=600,
        help="challenge-level cooldown window for submit blocking",
    )
    advanced.add_argument(
        "--pull-submissions",
        action="store_true",
        help="pull latest submissions into submissions.jsonl before processing",
    )
    advanced.add_argument(
        "--pull-challenge-status",
        choices=["on", "off"],
        default="on",
        help="refresh CTFd challenge overview (solves/value/state/solved_by_me) into status.json before processing",
    )
    advanced.add_argument("--pull-submissions-endpoint", default="api/v1/submissions", help="submissions API path")
    advanced.add_argument("--pull-submissions-per-page", type=int, default=50, help="submissions API page size")
    advanced.add_argument("--pull-submissions-max-pages", type=int, default=5, help="max pages per pull")
    advanced.add_argument(
        "--image-watch",
        choices=["on", "off"],
        default="on",
        help="auto guard/repair newly created images during session (default: on)",
    )
    advanced.add_argument("--image-watch-interval-sec", type=int, default=8, help="image watch scan interval seconds")
    advanced.add_argument("--image-watch-max-per-scan", type=int, default=30, help="max images handled per scan")
    advanced.add_argument(
        "--allow-duplicate-sessions",
        action="store_true",
        help="allow launching a new session even when sessions.jsonl shows an unclosed recent session for the same challenge",
    )
    advanced.add_argument(
        "--resume-incomplete-sessions",
        choices=["on", "off"],
        default="on",
        help="resume unfinished opencode sessions when their session id can be resolved (default: on)",
    )
    advanced.add_argument(
        "--duplicate-session-ttl-sec",
        type=int,
        default=0,
        help="expiry for unfinished sessions in sessions.jsonl before allowing a new one; 0 keeps skipping duplicates indefinitely (default)",
    )
    advanced.add_argument(
        "--skip-repair-event-state",
        action="store_true",
        help="skip startup repair of task/context/status category and recommended_agent drift",
    )
    args = ap.parse_args()
    lifecycle_install_lock_signal_handlers()
    apply_mode_defaults(args)
    apply_auto_run_defaults(args)
    args.pipeline_id = str(uuid.uuid4())
    args.require_replay = str(args.require_replay).lower() == "on"
    args.event_dir_required = str(args.event_dir_required).lower() == "on"
    args.image_watch = str(args.image_watch).lower() == "on"
    args.resume_incomplete_sessions = str(args.resume_incomplete_sessions).lower() == "on"
    args.pull_challenge_status = str(args.pull_challenge_status).lower() == "on"

    args.out_root = Path(args.out_root).resolve()
    if not args.out_root.exists():
        raise RuntimeError(f"out root not found: {args.out_root}")
    env_file = args.env_file or str(args.out_root / ".env")
    env_map = load_env_file(env_file)
    args.base = args.base or env_map.get("CTFD_BASE_URL", "")
    args.session = args.session or env_map.get("CTFD_SESSION", "")
    args.token = args.token or env_map.get("CTFD_TOKEN", "")

    if args.pull_challenge_status and args.base and (args.session or args.token):
        cmd = [
            "python3",
            str(Path(__file__).resolve().parent / "pull_challenge_status.py"),
            "--event-dir",
            str(args.out_root),
            "--base",
            args.base,
        ]
        if args.session:
            cmd += ["--session", args.session]
        if args.token:
            cmd += ["--token", args.token]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            print("[warn] pull_challenge_status timed out timeout=60s", file=sys.stderr)
            result = None
        if result is None:
            pass
        elif result.returncode != 0:
            print(f"[warn] pull_challenge_status failed rc={result.returncode}", file=sys.stderr)
        elif result.stdout.strip():
            print(result.stdout.strip().splitlines()[-1])

    if args.pull_submissions:
        if not args.base:
            raise RuntimeError("--pull-submissions requires --base")
        if not args.session and not args.token:
            raise RuntimeError("--pull-submissions requires --session or --token")
        cmd = [
            "python3",
            str(Path(__file__).resolve().parent / "pull_submissions.py"),
            "--event-dir",
            str(args.out_root),
            "--base",
            args.base,
            "--endpoint",
            args.pull_submissions_endpoint,
            "--per-page",
            str(args.pull_submissions_per_page),
            "--max-pages",
            str(args.pull_submissions_max_pages),
        ]
        if args.session:
            cmd += ["--session", args.session]
        if args.token:
            cmd += ["--token", args.token]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            print("[warn] pull_submissions timed out timeout=90s", file=sys.stderr)
            result = None
        if result is None:
            pass
        elif result.returncode != 0:
            print(f"[warn] pull_submissions failed rc={result.returncode}", file=sys.stderr)
        elif result.stdout.strip():
            print(result.stdout.strip().splitlines()[-1])

    if not args.skip_repair_event_state:
        try:
            repair_result = repair_event_state(args.out_root, apply=True)
            task_n = len(repair_result.get("task_changes") or [])
            context_n = len(repair_result.get("context_changes") or [])
            status_n = len(repair_result.get("status_changes") or [])
            if task_n or context_n or status_n:
                print(
                    f"[repair] event state repaired task={task_n} context={context_n} status={status_n}"
                )
        except Exception as e:
            print(f"[warn] repair_event_state failed: {e}", file=sys.stderr)

    status = load_status_index(args.out_root)
    if args.prune_missing:
        pruned, removed = prune_missing_status_entries(status)
        if removed:
            save_status_index(args.out_root, pruned)
            status = pruned
            print(f"[prune] removed {len(removed)} stale status entries")
        else:
            print("[prune] no stale status entries")
    challenges = load_challenges_from_status(args.out_root)
    if not challenges:
        challenges = load_challenges_from_files(args.out_root)
    if not challenges:
        raise RuntimeError("no challenges found from status.json or challenge.txt")
    disable_submit = submissions_disabled_for_challenge(args)
    if disable_submit:
        args.auto_submit = False
    if args.backfill_from_work:
        apply_backfill_from_work(args.backfill_from_work, challenges, status, args.out_root)

    if args.submit_only and not args.auto_submit and not disable_submit:
        args.auto_submit = True
        print("[pipeline] --submit-only enabled, forcing --auto-submit")
    if args.auto_submit and not args.base:
        raise RuntimeError("--auto-submit requires --base")
    if args.auto_submit and not args.session and not args.token:
        raise RuntimeError("--auto-submit requires --session or --token")

    selected = filtered(challenges, args)
    if args.interactive_select:
        if not sys.stdin.isatty():
            raise RuntimeError("--interactive-select requires a TTY")
        selected = interactive_pick(selected)
    if args.only_unsolved:
        work_flag_index = build_work_flag_index(None)
        submit_index = build_solved_index_from_logs(args.out_root)
        changed = False
        tmp = []
        for ch in selected:
            sid = str(ch["id"])
            entry = status.setdefault(sid, {})
            submit_rec = submit_index.get(int(ch["id"])) if submit_index else None
            if submit_rec:
                submission_status = submit_rec.get("submission_status") or ""
                msg = str(submit_rec.get("message") or "")
                if submission_status:
                    entry["submission_status"] = submission_status
                if submit_rec.get("http_status") is not None:
                    entry["last_submit_http"] = submit_rec.get("http_status")
                if submit_rec.get("ts"):
                    entry["last_submit_ts"] = submit_rec.get("ts")
                submit_ok = submission_status in {"correct", "already_solved"} and "incorrect" not in msg
                if submit_ok:
                    entry["solved"] = True
                changed = True
            local_files = find_local_flag_files(ch)
            if local_files:
                entry["local_flag_found"] = True
                entry["local_flag_path"] = str(local_files[0])
                entry["local_flag_ts"] = local_files[0].stat().st_mtime
                changed = True
            elif work_flag_index:
                key = challenge_key(ch.get("name", ""), ch.get("category", ""))
                cand = work_flag_index.get(key)
                if cand:
                    entry["local_flag_found"] = True
                    entry["local_flag_path"] = str(cand["path"])
                    entry["local_flag_ts"] = cand["mtime"]
                    changed = True
            if is_solved(ch, entry):
                continue
            tmp.append(ch)
        selected = tmp
        if changed:
            save_status_index(args.out_root, status)

    enforce_event_dir_context(args.out_root, selected, required=args.event_dir_required)
    if not selected:
        print("no challenges matched filters")
        return
    for ch in selected:
        ch["submit_disabled"] = bool(submissions_disabled_for_challenge(args, ch))
        enrich_challenge_context(ch)
    if args.opencode_continue:
        print(
            "[warn] ignoring --opencode-continue: opencode resumes the last global session, "
            "which is unsafe for pipeline challenge isolation. "
            "This pipeline only resumes sessions via resolved per-challenge session ids."
        )
        args.opencode_continue = False
    if args.workers < 1:
        args.workers = 1
    if args.max_active_remote < 1:
        args.max_active_remote = 1

    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": args.base,
            "CTFD_SESSION": args.session,
            "CTFD_TOKEN": args.token,
        },
    )

    # Priority queue: faster-yield categories first, then estimated difficulty.
    selected = sorted(selected, key=priority_key)
    print(f"[pipeline] found {len(selected)} challenge(s)")
    status_lock = threading.Lock()
    budget_state = load_budget_state(args.out_root)
    budget_lock = threading.Lock()
    event_lock = threading.Lock()
    started_ids_lock = threading.Lock()
    started_ts = time.time()
    budget_state.setdefault("global", {})
    budget_state["global"]["pipeline_start_ts"] = started_ts
    budget_state["global"]["workers"] = args.workers
    budget_state["global"]["max_active_remote"] = args.max_active_remote
    budget_state["global"]["per_task_timeout_sec"] = args.per_task_timeout_sec
    budget_state["global"]["auto_timeout"] = bool(args.auto_timeout)
    budget_state["global"]["global_time_budget_min"] = args.global_time_budget_min
    save_budget_state(args.out_root, budget_state)
    remote_sem = threading.Semaphore(args.max_active_remote)
    round_started_ids = set()
    progress_lock = threading.Lock()
    run_ctx = PipelineRunContext(
        args=args,
        status=status,
        budget_state=budget_state,
        status_lock=status_lock,
        budget_lock=budget_lock,
        event_lock=event_lock,
        started_ids_lock=started_ids_lock,
        round_started_ids=round_started_ids,
    )

    def global_budget_exhausted():
        if not args.global_time_budget_min or args.global_time_budget_min <= 0:
            return False
        elapsed = time.time() - started_ts
        return elapsed >= float(args.global_time_budget_min) * 60.0

    def process_one(ch):
        if global_budget_exhausted():
            print(f"[budget] skip id={ch['id']} (global time budget exhausted)")
            return
        session_timeout_hint = None
        if args.auto_timeout:
            session_timeout_hint = auto_timeout_sec(ch, cap_sec=args.per_task_timeout_sec)
        elif args.per_task_timeout_sec and args.per_task_timeout_sec > 0:
            session_timeout_hint = int(args.per_task_timeout_sec)
        image_guard_timeout_sec, image_ocr_timeout_sec = precompute_timeout_budget(session_timeout_hint)
        requested_agent = (
            str(ch.get("recommended_agent") or "ctf-main")
            if args.agent in {"", "auto"}
            else str(args.agent)
        )
        dispatch = prepare_challenge_dispatch(
            ctx=run_ctx,
            ch=ch,
            requested_agent=requested_agent,
            resolve_agent_name_func=resolve_agent_name,
            canonical_category_func=canonical_category,
            recommended_agent_for_category_func=recommended_agent_for_category,
            resolve_resumable_session_for_challenge_func=lambda ch_, status_item_: resolve_resumable_session_for_challenge(
                args, ch_, status_item_
            ),
            validate_resumable_session_agent_func=lambda sid, expected_agent: lifecycle_validate_resumable_session_agent(
                sid,
                expected_agent,
                get_opencode_session_agent_state,
            ),
            should_skip_for_duplicate_session_func=lambda ch_: lifecycle_should_skip_for_duplicate_session(
                allow_duplicate_sessions=getattr(args, "allow_duplicate_sessions", False),
                duplicate_session_ttl_sec=float(getattr(args, "duplicate_session_ttl_sec", 0) or 0),
                out_root=run_ctx.out_root,
                sessions_file=SESSIONS_FILE,
                challenge_id=int(ch_["id"]),
                find_duplicate_active_session_func=find_duplicate_active_session_store,
            ),
            resolve_opencode_session_for_active_record_func=resolve_opencode_session_for_active_record,
            close_orphan_duplicate_session_func=lifecycle_close_orphan_duplicate_session,
            acquire_lock_func=lambda ch_: lifecycle_acquire_lock(
                run_ctx.out_root,
                run_ctx.pipeline_id,
                ch_,
                int(getattr(args, "per_task_timeout_sec", 0) or 0),
            ),
            build_session_title_func=build_session_title,
            append_session_record_func=append_session_record,
            load_event_index_func=load_event_index,
            load_status_index_func=load_status_index,
            update_event_index_func=update_event_index,
            print_func=print,
            stderr_print_func=lambda msg: print(msg, file=sys.stderr),
        )
        agent_name = str(dispatch.get("agent_name") or "ctf")
        lock_path = dispatch.get("lock_path")
        if lock_path is None:
            return
        ch["event"] = run_ctx.competition
        try:
            execute_challenge_run(
                ctx=run_ctx,
                ch=ch,
                agent_name=agent_name,
                remote_sem=remote_sem,
                reconcile_runtime_paths_func=reconcile_challenge_runtime_paths,
                load_event_index_func=load_event_index,
                save_status_index_func=save_status_index,
                save_event_index_func=save_event_index,
                maybe_start_container_func=maybe_start_container,
                evaluate_remote_readiness_func=evaluate_remote_readiness,
                write_task_files_func=lambda ch_: write_task_files(
                    ch_,
                    precompute_images=not bool(getattr(args, "dry_run", False)),
                    image_guard_timeout_sec=image_guard_timeout_sec,
                    image_ocr_timeout_sec=image_ocr_timeout_sec,
                ),
                launch_session_func=launch_session,
                append_session_record_func=append_session_record,
                update_event_index_func=update_event_index,
                save_budget_state_func=save_budget_state,
                touch_budget_challenge_func=touch_budget_challenge,
                estimate_difficulty_func=estimate_difficulty,
                record_preflight_failure_func=record_preflight_failure_state,
                update_remote_readiness_status_func=update_remote_readiness_status_state,
                record_session_phase_func=record_session_phase_state,
                update_run_budget_func=update_run_budget_state,
                finalize_attempt_outputs_func=finalize_attempt_outputs_state,
                maybe_record_attempt_func=lambda ch_, run_meta_, status_entry_, run_start_ts_, run_end_ts_: maybe_record_attempt(
                    args, ch_, run_meta_, status_entry_, run_start_ts_, run_end_ts_
                ),
                write_solve_report_func=write_solve_report,
                ensure_auto_writeup_func=lambda ch_: _ensure_auto_writeup_from_report(ch_),
                maybe_auto_learn_func=maybe_auto_learn,
                auto_submit_if_requested_func=auto_submit_if_requested,
                print_func=print,
            )
        finally:
            lifecycle_release_lock(lock_path)

    def run_batch(batch):
        if args.workers == 1 or len(batch) <= 1:
            for ch in batch:
                process_one(ch)
            return
        print(f"[pipeline] workers={args.workers}")
        total = len(batch)
        progress = {
            "started": 0,
            "finished": 0,
        }

        def run_logged(ch):
            with progress_lock:
                progress["started"] += 1
                slot = progress["started"]
                finished = progress["finished"]
                running = max(0, slot - finished - 1)
                print(
                    f"[worker] start {slot}/{total} id={ch['id']} "
                    f"name={ch.get('name','')} running={running}"
                )
            try:
                process_one(ch)
            finally:
                with progress_lock:
                    progress["finished"] += 1
                    done = progress["finished"]
                    remain = max(0, total - done)
                    running = max(0, progress["started"] - done)
                    print(
                        f"[worker] done {done}/{total} id={ch['id']} "
                        f"name={ch.get('name','')} running={running} remain={remain}"
                    )

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(run_logged, ch) for ch in batch]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    print(f"[warn] worker error: {e}", file=sys.stderr)

    def summarize_batch(batch, started_ids):
        solved_count = 0
        attempted_unsolved = 0
        unattempted = 0
        for ch in batch:
            sid = str(ch["id"])
            entry = status.get(sid, {})
            if is_solved(ch, entry):
                solved_count += 1
            elif int(ch["id"]) in started_ids:
                attempted_unsolved += 1
            else:
                unattempted += 1
        return solved_count, attempted_unsolved, unattempted

    if args.rounds < 0:
        args.rounds = 0
    original_selected = list(selected)
    overall_started_ids = set()
    round_no = 0
    max_rounds = int(args.rounds or 0)
    while True:
        round_no += 1
        if max_rounds > 0 and round_no > max_rounds:
            break
        batch = []
        for ch in original_selected:
            entry = status.get(str(ch["id"]), {})
            if is_solved(ch, entry):
                continue
            batch.append(ch)
        if not batch:
            round_label = f"{round_no}/{max_rounds}" if max_rounds > 0 else f"{round_no}/auto"
            print(f"[pipeline] round {round_label}: no unresolved challenges left")
            break
        if global_budget_exhausted():
            round_label = f"{round_no}/{max_rounds}" if max_rounds > 0 else f"{round_no}/auto"
            print(f"[pipeline] round {round_label}: global time budget exhausted before dispatch")
            break
        round_started_ids.clear()
        round_label = f"{round_no}/{max_rounds}" if max_rounds > 0 else f"{round_no}/auto"
        print(f"[pipeline] round {round_label} batch={len(batch)}")
        run_batch(batch)
        overall_started_ids.update(round_started_ids)
        if args.only_unsolved:
            retry_ids = []
            for ch in batch:
                sid = str(ch["id"])
                entry = status.get(sid, {})
                if is_solved(ch, entry):
                    continue
                if int(ch["id"]) not in round_started_ids:
                    retry_ids.append(int(ch["id"]))
            if retry_ids:
                retry_batch = [ch for ch in batch if int(ch["id"]) in set(retry_ids)]
                print(f"[pipeline] round {round_label} retrying unattempted challenges once: {retry_ids}")
                run_batch(retry_batch)
                overall_started_ids.update(round_started_ids)
        solved_count, attempted_unsolved, unattempted = summarize_batch(original_selected, overall_started_ids)
        print(
            f"[pipeline] round {round_label} summary total={len(original_selected)} solved={solved_count} "
            f"attempted_unsolved={attempted_unsolved} unattempted={unattempted}"
        )
    solved_count, attempted_unsolved, unattempted = summarize_batch(original_selected, overall_started_ids)
    print(
        f"[pipeline] final summary total={len(original_selected)} solved={solved_count} "
        f"attempted_unsolved={attempted_unsolved} unattempted={unattempted}"
    )


if __name__ == "__main__":
    main()
