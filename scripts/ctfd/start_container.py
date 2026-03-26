#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse

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


def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def compact_text(text, limit=4000):
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit] + f"...[truncated {len(s) - limit} chars]"


def http_request(
    method,
    url,
    headers=None,
    cookies=None,
    timeout=20,
    data=None,
    json_payload=None,
):
    headers = dict(headers or {})
    method = method.upper()
    if requests:
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                cookies=cookies,
                timeout=timeout,
                data=data,
                json=json_payload,
            )
            return resp.status_code, resp.text
        except Exception as e:
            return 0, f"request_error: {e}"

    import urllib.error
    import urllib.request

    body = None
    req_headers = dict(headers)
    if json_payload is not None:
        body = json.dumps(json_payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = urlencode(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
            return r.status, text
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = str(e)
        return e.code, text
    except Exception as e:
        return 0, f"request_error: {e}"


def extract_csrf_nonce(html):
    pats = [
        r"csrfNonce'\s*:\s*'([^']+)'",
        r'csrfNonce"\s*:\s*"([^"]+)"',
        r'name="csrf-token"\s+content="([^"]+)"',
        r"name='csrf-token'\s+content='([^']+)'",
    ]
    for pat in pats:
        m = re.search(pat, html or "")
        if m:
            return m.group(1)
    return ""


def maybe_add_csrf(base, headers, cookies):
    if headers.get("Authorization"):
        return
    if headers.get("CSRF-Token"):
        return
    status, text = http_request(
        "GET", urljoin(base, "challenges"), headers=headers, cookies=cookies, timeout=20
    )
    if status >= 400:
        return
    token = extract_csrf_nonce(text)
    if token:
        headers["CSRF-Token"] = token
        headers["Referer"] = urljoin(base, "challenges")


def normalize_hostport_url(value):
    s = str(value or "").strip()
    if not s:
        return ""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
        return s
    if re.match(r"^[A-Za-z0-9_.:-]+:\d+$", s):
        return f"tcp://{s}"
    return ""


def build_instance_url(data):
    # ctfd-owl style
    if isinstance(data, dict):
        ip = data.get("ip")
        containers = data.get("containers_data") or []
        if ip and containers:
            c0 = containers[0] if isinstance(containers[0], dict) else {}
            port = c0.get("port")
            labels = c0.get("labels") if isinstance(c0, dict) else {}
            labels = labels if isinstance(labels, dict) else {}
            fields = labels.get("fields") if isinstance(labels, dict) else {}
            fields = fields if isinstance(fields, dict) else {}
            conntype = fields.get("conntype") or "http"
            if port:
                return f"{conntype}://{ip}:{port}"

    # generic recursive search
    queue = [data]
    seen = set()
    while queue:
        cur = queue.pop(0)
        cid = id(cur)
        if cid in seen:
            continue
        seen.add(cid)
        if isinstance(cur, dict):
            for k in ("instance_url", "url", "target", "connection", "connection_info"):
                if k in cur:
                    u = normalize_hostport_url(cur.get(k))
                    if u:
                        return u
                    if isinstance(cur.get(k), str):
                        m = re.search(r"([A-Za-z0-9_.-]+:\d+)", cur.get(k))
                        if m:
                            return f"tcp://{m.group(1)}"
            host = cur.get("host") or cur.get("ip")
            port = cur.get("port")
            if host and port:
                proto = cur.get("proto") or cur.get("scheme") or "tcp"
                return f"{proto}://{host}:{port}"
            queue.extend(cur.values())
        elif isinstance(cur, list):
            queue.extend(cur)
        elif isinstance(cur, str):
            u = normalize_hostport_url(cur)
            if u:
                return u
            m = re.search(r"([A-Za-z0-9_.-]+:\d+)", cur)
            if m:
                return f"tcp://{m.group(1)}"
    return ""


def find_challenge_dir(out_root, ch_id):
    if not out_root:
        return ""
    prefixes = [f"{ch_id:02d} - ", f"{ch_id} - ", f"{ch_id:02d}_", f"{ch_id}_"]
    for root, dirs, _files in os.walk(out_root):
        for d in dirs:
            for p in prefixes:
                if d.startswith(p):
                    return os.path.join(root, d)
    return ""


def profile_path(out_root):
    if not out_root:
        return ""
    return os.path.join(out_root, "provider_profile.json")


def load_profile(out_root):
    pp = profile_path(out_root)
    if not pp or not os.path.exists(pp):
        return {}
    try:
        with open(pp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_profile(out_root, profile):
    pp = profile_path(out_root)
    if not pp:
        return
    try:
        with open(pp, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def has_challenge_id_param(url):
    return "challenge_id=" in url


def endpoint_with_id(base, path_or_url, challenge_id):
    if not path_or_url:
        return ""
    u = path_or_url
    if not urlparse(path_or_url).scheme:
        u = urljoin(base, path_or_url)
    if has_challenge_id_param(u):
        return u
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}challenge_id={challenge_id}"


def discover_candidates(base, challenge_id, headers, cookies):
    candidates = []
    seed_paths = [
        "plugins/ctfd-owl/container",
        "plugins/docker_challenges/container",
        "plugins/ctfd-whale/container",
        "plugins/container/container",
        "api/v1/container",
    ]
    for p in seed_paths:
        candidates.append(endpoint_with_id(base, p, challenge_id))

    for page in ("challenges", ""):
        status, text = http_request(
            "GET", urljoin(base, page), headers=headers, cookies=cookies, timeout=20
        )
        if status >= 400 or not text:
            continue
        for m in re.finditer(r"['\"](/[^'\"<>]*container[^'\"<>]*)['\"]", text):
            cand = endpoint_with_id(base, m.group(1), challenge_id)
            if cand:
                candidates.append(cand)

    uniq = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def probe_endpoint(endpoint, challenge_id, headers, cookies, poll_interval, poll_max):
    methods = [
        ("POST", None, None),
        ("POST", {"challenge_id": challenge_id}, None),
        ("POST", None, {"challenge_id": challenge_id}),
        ("GET", None, None),
    ]
    start_status = 0
    start_text = ""
    start_json = None
    instance_url = ""
    used_start_method = ""

    for method, form_data, json_data in methods:
        status, text = http_request(
            method,
            endpoint,
            headers=headers,
            cookies=cookies,
            timeout=20,
            data=form_data,
            json_payload=json_data,
        )
        payload = parse_json(text)
        inst = build_instance_url(payload) if payload is not None else ""
        if not start_text:
            start_status = status
            start_text = text
            start_json = payload
            used_start_method = method
        if inst:
            instance_url = inst
            start_status = status
            start_text = text
            start_json = payload
            used_start_method = method
            break
        # Prefer non-404 as start result.
        if status and status != 404:
            start_status = status
            start_text = text
            start_json = payload
            used_start_method = method

    poll_status = 0
    poll_text = ""
    poll_json = None
    poll_attempts = 0
    for i in range(max(poll_max, 1)):
        poll_attempts = i + 1
        poll_status, poll_text = http_request(
            "GET", endpoint, headers=headers, cookies=cookies, timeout=20
        )
        poll_json = parse_json(poll_text)
        if poll_json is not None:
            instance_url = build_instance_url(poll_json) or instance_url
        if instance_url:
            break
        if i < max(poll_max, 1) - 1:
            time.sleep(max(poll_interval, 0.0))

    return {
        "challenge_id": challenge_id,
        "start_url": endpoint,
        "poll_url": endpoint,
        "start_method": used_start_method or "POST/GET-probe",
        "start_http": start_status,
        "start_response": start_json if start_json is not None else compact_text(start_text),
        "poll_http": poll_status,
        "poll_response": poll_json if poll_json is not None else compact_text(poll_text),
        "instance_url": instance_url,
        "poll_attempts": poll_attempts,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Start CTFd container instance with provider detection and fallback probes."
    )
    ap.add_argument("--base", help="Base URL, e.g. https://2026.4x10m.ru/")
    ap.add_argument("--id", required=True, type=int, help="Challenge ID")
    ap.add_argument("--session", help="CTFd session cookie value")
    ap.add_argument("--token", help="CTFd API access token")
    ap.add_argument("--env-file", help="Custom .env path; default: <out-root>/.env")
    ap.add_argument("--endpoint", help="Override start endpoint (full URL)")
    ap.add_argument("--poll-endpoint", help="Override poll endpoint (full URL)")
    ap.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between poll attempts")
    ap.add_argument("--poll-max", type=int, default=20, help="Maximum poll attempts")
    ap.add_argument("--out-root", help="Root output dir to update status.json/challenge.txt")
    ap.add_argument("--status", default="status.json", help="Status JSON path (if out-root not set)")
    args = ap.parse_args()

    env_file = args.env_file or (os.path.join(args.out_root, ".env") if args.out_root else None)
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
    headers = {"User-Agent": "ctfd-container/1.0"}
    if token:
        headers["Authorization"] = f"Token {token}"
    maybe_add_csrf(base, headers, cookies)

    profile = load_profile(args.out_root)
    candidates = []
    if args.endpoint:
        candidates.append(endpoint_with_id(base, args.endpoint, args.id))
    elif args.poll_endpoint:
        candidates.append(endpoint_with_id(base, args.poll_endpoint, args.id))
    else:
        prof_url = (
            ((profile.get("container") or {}).get("start_url"))
            if isinstance(profile, dict)
            else ""
        )
        if prof_url:
            candidates.append(endpoint_with_id(base, prof_url, args.id))
        candidates.extend(discover_candidates(base, args.id, headers, cookies))

    # Keep order and de-duplicate.
    uniq = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    candidates = uniq
    if not candidates:
        default_endpoint = endpoint_with_id(base, "plugins/ctfd-owl/container", args.id)
        candidates = [default_endpoint]

    probes = []
    result = None
    for endpoint in candidates:
        r = probe_endpoint(
            endpoint=endpoint,
            challenge_id=args.id,
            headers=headers,
            cookies=cookies,
            poll_interval=args.poll_interval,
            poll_max=args.poll_max,
        )
        probes.append(
            {
                "endpoint": endpoint,
                "start_http": r.get("start_http"),
                "poll_http": r.get("poll_http"),
                "instance_url": r.get("instance_url", ""),
            }
        )
        result = r
        if r.get("instance_url"):
            break

    result = dict(result or {})
    result["provider_probe_count"] = len(probes)
    result["provider_probes"] = probes[:15]

    # Persist selected endpoint profile only on success.
    if args.out_root and result.get("instance_url"):
        save_profile(
            args.out_root,
            {
                "base": base,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "container": {
                    "start_url": result.get("start_url"),
                    "poll_url": result.get("poll_url"),
                    "start_method": result.get("start_method"),
                },
            },
        )

    print(json.dumps(result, ensure_ascii=False))

    status_path = args.status
    if args.out_root:
        status_path = os.path.join(args.out_root, "status.json")
    try:
        data = {}
        if os.path.exists(status_path):
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[str(args.id)] = {**data.get(str(args.id), {}), **result}
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    if args.out_root:
        ch_dir = find_challenge_dir(args.out_root, args.id)
        if ch_dir and result.get("instance_url"):
            txt_path = os.path.join(ch_dir, "challenge.txt")
            try:
                with open(txt_path, "a", encoding="utf-8") as f:
                    f.write(f"容器地址: {result.get('instance_url')}\n")
            except Exception:
                pass

    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": base,
            "CTFD_SESSION": session,
            "CTFD_TOKEN": token,
        },
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
