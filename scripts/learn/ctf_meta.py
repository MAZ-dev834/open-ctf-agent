#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

CATEGORY_SET = {"web", "pwn", "crypto", "rev", "misc", "forensics", "osint", "malware", "unknown"}
CATEGORY_SET_FALLBACK = CATEGORY_SET
CANONICAL_CATEGORIES = CATEGORY_SET_FALLBACK
CATEGORY_MAP = {
    "hardware": ("forensics", "hardware"),
    "hw": ("forensics", "hardware"),
    "osint": ("osint", "osint"),
    "forensics": ("forensics", "forensics"),
    "forensic": ("forensics", "forensics"),
    "digital-forensics": ("forensics", "forensics"),
    "stego": ("forensics", "stego"),
    "steganography": ("forensics", "stego"),
    "malware": ("malware", "malware"),
    "miscellaneous": ("misc", "miscellaneous"),
    "web exploitation": ("web", "web-exploitation"),
    "reverse engineering": ("rev", "reverse-engineering"),
    "cryptography": ("crypto", "cryptography"),
    "ai": ("misc", "ai"),
    "machine learning": ("misc", "ai"),
    "ml": ("misc", "ai"),
}


def normalize_project_key(name: str) -> str:
    return re.sub(r"_\d{8}_\d{6}$", "", str(name or "").strip())


def map_category(raw: str) -> tuple[str, str]:
    raw_norm = str(raw or "").strip().lower()
    if raw_norm in CANONICAL_CATEGORIES:
        return raw_norm, ""
    mapped = CATEGORY_MAP.get(raw_norm)
    if mapped:
        return mapped
    return "unknown", ""


def parse_category_from_text(text: str) -> str:
    if not text:
        return ""
    pats = [
        r"(?:^|\n)\s*(?:[-*]\s*)?(?:category(?:\s*\(if known\))?|类别)\s*[:：]\s*([A-Za-z0-9_ -]+)",
        r"(?:^|\n)\s*(?:[-*]\s*)?(?:type|题型)\s*[:：]\s*([A-Za-z0-9_-]+)",
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1).strip()
    return ""


def load_category_meta(project_dir: Path, read_text_func) -> tuple[str, str, str, str]:
    # category, raw_category, sub_category, source_path
    candidates = [
        project_dir / "challenge.json",
        project_dir / "task.json",
        project_dir / "challenge.txt",
        project_dir / "attachments" / "challenge.txt",
        project_dir / "题目附件" / "challenge.txt",
        project_dir / "attachments" / "challenge.json",
        project_dir / "题目附件" / "challenge.json",
    ]
    for meta in candidates:
        if not meta.exists():
            continue
        raw_category = ""
        try:
            if meta.suffix.lower() == ".json":
                data = json.loads(meta.read_text(encoding="utf-8"))
                raw_category = str(data.get("category", "")).strip()
            else:
                raw_category = parse_category_from_text(
                    meta.read_text(encoding="utf-8", errors="ignore")
                )
        except Exception:
            raw_category = ""
        if raw_category:
            category, sub_category = map_category(raw_category)
            return (
                category,
                raw_category.lower(),
                sub_category,
                str(meta.relative_to(project_dir)),
            )

    writeup = project_dir / "writeup.md"
    text = read_text_func(writeup)
    if text:
        raw_category = parse_category_from_text(text)
        if raw_category:
            category, sub_category = map_category(raw_category)
            return category, raw_category.lower(), sub_category, "writeup.md"
        low = text.lower()
        if re.search(r"(hardware|fpga|uart|jtag|spi|i2c|side[ -]?channel|logic analyzer)", low):
            return "forensics", "inferred_hardware", "hardware", "writeup.md"
        if re.search(r"(osint|geolocation|username|whois|archive\.org|metadata hunt)", low):
            return "osint", "inferred_osint", "osint", "writeup.md"
        if re.search(r"(malware|packed|obfus|ransomware|c2|beacon|dropper|process injection)", low):
            return "malware", "inferred_malware", "malware", "writeup.md"
        if re.search(r"(forensics?|disk image|volatility|memory dump|pcap)", low):
            return "forensics", "inferred_forensics", "forensics", "writeup.md"
        if re.search(
            r"(http|cookie|csrf|jwt|xss|sqli|ssti|ssrf|upload|path traversal|lfi|rfi)",
            low,
        ):
            return "web", "inferred_web", "", "writeup.md"
        if re.search(
            r"(heap|tcache|uaf|format string|rop|got|plt|canary|pie|aslr|libc)", low
        ):
            return "pwn", "inferred_pwn", "", "writeup.md"
        if re.search(
            r"(rsa|aes|prng|mt19937|lattice|lll|ecc|feistel|galois|gf\()", low
        ):
            return "crypto", "inferred_crypto", "", "writeup.md"
        if re.search(r"(ghidra|radare|xrefs|decompile|obfusc|packer|reverse)", low):
            return "rev", "inferred_rev", "", "writeup.md"
        if re.search(r"(pcap|stego|forensics|binwalk|exif|wireshark)", low):
            return "forensics", "inferred_forensics", "forensics", "writeup.md"
    path_low = str(project_dir).lower()
    if "/hardware/" in path_low:
        return "forensics", "path_hardware", "hardware", "."
    if "/osint/" in path_low:
        return "osint", "path_osint", "osint", "."
    if "/forensics/" in path_low:
        return "forensics", "path_forensics", "forensics", "."
    if "/malware/" in path_low:
        return "malware", "path_malware", "malware", "."
    if "/web exploitation/" in path_low or "/web/" in path_low:
        return "web", "path_web", "web-exploitation", "."
    if "/reverse engineering/" in path_low or "/rev/" in path_low:
        return "rev", "path_rev", "reverse-engineering", "."
    if "/cryptography/" in path_low or "/crypto/" in path_low:
        return "crypto", "path_crypto", "cryptography", "."
    if "/miscellaneous/" in path_low or "/misc/" in path_low:
        return "misc", "path_misc", "miscellaneous", "."
    return "unknown", "unknown", "", ""
