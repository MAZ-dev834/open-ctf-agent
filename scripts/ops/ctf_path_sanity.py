#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def is_suspicious_name(name: str, max_name_len: int) -> list[str]:
    issues: list[str] = []
    if len(name) > max_name_len:
        issues.append(f"name_too_long>{max_name_len}")
    if any(ord(ch) < 32 for ch in name):
        issues.append("contains_control_chars")
    if "\n" in name or "\r" in name or "\t" in name:
        issues.append("contains_whitespace_escape")
    if name.startswith("Usage: dirname"):
        issues.append("looks_like_command_help_output")
    if name.strip() != name:
        issues.append("leading_or_trailing_spaces")
    return issues


def scan_tree(root: Path, max_name_len: int = 160, max_depth: int = 3) -> list[dict]:
    findings: list[dict] = []
    root = root.resolve()
    for base, dirs, files in os.walk(root):
        rel_depth = len(Path(base).resolve().relative_to(root).parts)
        if rel_depth > max_depth:
            dirs[:] = []
            continue
        for name in list(dirs) + list(files):
            tags = is_suspicious_name(name, max_name_len)
            if not tags:
                continue
            p = Path(base) / name
            findings.append(
                {
                    "path": str(p),
                    "relative": str(p.resolve().relative_to(root)),
                    "kind": "dir" if p.is_dir() else "file",
                    "issues": tags,
                }
            )
    findings.sort(key=lambda x: x["relative"])
    return findings


def category_key(name: str) -> str:
    low = str(name or "").strip().lower()
    low = re.sub(r"\s+", " ", low)
    aliases = {
        "web exploitation": "web",
        "web": "web",
        "binary exploitation": "pwn",
        "pwn": "pwn",
        "reverse engineering": "rev",
        "rev": "rev",
        "cryptography": "crypto",
        "crypto": "crypto",
        "miscellaneous": "misc",
        "misc": "misc",
        "forensics": "forensics",
        "malware": "malware",
        "osint": "osint",
    }
    return aliases.get(low, low)


def discover_event_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    events_root = root / "events"
    if events_root.exists():
        for d in events_root.iterdir():
            if d.is_dir() and (d / "status.json").exists():
                out.append(d)
    for d in root.iterdir():
        if d.is_dir() and (d / "status.json").exists():
            out.append(d)
    seen: set[str] = set()
    uniq = []
    for d in out:
        rp = str(d.resolve())
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(d)
    return sorted(uniq)


def scan_event_category_issues(root: Path) -> list[dict]:
    findings: list[dict] = []
    ignore_names = {".locks"}
    bad_names = {"???", "uncategorized"}
    for event_dir in discover_event_dirs(root):
        by_key: dict[str, list[str]] = {}
        for cat_dir in sorted(event_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            if cat_dir.name in ignore_names:
                continue
            key = category_key(cat_dir.name)
            by_key.setdefault(key, []).append(cat_dir.name)
            if cat_dir.name.strip().lower() in bad_names:
                findings.append(
                    {
                        "path": str(cat_dir),
                        "relative": str(cat_dir.resolve().relative_to(root.resolve())),
                        "kind": "dir",
                        "issues": ["ambiguous_category_name"],
                    }
                )
        for key, names in by_key.items():
            uniq = sorted(set(names))
            if len(uniq) <= 1:
                continue
            findings.append(
                {
                    "path": str(event_dir),
                    "relative": str(event_dir.resolve().relative_to(root.resolve())),
                    "kind": "dir",
                    "issues": [f"category_alias_conflict:{key}:{'|'.join(uniq)}"],
                }
            )
    return findings


def main() -> int:
    p = argparse.ArgumentParser(description="Scan workspace for suspicious path names.")
    p.add_argument("--root", default=".")
    p.add_argument("--max-name-len", type=int, default=160)
    p.add_argument("--max-depth", type=int, default=3)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    root = Path(args.root)
    findings = scan_tree(root, max_name_len=args.max_name_len, max_depth=args.max_depth)
    findings.extend(scan_event_category_issues(root))
    findings.sort(key=lambda x: x["relative"])
    if args.json:
        print(json.dumps({"root": str(root.resolve()), "issues": findings}, ensure_ascii=False))
    else:
        print("== Path Sanity ==")
        print(f"- root: {root.resolve()}")
        print(f"- issues: {len(findings)}")
        for it in findings:
            print(f"- {it['relative']} [{it['kind']}] -> {','.join(it['issues'])}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
