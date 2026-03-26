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


def http_get_json(url, headers=None, cookies=None, timeout=20):
    if requests:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=timeout)
        return resp.status_code, resp.json() if resp.text else {}
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8", errors="replace")
        return r.status, json.loads(data) if data else {}


def parse_submit_status(record):
    status = ""
    message = ""
    if not isinstance(record, dict):
        return status, message
    if "status" in record:
        status = str(record.get("status") or "")
    if "message" in record:
        message = str(record.get("message") or "")
    if not status:
        correct = record.get("correct")
        if isinstance(correct, bool):
            status = "correct" if correct else "incorrect"
    if not message:
        resp = record.get("response")
        if resp:
            message = str(resp)
    return status.lower(), message.lower()


def normalize_record(rec, http_status):
    ch_id = rec.get("challenge_id", rec.get("id"))
    try:
        ch_id = int(ch_id)
    except Exception:
        return None
    ts = rec.get("ts")
    if ts is None:
        ts = rec.get("date")
    try:
        ts = float(ts) if ts is not None else time.time()
    except Exception:
        ts = time.time()
    status, message = parse_submit_status(rec)
    if not status:
        status = "unknown"
    payload = {
        "ts": ts,
        "challenge_id": ch_id,
        "flag": rec.get("provided") or rec.get("flag") or "",
        "http_status": http_status,
        "response": {"data": {"status": status, "message": message}, "source": "pull_submissions"},
    }
    return payload


def read_recent_log_keys(log_path, limit=200):
    keys = set()
    if not log_path.exists():
        return keys
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 65536, 0))
            lines = f.read().splitlines()[-limit:]
        for line in lines:
            try:
                rec = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            key = (rec.get("challenge_id"), rec.get("ts"), rec.get("response", {}).get("data", {}).get("status"))
            keys.add(key)
    except Exception:
        return keys
    return keys


def update_status_index(status_path, pulled_records):
    if not status_path.exists():
        return False
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(status, dict):
        return False
    changed = False
    for rec in pulled_records:
        ch_id = rec.get("challenge_id")
        try:
            sid = str(int(ch_id))
        except Exception:
            continue
        entry = status.setdefault(sid, {})
        data = (rec.get("response") or {}).get("data") or {}
        submission_status = str(data.get("status") or "")
        msg = str(data.get("message") or "")
        if submission_status:
            entry["submission_status"] = submission_status
            changed = True
        if rec.get("ts"):
            entry["last_submit_ts"] = rec.get("ts")
            changed = True
        if rec.get("http_status") is not None:
            entry["last_submit_http"] = rec.get("http_status")
            changed = True
        submit_ok = submission_status in {"correct", "already_solved"} and "incorrect" not in msg
        if submit_ok:
            entry["solved"] = True
            changed = True
    if changed:
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def pull_once(args):
    env_file = args.env_file
    if not env_file and args.event_dir:
        env_file = os.path.join(args.event_dir, ".env")
    env_map = load_env_file(env_file)

    base = args.base or env_map.get("CTFD_BASE_URL", "")
    session = args.session or env_map.get("CTFD_SESSION", "")
    token = args.token or env_map.get("CTFD_TOKEN", "")

    if not session and not token:
        raise RuntimeError("Provide --session or --token for authentication")
    if not base:
        raise RuntimeError("Provide --base or set CTFD_BASE_URL in .env")

    if not base.endswith("/"):
        base += "/"

    cookies = {"session": session} if session else None
    headers = {"User-Agent": "ctfd-pull-submissions/1.0"}
    if token:
        headers["Authorization"] = f"Token {token}"

    endpoint = urljoin(base, args.endpoint.lstrip("/"))
    log_path = Path(args.log or (Path(args.event_dir) / "submissions.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status_path = Path(args.event_dir) / "status.json" if args.event_dir else None

    recent_keys = read_recent_log_keys(log_path)
    pulled = []
    total_seen = 0
    for page in range(1, args.max_pages + 1):
        url = f"{endpoint}?page={page}&limit={args.per_page}"
        http_status, payload = http_get_json(url, headers=headers, cookies=cookies, timeout=20)
        if http_status >= 400:
            raise RuntimeError(f"HTTP {http_status} for {url}")
        if not isinstance(payload, dict):
            break
        data = payload.get("data", [])
        if not data:
            break
        if not isinstance(data, list):
            break
        for rec in data:
            total_seen += 1
            normalized = normalize_record(rec, http_status)
            if not normalized:
                continue
            key = (normalized.get("challenge_id"), normalized.get("ts"), normalized.get("response", {}).get("data", {}).get("status"))
            if key in recent_keys:
                continue
            pulled.append(normalized)
        if len(data) < args.per_page:
            break

    if pulled:
        with open(log_path, "a", encoding="utf-8") as f:
            for rec in pulled:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if status_path and status_path.exists():
            update_status_index(status_path, pulled)

    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": base,
            "CTFD_SESSION": session,
            "CTFD_TOKEN": token,
        },
    )

    return {"pulled": len(pulled), "seen": total_seen, "log": str(log_path)}


def main():
    ap = argparse.ArgumentParser(description="Pull CTFd submissions into submissions.jsonl")
    ap.add_argument("--base", help="Base URL, e.g. https://ctfd.example/")
    ap.add_argument("--session", help="CTFd session cookie value")
    ap.add_argument("--token", help="CTFd API access token")
    ap.add_argument("--event-dir", required=True, help="Event directory, e.g. ./events/democtf2026")
    ap.add_argument("--env-file", help="Custom .env path; default: <event-dir>/.env")
    ap.add_argument("--log", help="Log file (JSONL). Default: <event-dir>/submissions.jsonl")
    ap.add_argument("--endpoint", default="api/v1/submissions", help="Submissions API path")
    ap.add_argument("--per-page", type=int, default=50, help="API page size")
    ap.add_argument("--max-pages", type=int, default=5, help="Max pages per pull")
    ap.add_argument("--interval-sec", type=int, default=0, help="Loop interval (0 = once)")
    ap.add_argument("--max-iterations", type=int, default=0, help="Stop after N loops (0 = infinite when interval>0)")
    args = ap.parse_args()

    iter_count = 0
    while True:
        iter_count += 1
        try:
            res = pull_once(args)
        except Exception as e:
            print(f"[pull] error: {e}", file=sys.stderr)
            if args.interval_sec <= 0:
                sys.exit(2)
            res = {"pulled": 0, "seen": 0, "log": ""}
        print(f"[pull] seen={res['seen']} appended={res['pulled']} log={res['log']}")
        if args.interval_sec <= 0:
            break
        if args.max_iterations > 0 and iter_count >= args.max_iterations:
            break
        time.sleep(max(1, args.interval_sec))


if __name__ == "__main__":
    main()
