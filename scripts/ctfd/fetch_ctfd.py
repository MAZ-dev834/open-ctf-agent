#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests  # type: ignore
except Exception:
    requests = None

MAX_ATTACHMENT_BYTES = 1024 ** 3


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


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []

    def handle_data(self, data):
        if data:
            self._chunks.append(data)

    def get_text(self):
        return "".join(self._chunks)


def strip_html(html):
    if not html:
        return ""
    s = _Stripper()
    s.feed(html)
    return s.get_text()


def http_get(url, headers=None, cookies=None, timeout=20):
    if requests:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=timeout)
        return resp.status_code, resp.text, resp.content, resp.headers
    # urllib fallback
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return r.status, text, data, r.headers


def http_get_json(url, headers=None, cookies=None, timeout=20):
    status, text, _data, _hdrs = http_get(url, headers=headers, cookies=cookies, timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"HTTP {status} for {url}")
    return json.loads(text)


def safe_name(name):
    name = name.replace(os.sep, " ")
    name = name.replace("/", " ").replace("\\", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def safe_slug(name, fallback="item"):
    text = safe_name(name or "")
    text = re.sub(r"[^\w.\-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-._")
    return text or fallback


def canonical_category_name(raw):
    text = safe_name(raw or "").strip()
    low = text.lower()
    mapping = {
        "web": "Web",
        "web exploitation": "Web",
        "pwn": "Pwn",
        "binary exploitation": "Pwn",
        "rev": "Rev",
        "reverse engineering": "Rev",
        "crypto": "Crypto",
        "cryptography": "Crypto",
        "misc": "Misc",
        "miscellaneous": "Misc",
        "forensics": "Forensics",
        "forensic": "Forensics",
        "dfir": "Forensics",
        "digital forensics": "Forensics",
        "hardware": "Forensics",
        "stego": "Forensics",
        "steganography": "Forensics",
        "osint": "OSINT",
        "geoint": "OSINT",
        "geo": "OSINT",
        "geoint": "OSINT",
        "threat intel": "OSINT",
        "threat intelligence": "OSINT",
        "malware": "Malware",
    }
    if low in mapping:
        return mapping[low]
    if "web" in low:
        return "Web"
    if "crypto" in low:
        return "Crypto"
    if "reverse" in low or low == "rev":
        return "Rev"
    if "pwn" in low or "binary exploitation" in low:
        return "Pwn"
    if "malware" in low:
        return "Malware"
    if "osint" in low or "geoint" in low or low == "geo":
        return "OSINT"
    if any(x in low for x in ("forensic", "hardware", "stego", "dfir")):
        return "Forensics"
    if "misc" in low:
        return "Misc"
    return text or "Unknown"


def infer_category_from_tags(tags):
    values = []
    for tag in tags or []:
        if isinstance(tag, dict):
            val = tag.get("value")
        else:
            val = tag
        val = safe_name(val or "")
        if val:
            values.append(val)
    if not values:
        return "Unknown"
    preferred = [
        "Web",
        "Pwn",
        "Rev",
        "Crypto",
        "Forensics",
        "OSINT",
        "Malware",
        "Misc",
    ]
    normalized = [canonical_category_name(v) for v in values]
    for want in preferred:
        if want in normalized:
            return want
    return canonical_category_name(values[0])


def discover_existing_challenge_dirs(out_root):
    by_id = {}
    root = Path(out_root)
    if not root.exists():
        return by_id
    for cat_dir in root.iterdir():
        if not cat_dir.is_dir() or cat_dir.name.startswith("."):
            continue
        for ch_dir in cat_dir.iterdir():
            if not ch_dir.is_dir():
                continue
            m = re.match(r"^(\d+)(?:\s*-\s*|_)", ch_dir.name)
            if not m:
                continue
            try:
                cid = int(m.group(1))
            except Exception:
                continue
            resolved = ch_dir.resolve()
            prev = by_id.get(cid)
            if prev is None:
                by_id[cid] = resolved
                continue
            prev_unknown = prev.parent.name == "Unknown"
            cur_unknown = resolved.parent.name == "Unknown"
            if prev_unknown and not cur_unknown:
                by_id[cid] = resolved
    return by_id


def _looks_like_css(s):
    s_low = s.lower()
    if "var(" in s_low:
        return True
    if ":" in s or ";" in s or "!important" in s_low:
        return True
    if "background" in s_low or "color" in s_low:
        return True
    return False


def find_flag_format(rules_text, desc_text, flag_prefix=None):
    combined = "\n".join([rules_text or "", desc_text or ""])
    combined = combined.replace("\r", "")

    if flag_prefix:
        pref_pat = re.compile(rf"{re.escape(flag_prefix)}\{{[^}}\n]+}}")
        m = pref_pat.search(combined)
        if m:
            return m.group(0).strip()

    m = re.search(r"flag\s*format\s*[:\-]?\s*([^\n]+)", combined, re.IGNORECASE)
    if m:
        cand = m.group(1).strip()
        if not _looks_like_css(cand):
            return cand

    m = re.search(r"(?:пример|example)\s*[:\-]?\s*([^\n]+)", combined, re.IGNORECASE)
    if m:
        cand = m.group(1).strip()
        if not _looks_like_css(cand):
            return cand

    m = re.search(r"[A-Za-z0-9_]{2,}\{[^\n}]{1,}\}", combined)
    if m:
        cand = m.group(0).strip()
        if not _looks_like_css(cand):
            return cand

    if flag_prefix:
        return f"{flag_prefix}{{...}}"
    return ""

def is_container_challenge(ch):
    ch_type = (ch.get("type") or "").lower()
    if ch_type == "dynamic_check_docker":
        return True
    type_data = ch.get("type_data") or {}
    if (type_data.get("id") or "").lower() == "dynamic_check_docker":
        return True
    return False


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def challenge_dir_for(out_root, category, ch_id, name):
    cat_dir = os.path.join(out_root, category)
    return os.path.join(cat_dir, f"{ch_id:02d}_{safe_slug(name, f'challenge-{ch_id}')}")


def maybe_promote_unknown_dir(existing_dir, target_dir):
    if not existing_dir:
        return target_dir
    existing_dir = str(existing_dir)
    target_dir = str(target_dir)
    if os.path.abspath(existing_dir) == os.path.abspath(target_dir):
        return target_dir
    if not os.path.isdir(existing_dir):
        return target_dir
    if os.path.exists(target_dir):
        return target_dir
    ensure_dir(os.path.dirname(target_dir))
    try:
        os.replace(existing_dir, target_dir)
        return target_dir
    except Exception:
        return target_dir


def unique_file_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{base}__{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _format_size(num):
    if num is None:
        return "unknown"
    num = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PiB"


def download_file(url, out_path, headers=None, cookies=None, max_bytes=None):
    max_bytes = max_bytes or 0
    if requests:
        resp = requests.get(url, headers=headers, cookies=cookies, stream=True, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}")
        length = resp.headers.get("Content-Length") or resp.headers.get("content-length")
        if length and max_bytes and int(length) > max_bytes:
            resp.close()
            return "skipped", int(length)
        size = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if max_bytes and size > max_bytes:
                    resp.close()
                    f.close()
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                    return "skipped", size
                f.write(chunk)
        return "downloaded", size
    # urllib fallback
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        req.add_header("Cookie", cookie_str)
    with urllib.request.urlopen(req, timeout=30) as r:
        status = getattr(r, "status", 200)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} for {url}")
        length = r.headers.get("Content-Length")
        if length and max_bytes and int(length) > max_bytes:
            return "skipped", int(length)
        size = 0
        with open(out_path, "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes and size > max_bytes:
                    f.close()
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                    return "skipped", size
                f.write(chunk)
        return "downloaded", size


def parse_category_filters(raw_list):
    if not raw_list:
        return set()
    out = set()
    for raw in raw_list:
        if not raw:
            continue
        for part in str(raw).split(","):
            p = part.strip()
            if not p:
                continue
            out.add(canonical_category_name(p))
    return out


def read_preserved_lines(txt_path):
    if not os.path.exists(txt_path):
        return []
    keep_prefixes = (
        "容器地址:",
        "提交状态:",
        "提交结果:",
        "备注:",
        "Note:",
        "Manual:",
    )
    out = []
    try:
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.rstrip("\n")
                if any(s.startswith(p) for p in keep_prefixes):
                    out.append(s)
    except Exception:
        return []
    # unique while preserving order
    seen = set()
    dedup = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        dedup.append(s)
    return dedup


def main():
    ap = argparse.ArgumentParser(description="Fetch CTFd challenges and export to folders")
    ap.add_argument("--base", help="Base URL, e.g. https://ctfd.example/")
    ap.add_argument("--session", help="CTFd session cookie value")
    ap.add_argument("--token", help="CTFd API access token")
    ap.add_argument("--out", default="events/axiom2026", help="Output directory")
    ap.add_argument("--env-file", help="Custom .env path; default: <out>/.env")
    ap.add_argument("--rules-path", default="rules", help="Rules path, default: rules")
    ap.add_argument("--no-rules", action="store_true", help="Skip fetching rules for flag format")
    ap.add_argument("--flag-prefix", help="Fallback flag prefix, e.g. axiom")
    ap.add_argument("--include-solved", action="store_true", help="Also fetch challenges already solved_by_me")
    ap.add_argument("--category", action="append", help="Only fetch specified category (repeatable, comma-separated)")
    ap.add_argument("--categories", help="Comma-separated category list (alias of --category)")
    args = ap.parse_args()

    env_file = args.env_file or os.path.join(args.out, ".env")
    env_map = load_env_file(env_file)

    base = args.base or env_map.get("CTFD_BASE_URL", "")
    if not base.endswith("/"):
        base += "/"

    session = args.session or env_map.get("CTFD_SESSION", "")
    token = args.token or env_map.get("CTFD_TOKEN", "")

    if not session and not token:
        raise RuntimeError("Provide --session or --token for authentication")
    if not base:
        raise RuntimeError("Provide --base or set CTFD_BASE_URL in .env")

    cookies = {"session": session} if session else None
    headers = {"User-Agent": "ctfd-export/1.0"}
    if token:
        headers["Authorization"] = f"Token {token}"

    rules_plain = ""
    if not args.no_rules:
        rules_url = urljoin(base, args.rules_path.lstrip("/"))
        try:
            _status, rules_text, _data, _hdrs = http_get(rules_url, headers=headers, cookies=cookies, timeout=20)
            rules_plain = strip_html(rules_text)
        except Exception:
            rules_plain = ""

    challenges_url = urljoin(base, "api/v1/challenges")
    payload = http_get_json(challenges_url, headers=headers, cookies=cookies, timeout=20)
    if not payload.get("success"):
        raise RuntimeError("CTFd API returned success=false for challenges list")
    challenges = payload.get("data", [])

    ensure_dir(args.out)
    status_path = os.path.join(args.out, "status.json")
    prev_status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    prev_status = loaded
        except Exception:
            prev_status = {}
    existing_dirs = discover_existing_challenge_dirs(args.out)

    raw_filters = []
    if args.category:
        raw_filters.extend(args.category)
    if args.categories:
        raw_filters.append(args.categories)
    category_filters = parse_category_filters(raw_filters)

    total = len(challenges)
    status_index = dict(prev_status)
    for idx, ch in enumerate(challenges, start=1):
        ch_id = ch.get("id")
        if category_filters:
            ch_cat = canonical_category_name(ch.get("category", "Uncategorized"))
            if ch_cat == "Unknown":
                ch_cat = infer_category_from_tags(ch.get("tags") or [])
            if ch_cat not in category_filters:
                print(f"[{idx}/{total}] Skipping category {ch_cat} for challenge {ch_id}", flush=True)
                continue
        if ch.get("solved_by_me") and not args.include_solved:
            print(f"[{idx}/{total}] Skipping solved challenge {ch_id}", flush=True)
            # Preserve previous status if exists; otherwise keep minimal index entry.
            key = str(ch_id)
            existing_dir = existing_dirs.get(int(ch_id)) if ch_id is not None else None
            existing_category = existing_dir.parent.name if existing_dir is not None else ""
            if key not in status_index:
                status_index[key] = {
                    "id": ch_id,
                    "name": safe_name(ch.get("name", f"challenge-{ch_id}")),
                    "category": existing_category or canonical_category_name(ch.get("category", "Uncategorized")),
                    "solved_by_me": True,
                }
                if existing_dir is not None:
                    status_index[key]["challenge_dir"] = str(existing_dir)
            else:
                status_index[key]["solved_by_me"] = True
                if existing_category and canonical_category_name(status_index[key].get("category", "")) == "Unknown":
                    status_index[key]["category"] = existing_category
                if existing_dir is not None:
                    status_index[key]["challenge_dir"] = str(existing_dir)
            continue
        detail_url = urljoin(base, f"api/v1/challenges/{ch_id}")
        print(f"[{idx}/{total}] Fetching challenge {ch_id}...", flush=True)
        detail = http_get_json(detail_url, headers=headers, cookies=cookies, timeout=20)
        if not detail.get("success"):
            continue
        data = detail.get("data", {})

        prev_entry = dict(prev_status.get(str(ch_id), {}))
        name = safe_name(data.get("name", f"challenge-{ch_id}"))
        category = canonical_category_name(data.get("category", "Uncategorized"))
        if category == "Unknown":
            category = infer_category_from_tags(data.get("tags") or ch.get("tags") or [])
        prev_category = canonical_category_name(prev_entry.get("category", ""))
        existing_dir = existing_dirs.get(int(ch_id)) if ch_id is not None else None
        if category == "Unknown" and prev_category != "Unknown":
            category = prev_category
        existing_category = existing_dir.parent.name if existing_dir is not None else ""
        if existing_dir is not None and existing_category != "Unknown":
            category = existing_category
        if category_filters and category not in category_filters:
            print(f"[{idx}/{total}] Skipping category {category} for challenge {ch_id}", flush=True)
            continue
        description_html = data.get("description", "")
        description = strip_html(description_html).strip()
        connection_info = strip_html(data.get("connection_info", "") or "").strip()

        flag_format = find_flag_format(rules_plain, description, flag_prefix=args.flag_prefix)
        needs_container = is_container_challenge(data)

        chal_dir = challenge_dir_for(args.out, category, ch_id, name)
        if existing_dir is not None:
            if existing_category != "Unknown":
                chal_dir = str(existing_dir)
                category = existing_category
            elif category != "Unknown":
                promoted_dir = challenge_dir_for(args.out, category, ch_id, name)
                chal_dir = maybe_promote_unknown_dir(existing_dir, promoted_dir)
            else:
                chal_dir = str(existing_dir)
        ensure_dir(chal_dir)

        attachments = []
        attachments_dir = os.path.join(chal_dir, "attachments")
        ensure_dir(attachments_dir)
        files = data.get("files", []) or []
        for f in files:
            if not f:
                continue
            file_url = f if urlparse(f).scheme else urljoin(base, f.lstrip("/"))
            filename = os.path.basename(urlparse(file_url).path) or "attachment"
            safe_filename = safe_slug(filename, "attachment")
            out_path = unique_file_path(os.path.join(attachments_dir, safe_filename))
            try:
                print(f"  - downloading {file_url}", flush=True)
                status, size = download_file(
                    file_url,
                    out_path,
                    headers=headers,
                    cookies=cookies,
                    max_bytes=MAX_ATTACHMENT_BYTES,
                )
                if status == "skipped":
                    print(
                        f"  - skipped large file ({_format_size(size)}) {file_url}",
                        flush=True,
                    )
                    attachments.append(f"SKIPPED_LARGE:{file_url}")
                else:
                    attachments.append(os.path.abspath(out_path))
            except Exception:
                attachments.append(f"FAILED:{file_url}")

        txt_path = os.path.join(chal_dir, "challenge.txt")
        preserved = read_preserved_lines(txt_path)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"题目名称: {name}\n")
            f.write(f"类别: {category}\n")
            f.write(f"Flag 格式: {flag_format}\n")
            f.write(f"需要启动容器: {'是' if needs_container else '否'}\n")
            f.write("描述:\n")
            f.write(description + "\n")
            f.write("目标地址或附件:\n")
            if connection_info:
                f.write(connection_info + "\n")
            if attachments:
                for a in attachments:
                    f.write(f"- {a}\n")
            if preserved:
                for line in preserved:
                    f.write(line + "\n")

        merged = prev_entry
        merged.update({
            "id": ch_id,
            "name": name,
            "category": category,
            "solved_by_me": bool(data.get("solved_by_me", ch.get("solved_by_me", False))),
            "needs_container": needs_container,
            "connection_info": connection_info,
            "attachments": attachments,
            "challenge_dir": os.path.abspath(chal_dir),
        })
        status_index[str(ch_id)] = merged

    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status_index, f, ensure_ascii=False, indent=2)

    update_env_file(
        env_file,
        {
            "CTFD_BASE_URL": base,
            "CTFD_SESSION": session,
            "CTFD_TOKEN": token,
        },
    )

    print(f"Done. Output in {args.out}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
