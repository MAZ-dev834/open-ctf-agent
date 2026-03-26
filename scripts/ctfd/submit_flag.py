#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
from urllib.parse import urljoin
import os

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


def http_post_json(url, payload, headers=None, cookies=None, timeout=20):
    if requests:
        resp = requests.post(
            url, headers=headers, cookies=cookies, json=payload, timeout=timeout
        )
        return resp.status_code, resp.text
    # urllib fallback
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", errors="replace")
        return r.status, text


def http_get_text(url, headers=None, cookies=None, timeout=20):
    if requests:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=timeout)
        return resp.status_code, resp.text
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", errors="replace")
        return r.status, text


def extract_csrf_token(html):
    patterns = [
        r'csrfNonce"\s*:\s*"([^"]+)"',
        r"csrfNonce'\s*:\s*\"([^\"]+)\"",
        r"csrfNonce'\s*:\s*'([^']+)'",
        r'name="csrf-token"\s+content="([^"]+)"',
        r"name='csrf-token'\s+content='([^']+)'",
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def fetch_csrf_token(base, headers, cookies):
    probe_paths = ["challenges", ""]
    for p in probe_paths:
        url = urljoin(base, p)
        try:
            status, text = http_get_text(
                url, headers=headers, cookies=cookies, timeout=20
            )
        except Exception:
            continue
        if status >= 400:
            continue
        token = extract_csrf_token(text)
        if token:
            return token
    return ""


def resolve_submit_log_path(log_arg, event_dir, env_map):
    if log_arg:
        return log_arg
    env_log = str(env_map.get("CTFD_SUBMIT_LOG", "")).strip()
    if env_log:
        return env_log
    if event_dir:
        return os.path.join(event_dir, "submissions.jsonl")
    raise RuntimeError(
        "missing submit log path: provide --event-dir, --log, or CTFD_SUBMIT_LOG"
    )


def main():
    ap = argparse.ArgumentParser(description="Submit a flag to CTFd")
    ap.add_argument("--base", help="Base URL, e.g. https://ctfd.example/")
    ap.add_argument("--id", required=True, type=int, help="Challenge ID")
    ap.add_argument("--flag", required=True, help="Flag to submit")
    ap.add_argument("--session", help="CTFd session cookie value")
    ap.add_argument("--token", help="CTFd API access token")
    ap.add_argument(
        "--event-dir",
        help="Event directory; load/save credentials from <event-dir>/.env",
    )
    ap.add_argument("--env-file", help="Custom .env path for credentials")
    ap.add_argument(
        "--log",
        default=None,
        help="Log file (JSONL). Default: <event-dir>/submissions.jsonl when --event-dir is set",
    )
    ap.add_argument(
        "--min-interval",
        type=float,
        default=5.0,
        help="Minimum seconds between submissions",
    )
    args = ap.parse_args()

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
    headers = {"User-Agent": "ctfd-submit/1.0"}
    csrf = env_map.get("CTFD_CSRF_TOKEN", "")
    csrf_header = "X-CSRF-Token"
    if token:
        headers["Authorization"] = f"Token {token}"
    elif session:
        if csrf:
            headers[csrf_header] = csrf
        else:
            csrf = fetch_csrf_token(base, headers, cookies)
            if csrf:
                headers[csrf_header] = csrf
        headers["Referer"] = urljoin(base, "challenges")

    endpoint = urljoin(base, "api/v1/challenges/attempt")
    payload = {"challenge_id": args.id, "submission": args.flag}

    log_path = resolve_submit_log_path(args.log, args.event_dir, env_map)

    lock_path = log_path + ".lock"
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)

    status = 0
    text = ""
    data = None
    # Keep wait + submit + append under one lock to enforce real global QPS.
    with open(lock_path, "a+", encoding="utf-8") as lockf:
        try:
            import fcntl

            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass

        if args.min_interval and args.min_interval > 0:
            try:
                last_ts = None
                with open(log_path, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(size - 4096, 0))
                    lines = f.read().splitlines()
                for line in reversed(lines):
                    try:
                        rec = json.loads(line.decode("utf-8"))
                        if isinstance(rec, dict) and "ts" in rec:
                            last_ts = float(rec["ts"])
                            break
                    except Exception:
                        continue
                if last_ts is not None:
                    wait = args.min_interval - (time.time() - last_ts)
                    if wait > 0:
                        time.sleep(wait)
            except Exception:
                pass

        status, text = http_post_json(
            endpoint, payload, headers=headers, cookies=cookies, timeout=20
        )
        try:
            data = json.loads(text)
        except Exception:
            data = None

        try:
            record = {
                "ts": time.time(),
                "challenge_id": args.id,
                "flag": args.flag,
                "http_status": status,
            }
            if isinstance(data, dict):
                record["response"] = data
            else:
                record["response"] = text
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        try:
            import fcntl

            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass

    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": base,
            "CTFD_SESSION": session,
            "CTFD_TOKEN": token,
            "CTFD_CSRF_TOKEN": csrf,
        },
    )

    auth_mode = "token" if token else "session"
    csrf_used = bool(headers.get(csrf_header))

    try:
        if data is None:
            raise ValueError("not json")
        print(
            json.dumps(
                {
                    "http_status": status,
                    "auth_mode": auth_mode,
                    "csrf_used": csrf_used,
                    "response": data,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        print(
            json.dumps(
                {
                    "http_status": status,
                    "auth_mode": auth_mode,
                    "csrf_used": csrf_used,
                    "response": text,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
