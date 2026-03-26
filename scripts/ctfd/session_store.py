#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path


def append_session_record(out_root: Path, sessions_file: str, payload: dict) -> None:
    if not out_root:
        return
    try:
        path = out_root / sessions_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def load_session_state(out_root: Path, sessions_file: str) -> dict[int, dict]:
    path = out_root / sessions_file
    state: dict[int, dict] = {}
    if not path.exists():
        return state
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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
                try:
                    challenge_id = int(rec.get("challenge_id"))
                except Exception:
                    continue
                phase = str(rec.get("phase") or "").strip().lower()
                session_uid = str(rec.get("session_uid") or "").strip()
                if not session_uid:
                    continue
                item = state.setdefault(
                    challenge_id,
                    {
                        "last_start": None,
                        "last_end": None,
                        "active": {},
                    },
                )
                if phase == "start":
                    item["last_start"] = rec
                    item["active"][session_uid] = rec
                elif phase == "bind":
                    active_rec = item["active"].get(session_uid)
                    if active_rec is not None:
                        active_rec["opencode_session_id"] = rec.get("opencode_session_id")
                    if item.get("last_start", {}).get("session_uid") == session_uid:
                        item["last_start"]["opencode_session_id"] = rec.get("opencode_session_id")
                elif phase == "end":
                    item["last_end"] = rec
                    item["active"].pop(session_uid, None)
    except Exception:
        return {}
    return state


def find_latest_recorded_session_id(out_root: Path, sessions_file: str, challenge_id: int) -> str:
    state = load_session_state(out_root, sessions_file).get(int(challenge_id)) or {}
    candidates = []
    for key in ("last_end", "last_start"):
        rec = state.get(key)
        if isinstance(rec, dict):
            sid = str(rec.get("opencode_session_id") or "").strip()
            if sid:
                candidates.append((float(rec.get("ts") or 0.0), sid))
    active = state.get("active") or {}
    for rec in active.values():
        if not isinstance(rec, dict):
            continue
        sid = str(rec.get("opencode_session_id") or "").strip()
        if sid:
            candidates.append((float(rec.get("ts") or 0.0), sid))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def find_duplicate_active_session(out_root: Path, sessions_file: str, challenge_id: int, ttl_sec: float) -> dict | None:
    state = load_session_state(out_root, sessions_file).get(int(challenge_id)) or {}
    active = state.get("active") or {}
    if not active:
        return None
    now = time.time()
    candidates = []
    for rec in active.values():
        try:
            ts = float(rec.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if ttl_sec > 0 and ts > 0 and (now - ts) > ttl_sec:
            continue
        candidates.append(rec)
    if not candidates:
        return None
    candidates.sort(key=lambda x: float(x.get("ts") or 0.0), reverse=True)
    return candidates[0]

