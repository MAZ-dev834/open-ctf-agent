#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path


BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")
B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+=*$")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
FLAG_RE = re.compile(r"[A-Za-z0-9_]{0,10}\\{[^}]{4,}\\}")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".zst", ".tgz", ".tbz", ".txz"}


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(cmd: list[str], timeout: int = 15) -> dict:
    exe = cmd[0]
    if shutil.which(exe) is None:
        return {"cmd": cmd, "rc": 127, "out": "", "err": f"{exe} not found"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {"cmd": cmd, "rc": proc.returncode, "out": proc.stdout, "err": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "rc": 124, "out": "", "err": f"timeout>{timeout}s"}


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


def pick_project_files(project: Path, max_files: int = 200) -> list[Path]:
    roots = [
        project,
        project / "attachments",
        project / "attachments" / "extracted",
        project / "题目附件",
        project / "题目附件" / "extracted",
    ]
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in iter_candidate_files(root):
            rp = str(p.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            out.append(p)
            if len(out) >= max_files:
                return out
    return out


def analyze_text(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lengths = [len(ln) for ln in lines]
    printable = sum(ch.isprintable() for ch in text)
    printable_ratio = printable / max(1, len(text))

    base64_lines = [ln for ln in lines if len(ln) >= 16 and BASE64_RE.match(ln)]
    b64url_lines = [ln for ln in lines if len(ln) >= 16 and B64URL_RE.match(ln)]
    hex_lines = [ln for ln in lines if len(ln) >= 16 and HEX_RE.match(ln) and len(ln) % 2 == 0]
    big_ints = re.findall(r"\b\d{40,}\b", text)
    hex_blobs = re.findall(r"\b[0-9a-fA-F]{32,}\b", text)
    urls = URL_RE.findall(text)
    flag_hits = FLAG_RE.findall(text)

    hints: list[str] = []
    if base64_lines or b64url_lines:
        hints.append("base64_like_lines")
    if hex_lines or hex_blobs:
        hints.append("hex_like_data")
    if big_ints:
        hints.append("big_integers_present")
    if urls:
        hints.append("urls_present")
    if flag_hits:
        hints.append("flag_pattern_present")

    line_stats = {
        "lines": len(lines),
        "avg_len": round(sum(lengths) / max(1, len(lengths)), 2) if lengths else 0,
        "min_len": min(lengths) if lengths else 0,
        "max_len": max(lengths) if lengths else 0,
        "unique_lengths": len(set(lengths)),
    }

    return {
        "printable_ratio": round(printable_ratio, 3),
        "line_stats": line_stats,
        "base64_lines": len(base64_lines),
        "b64url_lines": len(b64url_lines),
        "hex_lines": len(hex_lines),
        "big_ints": len(big_ints),
        "hex_blobs": len(hex_blobs),
        "urls": len(urls),
        "flag_hits": len(flag_hits),
        "hints": hints,
    }


def strings_sample(path: Path, min_len: int = 6, limit: int = 120) -> dict | None:
    res = run_cmd(["strings", "-n", str(min_len), str(path)], timeout=20)
    lines = res["out"].splitlines() if res["out"] else []
    return {
        "cmd": res.get("cmd"),
        "rc": res.get("rc"),
        "err": res.get("err"),
        "total_lines": len(lines),
        "sample": lines[:limit],
    }


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


def analyze_file(path: Path, max_read: int = 512 * 1024) -> dict:
    size = path.stat().st_size
    file_type = run_cmd(["file", "-b", str(path)])
    entry = {
        "path": str(path.resolve()),
        "size_bytes": size,
        "sha256": sha256sum(path),
        "file": file_type,
        "text": None,
        "strings": None,
        "exiftool": None,
        "binwalk": None,
    }

    if size <= max_read:
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            entry["text"] = analyze_text(text)
        except Exception:
            entry["text"] = None

    if size <= 10 * 1024 * 1024:
        entry["strings"] = strings_sample(path, min_len=6, limit=120)

    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        exif = run_cmd(["exiftool", str(path)], timeout=20)
        exif["out"] = truncate(exif.get("out", ""))
        exif["err"] = truncate(exif.get("err", ""))
        entry["exiftool"] = exif

    if ext in ARCHIVE_EXTS and size <= 25 * 1024 * 1024:
        bw = run_cmd(["binwalk", str(path)], timeout=30)
        bw["out"] = truncate(bw.get("out", ""))
        bw["err"] = truncate(bw.get("err", ""))
        entry["binwalk"] = bw

    return entry


def main() -> int:
    p = argparse.ArgumentParser(description="Quick misc scan for files, strings, and light metadata.")
    p.add_argument("--project", default="", help="Project directory to scan")
    p.add_argument("--input", default="", help="File or directory to scan")
    p.add_argument("--out-dir", default="", help="Output directory (default: <project>/artifacts)")
    p.add_argument("--max-files", type=int, default=200)
    args = p.parse_args()

    files: list[Path] = []
    project = Path(args.project).expanduser().resolve() if args.project else None

    if args.input:
        inp = Path(args.input).expanduser().resolve()
        if inp.is_dir():
            files = iter_candidate_files(inp)
        elif inp.is_file():
            files = [inp]
        else:
            raise SystemExit(f"input not found: {inp}")
    elif project:
        files = pick_project_files(project, max_files=args.max_files)
    else:
        raise SystemExit("provide --project or --input")

    files = files[: args.max_files]
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    if out_dir is None:
        if not project:
            raise SystemExit("provide --out-dir when --project is not set")
        out_dir = project / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = [analyze_file(p) for p in files]
    hints = Counter()
    for r in results:
        if r.get("text") and r["text"].get("hints"):
            hints.update(r["text"]["hints"])

    payload = {
        "files_scanned": len(results),
        "hint_summary": dict(hints),
        "results": results,
    }

    json_path = out_dir / "misc_quick_scan.json"
    txt_path = out_dir / "misc_quick_scan.txt"
    json_path.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        f"files_scanned: {payload['files_scanned']}",
        f"hint_summary: {payload['hint_summary']}",
        "",
    ]
    for r in results:
        lines.append(f"- {r['path']} ({r['size_bytes']} bytes)")
        lines.append(f"  file: {r['file']['out'].strip()}")
        if r.get("text"):
            t = r["text"]
            lines.append(f"  hints: {', '.join(t['hints']) if t['hints'] else 'none'}")
            ls = t["line_stats"]
            lines.append(f"  lines: {ls['lines']} avg_len:{ls['avg_len']} min:{ls['min_len']} max:{ls['max_len']} unique:{ls['unique_lengths']}")
            lines.append(
                f"  base64_lines:{t['base64_lines']} b64url_lines:{t['b64url_lines']} hex_lines:{t['hex_lines']} "
                f"big_ints:{t['big_ints']} hex_blobs:{t['hex_blobs']} urls:{t['urls']} flag_hits:{t['flag_hits']}"
            )
        if r.get("strings") and r["strings"]["sample"]:
            lines.append(f"  strings_sample: {len(r['strings']['sample'])} lines")
        if r.get("exiftool"):
            lines.append(f"  exiftool_rc: {r['exiftool']['rc']}")
        if r.get("binwalk"):
            lines.append(f"  binwalk_rc: {r['binwalk']['rc']}")
        lines.append("")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[+] misc_quick_scan: {json_path}")
    print(f"[+] misc_quick_scan_txt: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
