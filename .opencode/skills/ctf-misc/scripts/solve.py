#!/usr/bin/env python3
"""
Misc helper:
- file scan (size/hash/strings)
- decode chain (base + compression)
- optional pcap quick summary via tshark
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import re
import subprocess
import sys
import urllib.parse
import zlib
from pathlib import Path


PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_file(path: Path, max_strings: int, min_len: int) -> int:
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    data = path.read_bytes()
    print(f"path: {path}")
    print(f"size: {len(data)}")
    print(f"sha256: {sha256_of(path)}")

    try:
      out = subprocess.check_output(["file", "-b", str(path)], text=True).strip()
      print(f"file_type: {out}")
    except Exception:
      pass

    strings = [m.group().decode("latin-1", errors="ignore") for m in PRINTABLE.finditer(data)]
    filtered = [s for s in strings if len(s) >= min_len]
    print(f"printable_strings: {len(filtered)}")
    for line in filtered[:max_strings]:
        print(f"str: {line}")

    return 0


def b58decode(data: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for ch in data:
        n = n * 58 + alphabet.index(ch)
    out = bytearray()
    while n > 0:
        n, rem = divmod(n, 256)
        out.append(rem)
    out.reverse()
    pad = 0
    for ch in data:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + bytes(out)


def decode_once(blob: bytes):
    candidates = []
    txt = blob.decode("latin-1", errors="ignore").strip()

    try:
        candidates.append(("hex", binascii.unhexlify(txt)))
    except Exception:
        pass

    try:
        candidates.append(("base64", base64.b64decode(txt, validate=True)))
    except Exception:
        pass

    try:
        candidates.append(("base32", base64.b32decode(txt, casefold=True)))
    except Exception:
        pass

    try:
        candidates.append(("base85", base64.b85decode(txt)))
    except Exception:
        pass

    try:
        if txt:
            candidates.append(("base58", b58decode(txt)))
    except Exception:
        pass

    try:
        candidates.append(("url", urllib.parse.unquote_to_bytes(txt)))
    except Exception:
        pass

    for name, fn in (("zlib", zlib.decompress), ("gzip", gzip.decompress)):
        try:
            candidates.append((name, fn(blob)))
        except Exception:
            pass

    return candidates


def decode_chain(text: str, depth: int) -> int:
    seen = set()
    queue = [("input", text.encode())]

    for step in range(depth):
        if not queue:
            break
        name, blob = queue.pop(0)
        key = (name, blob)
        if key in seen:
            continue
        seen.add(key)

        print(f"step={step} via={name} len={len(blob)}")
        preview = blob[:200].decode("latin-1", errors="ignore")
        print(f"preview={preview}")

        next_items = decode_once(blob)
        for item in next_items:
            queue.append(item)

    return 0


def pcap_summary(path: Path) -> int:
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    try:
        out = subprocess.check_output(["tshark", "-r", str(path), "-q", "-z", "io,phs"], text=True)
        print(out)
        return 0
    except FileNotFoundError:
        print("tshark not installed", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(exc.output, file=sys.stderr)
        return exc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Misc CTF helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="basic file scan")
    p_scan.add_argument("--input", required=True)
    p_scan.add_argument("--max-strings", type=int, default=40)
    p_scan.add_argument("--min-len", type=int, default=4)

    p_decode = sub.add_parser("decode", help="multi-step decode attempts")
    p_decode.add_argument("--text", required=True)
    p_decode.add_argument("--depth", type=int, default=8)

    p_pcap = sub.add_parser("pcap", help="tshark protocol summary")
    p_pcap.add_argument("--input", required=True)

    args = parser.parse_args()

    if args.cmd == "scan":
        return scan_file(Path(args.input), args.max_strings, args.min_len)
    if args.cmd == "decode":
        return decode_chain(args.text, args.depth)
    if args.cmd == "pcap":
        return pcap_summary(Path(args.input))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
