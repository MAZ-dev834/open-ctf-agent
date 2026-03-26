#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

_ACTIVE_LOCKS: set[str] = set()
_SIGNAL_HANDLERS_INSTALLED = False


def is_pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lock_path_for(out_root: Path, challenge_id: int) -> Path:
    return out_root / ".locks" / f"challenge_{challenge_id}.lock.json"


def session_ttl_for(per_task_timeout_sec: int) -> int:
    ttl = per_task_timeout_sec * 2 if per_task_timeout_sec and per_task_timeout_sec > 0 else 7200
    if ttl < 600:
        ttl = 600
    return ttl


def release_all_active_locks():
    for lock_path in list(_ACTIVE_LOCKS):
        try:
            Path(lock_path).unlink()
        except Exception:
            pass
        finally:
            _ACTIVE_LOCKS.discard(lock_path)


def install_lock_signal_handlers():
    global _SIGNAL_HANDLERS_INSTALLED
    if _SIGNAL_HANDLERS_INSTALLED:
        return

    def _handle_signal(signum, _frame):
        release_all_active_locks()
        raise SystemExit(128 + int(signum))

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            continue
    _SIGNAL_HANDLERS_INSTALLED = True


def acquire_lock(out_root: Path, pipeline_id: str, challenge: dict, per_task_timeout_sec: int):
    locks_dir = out_root / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_path_for(out_root, int(challenge["id"]))
    lock_ttl = session_ttl_for(per_task_timeout_sec)

    if lock_path.exists():
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = int(data.get("pid", -1))
            ts = float(data.get("ts", 0))
            age = time.time() - ts if ts else 0
            if is_pid_alive(pid) and (age <= lock_ttl or lock_ttl <= 0):
                return None, f"[lock] skip id={challenge['id']} held_by_pid={pid}"
            if is_pid_alive(pid) and age > lock_ttl:
                return "stale", f"[lock] stale id={challenge['id']} held_by_pid={pid} age_sec={int(age)}"
        except Exception:
            pass
        try:
            lock_path.unlink()
        except Exception:
            return None, f"[warn] cannot clear stale lock for id={challenge['id']}"

    payload = {
        "pid": os.getpid(),
        "ts": time.time(),
        "challenge_id": challenge["id"],
        "challenge_dir": challenge.get("challenge_dir", ""),
        "pipeline_id": pipeline_id,
    }
    try:
        with open(lock_path, "x", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        _ACTIVE_LOCKS.add(str(lock_path))
        return lock_path, ""
    except FileExistsError:
        return None, f"[lock] skip id={challenge['id']} (lock exists)"


def release_lock(lock_path):
    if not lock_path or lock_path == "stale":
        return
    try:
        Path(lock_path).unlink()
    except Exception:
        pass
    finally:
        _ACTIVE_LOCKS.discard(str(lock_path))


def should_skip_for_duplicate_session(
    *,
    allow_duplicate_sessions: bool,
    duplicate_session_ttl_sec: float,
    out_root: Path,
    sessions_file: str,
    challenge_id: int,
    find_duplicate_active_session_func,
):
    if allow_duplicate_sessions:
        return None
    ttl = float(duplicate_session_ttl_sec or 0)
    dup = find_duplicate_active_session_func(out_root, sessions_file, int(challenge_id), ttl)
    if not dup:
        return None
    try:
        existing_ts = float(dup.get("ts") or 0.0)
    except Exception:
        existing_ts = 0.0
    age_sec = int(max(0.0, time.time() - existing_ts)) if existing_ts else None
    return {
        "session_uid": str(dup.get("session_uid") or ""),
        "pipeline_id": str(dup.get("pipeline_id") or ""),
        "opencode_session_id": str(dup.get("opencode_session_id") or ""),
        "title": str(dup.get("title") or ""),
        "challenge_name": str(dup.get("challenge_name") or ""),
        "category": str(dup.get("category") or ""),
        "age_sec": age_sec,
        "ts": existing_ts,
    }


def validate_resumable_session_agent(session_id: str, expected_agent: str, get_opencode_session_agent_state_func) -> tuple[bool, str]:
    sid = str(session_id or "").strip()
    expected = str(expected_agent or "").strip()
    if not sid or not expected:
        return True, ""
    state = get_opencode_session_agent_state_func(sid)
    if not isinstance(state, dict):
        return True, ""
    mismatches = []
    last_user_agent = str(state.get("last_user_agent") or "").strip()
    last_assistant_agent = str(state.get("last_assistant_agent") or "").strip()
    recent_user_agents = [str(x or "").strip() for x in (state.get("recent_user_agents") or [])]
    recent_assistant_agents = [str(x or "").strip() for x in (state.get("recent_assistant_agents") or [])]
    if last_user_agent and last_user_agent != expected:
        mismatches.append(f"user={last_user_agent}")
    if last_assistant_agent and last_assistant_agent != expected:
        mismatches.append(f"assistant={last_assistant_agent}")
    user_drift = sorted({x for x in recent_user_agents if x and x != expected})
    assistant_drift = sorted({x for x in recent_assistant_agents if x and x != expected})
    if user_drift:
        mismatches.append(f"user_recent={','.join(user_drift)}")
    if assistant_drift:
        mismatches.append(f"assistant_recent={','.join(assistant_drift)}")
    if mismatches:
        return False, ", ".join(mismatches)
    return True, ""


def close_orphan_duplicate_session(
    *,
    out_root: Path,
    competition: str,
    ch: dict,
    dup: dict,
    agent_name: str,
    model: str,
    build_session_title_func,
    append_session_record_func,
    load_event_index_func,
    load_status_index_func,
    update_event_index_func,
):
    session_uid = str(dup.get("session_uid") or "").strip()
    if not session_uid:
        return
    end_entry = {
        "phase": "end",
        "ts": time.time(),
        "session_uid": session_uid,
        "opencode_session_id": str(dup.get("opencode_session_id") or "").strip(),
        "pipeline_id": str(dup.get("pipeline_id") or "").strip(),
        "challenge_id": ch.get("id"),
        "challenge_name": ch.get("name", ""),
        "category": ch.get("category", ""),
        "agent": agent_name,
        "model": model,
        "title": build_session_title_func(competition, ch.get("category", ""), ch.get("name", "")),
        "resolved_challenge_dir": ch.get("resolved_challenge_dir", ch.get("challenge_dir", "")),
        "elapsed_sec": 0.0,
        "returncode": 98,
        "timed_out": False,
        "failure_reason": "orphaned_duplicate_session",
        "message": "auto-closed stale duplicate session with no resumable opencode session id",
    }
    append_session_record_func(out_root, end_entry)
    try:
        _ = load_event_index_func(out_root)
        update_event_index_func(
            out_root,
            ch,
            status_entry=load_status_index_func(out_root).get(str(ch.get("id")), {}),
            session_entry=end_entry,
            competition=competition,
        )
    except Exception:
        pass
