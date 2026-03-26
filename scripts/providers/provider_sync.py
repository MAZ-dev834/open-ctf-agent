#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests  # type: ignore
except Exception:
    requests = None

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    except Exception:
        return {}
    return out


def update_env_file(path: Path, updates: dict) -> None:
    current = load_env_file(path)
    for k, v in updates.items():
        if v is None or v == "":
            continue
        current[k] = str(v)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for k in sorted(current.keys()):
            f.write(f"{k}={current[k]}\n")


def http_get_json(url: str, headers: dict | None = None, timeout: int = 20) -> dict | list:
    if requests:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read().decode("utf-8", errors="replace")
        return json.loads(data)


def http_get_bytes(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    if requests:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def safe_name(name: str) -> str:
    name = name.replace(os.sep, " ").replace("/", " ").replace("\\", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def canonical_category(raw: str) -> str:
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
        "forensics": "Misc",
        "hardware": "Misc",
        "stego": "Misc",
        "steganography": "Misc",
        "osint": "OSINT",
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
    if "osint" in low:
        return "OSINT"
    if any(x in low for x in ("misc", "forensic", "hardware", "stego")):
        return "Misc"
    return text or "Unknown"


def extract_path(obj, path: str):
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def make_headers(token: str, auth_header: str, token_prefix: str, extra: dict | None) -> dict:
    headers = {}
    if token:
        headers[auth_header] = f"{token_prefix}{token}"
    if extra:
        headers.update(extra)
    return headers


def build_challenge_dir(out_root: Path, category: str, cid: str, name: str) -> Path:
    safe_cat = canonical_category(category)
    safe_title = safe_name(name)
    dir_name = f"{cid} - {safe_title}" if cid else safe_title
    return out_root / safe_cat / dir_name


def write_challenge_txt(ch_dir: Path, meta: dict) -> None:
    lines = []
    lines.append(f"题目名称: {meta.get('name','')}")
    lines.append(f"类别: {meta.get('category','')}")
    flag_fmt = meta.get("flag_format") or ""
    lines.append(f"Flag 格式: {flag_fmt}")
    needs_container = "是" if meta.get("needs_container") else "否"
    lines.append(f"需要启动容器: {needs_container}")
    if meta.get("instance_url"):
        lines.append(f"容器地址: {meta.get('instance_url')}")
    lines.append("描述:")
    lines.append(meta.get("description", ""))
    lines.append("")
    lines.append("目标地址或附件:")
    for item in meta.get("target_or_attachments") or []:
        lines.append(f"- {item}")
    ch_dir.mkdir(parents=True, exist_ok=True)
    (ch_dir / "challenge.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def download_attachments(attachments: list, ch_dir: Path, headers: dict) -> list:
    if not attachments:
        return []
    out_dir = ch_dir / "attachments"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in attachments:
        if not isinstance(item, str):
            continue
        if item.startswith("http://") or item.startswith("https://"):
            name = item.split("/")[-1] or "attachment.bin"
            path = out_dir / name
            try:
                data = http_get_bytes(item, headers=headers)
                path.write_bytes(data)
                saved.append(str(path))
            except Exception:
                saved.append(item)
        else:
            saved.append(item)
    return saved


def sync_custom_provider(out_root: Path, config: dict) -> None:
    base = str(config.get("base_url") or "")
    list_url = str(config.get("list_url") or "")
    if base and list_url and not list_url.startswith("http"):
        list_url = urljoin(base, list_url)
    if not list_url:
        raise RuntimeError("custom provider missing list_url")
    detail_url = str(config.get("detail_url") or "")
    if base and detail_url and not detail_url.startswith("http"):
        detail_url = urljoin(base, detail_url)
    auth_header = str(config.get("auth_header") or "Authorization")
    token_prefix = str(config.get("token_prefix") or "Bearer ")
    token = str(config.get("token") or "")
    extra_headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    headers = make_headers(token, auth_header, token_prefix, extra_headers)
    list_path = str(config.get("list_path") or "")
    detail_path = str(config.get("detail_path") or "")
    field_map = config.get("field_map") if isinstance(config.get("field_map"), dict) else {}

    raw_list = http_get_json(list_url, headers=headers)
    items = extract_path(raw_list, list_path) if list_path else raw_list
    if not isinstance(items, list):
        raise RuntimeError("list response is not a list (set list_path)")

    status = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ch = item
        if detail_url:
            cid = item.get(field_map.get("id", "id")) if field_map else item.get("id")
            if cid is not None:
                url = detail_url.replace("{id}", str(cid))
                raw_detail = http_get_json(url, headers=headers)
                detail = extract_path(raw_detail, detail_path) if detail_path else raw_detail
                if isinstance(detail, dict):
                    ch = detail

        def pick(key, default=""):
            field = field_map.get(key, key)
            return ch.get(field, default)

        cid = str(pick("id", ""))
        name = str(pick("name", ""))
        category = str(pick("category", "Unknown"))
        description = str(pick("description", ""))
        target = str(pick("target", ""))
        attachments = pick("attachments", []) or []
        status_val = str(pick("status", "unsolved"))
        tags = pick("tags", []) or []
        author = str(pick("author", ""))

        ch_dir = build_challenge_dir(out_root, category, cid, name)
        meta = {
            "name": name,
            "category": category,
            "flag_format": pick("flag_format", ""),
            "needs_container": bool(pick("needs_container", False)),
            "instance_url": pick("instance_url", ""),
            "description": description,
            "target_or_attachments": [target] if target else [],
        }
        write_challenge_txt(ch_dir, meta)
        saved_attachments = download_attachments(attachments if isinstance(attachments, list) else [], ch_dir, headers)

        status[str(cid)] = {
            "id": cid,
            "name": name,
            "category": category,
            "challenge_dir": str(ch_dir),
            "description": description,
            "target": target,
            "attachments": saved_attachments,
            "status": status_val,
            "tags": tags if isinstance(tags, list) else [str(tags)],
            "author": author,
        }

    (out_root / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_ctfd_sync(args, out_root: Path, env_file: Path) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "ctfd" / "fetch_ctfd.py"),
        "--out",
        str(out_root),
        "--env-file",
        str(env_file),
    ]
    if args.base:
        cmd.extend(["--base", args.base])
    if args.session:
        cmd.extend(["--session", args.session])
    if args.token:
        cmd.extend(["--token", args.token])
    if args.flag_prefix:
        cmd.extend(["--flag-prefix", args.flag_prefix])
    os.execv(sys.executable, cmd)


def main() -> int:
    p = argparse.ArgumentParser(description="Sync challenges from provider into events/<event>")
    p.add_argument("--event", required=True, help="Event name, e.g. democtf2026")
    p.add_argument("--out-root", default="events", help="Events root directory")
    p.add_argument("--provider", default="", help="Provider name: ctfd|custom")
    p.add_argument("--base", default="", help="CTFd base URL")
    p.add_argument("--session", default="", help="CTFd session cookie value")
    p.add_argument("--token", default="", help="CTFd API token")
    p.add_argument("--flag-prefix", default="", help="Flag prefix fallback")
    p.add_argument("--config", default="", help="Custom provider config path (json)")
    args = p.parse_args()

    out_root = Path(args.out_root).resolve() / args.event
    out_root.mkdir(parents=True, exist_ok=True)
    env_file = out_root / ".env"
    env = load_env_file(env_file)

    provider = args.provider or env.get("PROVIDER", "ctfd")
    if provider == "ctfd":
        updates = {}
        if args.base:
            updates["CTFD_BASE_URL"] = args.base
        if args.session:
            updates["CTFD_SESSION"] = args.session
        if args.token:
            updates["CTFD_TOKEN"] = args.token
        if args.flag_prefix:
            updates["CTFD_FLAG_PREFIX"] = args.flag_prefix
        # Submission safety defaults (can be overridden later)
        updates.setdefault("SUBMIT_COOLDOWN_SEC", env.get("SUBMIT_COOLDOWN_SEC", "600"))
        updates.setdefault("MAX_INCORRECT_PER_CHALLENGE", env.get("MAX_INCORRECT_PER_CHALLENGE", "3"))
        updates.setdefault("MAX_SUBMISSIONS_PER_CHALLENGE", env.get("MAX_SUBMISSIONS_PER_CHALLENGE", "10"))
        updates.setdefault("MAX_SUBMISSIONS_TOTAL", env.get("MAX_SUBMISSIONS_TOTAL", "200"))
        updates.setdefault("SUBMIT_MIN_INTERVAL_SEC", env.get("SUBMIT_MIN_INTERVAL_SEC", "20"))
        updates["PROVIDER"] = "ctfd"
        update_env_file(env_file, updates)
        run_ctfd_sync(args, out_root, env_file)
        return 0

    if provider == "custom":
        cfg_path = Path(args.config) if args.config else (out_root / "provider.json")
        if not cfg_path.exists():
            raise SystemExit(f"custom provider missing config: {cfg_path}")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sync_custom_provider(out_root, cfg)
        updates = {"PROVIDER": "custom"}
        updates.setdefault("SUBMIT_COOLDOWN_SEC", env.get("SUBMIT_COOLDOWN_SEC", "600"))
        updates.setdefault("MAX_INCORRECT_PER_CHALLENGE", env.get("MAX_INCORRECT_PER_CHALLENGE", "3"))
        updates.setdefault("MAX_SUBMISSIONS_PER_CHALLENGE", env.get("MAX_SUBMISSIONS_PER_CHALLENGE", "10"))
        updates.setdefault("MAX_SUBMISSIONS_TOTAL", env.get("MAX_SUBMISSIONS_TOTAL", "200"))
        updates.setdefault("SUBMIT_MIN_INTERVAL_SEC", env.get("SUBMIT_MIN_INTERVAL_SEC", "20"))
        update_env_file(env_file, updates)
        return 0

    raise SystemExit(f"unsupported provider: {provider}")


if __name__ == "__main__":
    raise SystemExit(main())
