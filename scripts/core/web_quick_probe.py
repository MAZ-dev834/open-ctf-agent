#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def iter_candidate_files(root: Path) -> list[Path]:
    skip_dirs = {"__pycache__", ".git", "artifacts", "logs"}
    out: list[Path] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            p = Path(base) / name
            if p.is_file():
                out.append(p)
    return out


def find_urls(project: Path, max_files: int = 200, max_read: int = 512 * 1024) -> list[str]:
    urls: list[str] = []
    for p in iter_candidate_files(project)[:max_files]:
        try:
            if p.stat().st_size > max_read:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for url in URL_RE.findall(text):
            if url not in urls:
                urls.append(url)
    return urls


def fetch(url: str, method: str = "GET", max_bytes: int = 4096, timeout: int = 6) -> dict:
    req = Request(
        url,
        method=method,
        headers={"User-Agent": "ctf-web-quick-probe/1.0"},
    )
    start = time.time()
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes) if method != "HEAD" else b""
            elapsed = round(time.time() - start, 3)
            body_hash = hashlib.sha256(body).hexdigest() if body else ""
            return {
                "url": url,
                "final_url": resp.geturl(),
                "status": resp.getcode(),
                "headers": dict(resp.headers),
                "elapsed_sec": elapsed,
                "body_bytes": len(body),
                "body_sha256": body_hash,
                "body_sample": body.decode("utf-8", errors="replace"),
                "error": "",
            }
    except HTTPError as e:
        body = b""
        try:
            body = e.read(max_bytes)
        except Exception:
            body = b""
        elapsed = round(time.time() - start, 3)
        body_hash = hashlib.sha256(body).hexdigest() if body else ""
        return {
            "url": url,
            "final_url": getattr(e, "url", url),
            "status": e.code,
            "headers": dict(e.headers) if getattr(e, "headers", None) else {},
            "elapsed_sec": elapsed,
            "body_bytes": len(body),
            "body_sha256": body_hash,
            "body_sample": body.decode("utf-8", errors="replace"),
            "error": f"HTTPError: {e}",
        }
    except URLError as e:
        elapsed = round(time.time() - start, 3)
        return {
            "url": url,
            "final_url": url,
            "status": 0,
            "headers": {},
            "elapsed_sec": elapsed,
            "body_bytes": 0,
            "body_sha256": "",
            "body_sample": "",
            "error": f"URLError: {e}",
        }
    except Exception as e:
        elapsed = round(time.time() - start, 3)
        return {
            "url": url,
            "final_url": url,
            "status": 0,
            "headers": {},
            "elapsed_sec": elapsed,
            "body_bytes": 0,
            "body_sha256": "",
            "body_sample": "",
            "error": f"Error: {e}",
        }


def build_probe_urls(base_url: str) -> list[str]:
    base = base_url.strip()
    if not base:
        return []
    if not urlparse(base).scheme:
        base = "http://" + base
    base = base.rstrip("/") + "/"
    paths = ["", "robots.txt", "sitemap.xml", ".well-known/security.txt"]
    return [urljoin(base, p) for p in paths]


def main() -> int:
    p = argparse.ArgumentParser(description="Quick web probe (GET base/robots/sitemap).")
    p.add_argument("--url", default="", help="Target base URL")
    p.add_argument("--url-file", default="", help="File containing URLs (one per line)")
    p.add_argument("--project", default="", help="Project directory to scan for URLs")
    p.add_argument("--out-dir", default="", help="Output directory (default: <project>/artifacts)")
    p.add_argument("--max-bytes", type=int, default=4096)
    p.add_argument("--max-files", type=int, default=200)
    args = p.parse_args()

    urls: list[str] = []
    if args.url:
        urls.append(args.url.strip())
    if args.url_file:
        uf = Path(args.url_file).expanduser().resolve()
        if not uf.exists():
            raise SystemExit(f"url file not found: {uf}")
        for line in uf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    project = Path(args.project).expanduser().resolve() if args.project else None
    if project:
        urls.extend(find_urls(project, max_files=args.max_files))

    # de-dup preserving order
    seen: set[str] = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]

    if not urls:
        raise SystemExit("no URL found; provide --url or --url-file")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    if out_dir is None:
        if not project:
            raise SystemExit("provide --out-dir when --project is not set")
        out_dir = project / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    probes: list[dict] = []
    for base_url in urls:
        for target in build_probe_urls(base_url):
            probes.append(fetch(target, method="GET", max_bytes=args.max_bytes))

    payload = {"base_urls": urls, "probes": probes}

    json_path = out_dir / "web_quick_probe.json"
    txt_path = out_dir / "web_quick_probe.txt"
    json_path.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = []
    for base_url in urls:
        lines.append(f"base_url: {base_url}")
    lines.append("")
    for pinfo in probes:
        lines.append(f"- {pinfo['url']}")
        lines.append(f"  status: {pinfo['status']} elapsed_sec: {pinfo['elapsed_sec']}")
        if pinfo.get("error"):
            lines.append(f"  error: {pinfo['error']}")
        ct = pinfo.get("headers", {}).get("Content-Type") or pinfo.get("headers", {}).get("content-type") or ""
        if ct:
            lines.append(f"  content_type: {ct}")
        lines.append(f"  body_bytes: {pinfo['body_bytes']} sha256: {pinfo['body_sha256']}")
        lines.append("")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[+] web_quick_probe: {json_path}")
    print(f"[+] web_quick_probe_txt: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
