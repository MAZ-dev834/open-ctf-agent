#!/usr/bin/env python3
from __future__ import annotations

import socket
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    from scripts.core.runtime_config import default_opencode_attach_url, default_opencode_db_path
except Exception:  # pragma: no cover
    import sys

    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.core.runtime_config import default_opencode_attach_url, default_opencode_db_path


_ATTACH_PROBE_CACHE: dict[str, bool] = {}


def resolve_opencode_attach_url() -> str:
    return default_opencode_attach_url().strip()


def should_attach_opencode_server(url: str) -> bool:
    url = str(url or "").strip()
    if not url:
        return False
    cached = _ATTACH_PROBE_CACHE.get(url)
    if cached is not None:
        return cached
    ok = False
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        with socket.create_connection((host, port), timeout=0.3):
            ok = True
    except Exception:
        ok = False
    _ATTACH_PROBE_CACHE[url] = ok
    return ok


def _sqlite_readonly_uri(db_path: str | Path) -> str:
    path = Path(db_path).expanduser().resolve()
    return f"file:{quote(str(path))}?mode=ro"


def find_opencode_session_record(
    *,
    title: str,
    directory: str = "",
    created_after_ms: int = 0,
    created_before_ms: int = 0,
    db_path: str | Path | None = None,
):
    target_db = Path(db_path or default_opencode_db_path()).expanduser()
    if not target_db.exists():
        return None
    con = None
    try:
        con = sqlite3.connect(_sqlite_readonly_uri(target_db), uri=True, timeout=0.2)
        cur = con.cursor()
        sql = [
            "SELECT id, title, directory, time_created, time_updated",
            "FROM session",
            "WHERE title = ?",
        ]
        args = [title]
        if directory:
            sql.append("AND directory = ?")
            args.append(directory)
        if created_after_ms > 0:
            sql.append("AND time_created >= ?")
            args.append(int(created_after_ms))
        if created_before_ms > 0:
            sql.append("AND time_created <= ?")
            args.append(int(created_before_ms))
        sql.append("ORDER BY time_updated DESC LIMIT 1")
        cur.execute(" ".join(sql), args)
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "directory": row[2],
            "time_created": row[3],
            "time_updated": row[4],
        }
    except Exception:
        return None
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def resolve_opencode_session_for_active_record(
    dup: dict,
    *,
    title_candidates: list[str],
    directory: str,
    db_path: str | Path | None = None,
) -> str:
    explicit = str(dup.get("opencode_session_id") or "").strip()
    if explicit:
        return explicit
    try:
        ts_sec = float(dup.get("ts") or 0.0)
    except Exception:
        ts_sec = 0.0
    if ts_sec <= 0:
        return ""
    lower_ms = int((ts_sec - 120.0) * 1000)
    upper_ms = int((ts_sec + 7200.0) * 1000)
    seen = set()
    for title in title_candidates:
        title = str(title or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        hit = find_opencode_session_record(
            title=title,
            directory=directory,
            created_after_ms=lower_ms,
            created_before_ms=upper_ms,
            db_path=db_path,
        )
        if hit:
            return str(hit.get("id") or "")
    return ""


def get_opencode_session_agent_state(
    session_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    target_db = Path(db_path or default_opencode_db_path()).expanduser()
    if not target_db.exists():
        return None
    con = None
    try:
        con = sqlite3.connect(_sqlite_readonly_uri(target_db), uri=True, timeout=0.2)
        cur = con.cursor()
        cur.execute(
            """
            SELECT time_created,
                   json_extract(data, '$.role') AS role,
                   json_extract(data, '$.agent') AS agent,
                   json_extract(data, '$.mode') AS mode
            FROM message
            WHERE session_id = ?
            ORDER BY time_created DESC
            LIMIT 256
            """,
            [sid],
        )
        rows = cur.fetchall()
        if not rows:
            return None
        out = {
            "session_id": sid,
            "last_user_agent": "",
            "last_user_mode": "",
            "last_user_ts": 0,
            "last_assistant_agent": "",
            "last_assistant_mode": "",
            "last_assistant_ts": 0,
            "recent_user_agents": [],
            "recent_assistant_agents": [],
        }
        user_seen = set()
        assistant_seen = set()
        for row in rows:
            ts, role, agent, mode = row
            role = str(role or "").strip()
            agent = str(agent or "").strip()
            mode = str(mode or "").strip()
            if role == "user" and not out["last_user_agent"]:
                out["last_user_agent"] = agent
                out["last_user_mode"] = mode
                out["last_user_ts"] = int(ts or 0)
            if role == "user" and agent:
                user_seen.add(agent)
            elif role == "assistant" and agent and agent != "compaction" and not out["last_assistant_agent"]:
                out["last_assistant_agent"] = agent
                out["last_assistant_mode"] = mode
                out["last_assistant_ts"] = int(ts or 0)
            if role == "assistant" and agent and agent != "compaction":
                assistant_seen.add(agent)
        out["recent_user_agents"] = sorted(user_seen)
        out["recent_assistant_agents"] = sorted(assistant_seen)
        return out
    except Exception:
        return None
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
