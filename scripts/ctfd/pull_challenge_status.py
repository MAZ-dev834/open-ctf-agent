#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests  # type: ignore
except Exception:
    requests = None


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
        return out
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


def http_get_json(url, headers=None, cookies=None, timeout=20):
    if requests:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=timeout)
        return resp.status_code, resp.json() if resp.text else {}
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    if cookies:
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8", errors="replace")
        return r.status, json.loads(data) if data else {}


def _to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def normalize_challenge_row(row):
    if not isinstance(row, dict):
        return None
    try:
        ch_id = int(row.get("id"))
    except Exception:
        return None
    solves = row.get("solves")
    if isinstance(solves, dict):
        solves = solves.get("value", solves.get("count", 0))
    return {
        "id": ch_id,
        "name": str(row.get("name") or ""),
        "category": str(row.get("category") or ""),
        "value": _to_int(row.get("value"), 0),
        "solves": _to_int(solves, 0),
        "solved_by_me": bool(row.get("solved_by_me", False)),
        "state": str(row.get("state") or ""),
        "type": str(row.get("type") or ""),
        "max_attempts": _to_int(row.get("max_attempts"), 0),
    }


def sync_once(args):
    env_file = args.env_file or os.path.join(args.event_dir, ".env")
    env_map = load_env_file(env_file)

    base = args.base or env_map.get("CTFD_BASE_URL", "")
    session = args.session or env_map.get("CTFD_SESSION", "")
    token = args.token or env_map.get("CTFD_TOKEN", "")
    if not base:
        raise RuntimeError("Provide --base or set CTFD_BASE_URL in .env")
    if not session and not token:
        raise RuntimeError("Provide --session or --token for authentication")
    if not base.endswith("/"):
        base += "/"

    headers = {"User-Agent": "ctfd-pull-challenge-status/1.0"}
    if token:
        headers["Authorization"] = f"Token {token}"
    cookies = {"session": session} if session else None

    endpoint = urljoin(base, args.endpoint.lstrip("/"))
    http_status, payload = http_get_json(endpoint, headers=headers, cookies=cookies, timeout=20)
    if http_status >= 400:
        raise RuntimeError(f"HTTP {http_status} for {endpoint}")
    if not isinstance(payload, dict) or not payload.get("success"):
        raise RuntimeError("CTFd API returned success=false for challenge list")
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        raise RuntimeError("CTFd challenge list payload is not a list")

    status_path = Path(args.event_dir) / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            status = {}
    else:
        status = {}
    if not isinstance(status, dict):
        status = {}

    updated = 0
    solved_me = 0
    now = time.time()
    for row in rows:
        item = normalize_challenge_row(row)
        if not item:
            continue
        sid = str(item["id"])
        entry = status.setdefault(sid, {"id": item["id"]})
        before = (
            entry.get("solved_by_me"),
            entry.get("ctfd_solves"),
            entry.get("ctfd_value"),
            entry.get("ctfd_state"),
            entry.get("ctfd_type"),
            entry.get("ctfd_max_attempts"),
        )
        if item["name"] and not entry.get("name"):
            entry["name"] = item["name"]
        if item["category"] and not entry.get("category"):
            entry["category"] = item["category"]
        entry["solved_by_me"] = item["solved_by_me"]
        entry["ctfd_solves"] = item["solves"]
        entry["ctfd_value"] = item["value"]
        entry["ctfd_state"] = item["state"]
        entry["ctfd_type"] = item["type"]
        entry["ctfd_max_attempts"] = item["max_attempts"]
        entry["ctfd_status_synced_at"] = now
        after = (
            entry.get("solved_by_me"),
            entry.get("ctfd_solves"),
            entry.get("ctfd_value"),
            entry.get("ctfd_state"),
            entry.get("ctfd_type"),
            entry.get("ctfd_max_attempts"),
        )
        if before != after:
            updated += 1
        if item["solved_by_me"]:
            solved_me += 1

    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": base,
            "CTFD_SESSION": session,
            "CTFD_TOKEN": token,
        },
    )
    return {
        "seen": len(rows),
        "updated": updated,
        "solved_by_me": solved_me,
        "status_path": str(status_path),
    }


def main():
    ap = argparse.ArgumentParser(description="Pull CTFd challenge overview into status.json")
    ap.add_argument("--base", help="Base URL, e.g. https://ctfd.example/")
    ap.add_argument("--session", help="CTFd session cookie value")
    ap.add_argument("--token", help="CTFd API access token")
    ap.add_argument("--event-dir", required=True, help="Event directory, e.g. ./events/democtf2026")
    ap.add_argument("--env-file", help="Custom .env path; default: <event-dir>/.env")
    ap.add_argument("--endpoint", default="api/v1/challenges", help="challenge list API path")
    args = ap.parse_args()
    print(json.dumps(sync_once(args), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
