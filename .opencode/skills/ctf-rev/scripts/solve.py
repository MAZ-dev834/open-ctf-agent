#!/usr/bin/env python3
"""
General reverse helper:
- extract printable strings
- brute-force single-byte XOR
- recover short repeating XOR keys
"""

from __future__ import annotations

import argparse
import itertools
import re
from pathlib import Path


PRINTABLE = set(range(32, 127)) | {9, 10, 13}


def load_data(path: str) -> bytes:
    return Path(path).read_bytes()


def printable_score(blob: bytes) -> float:
    if not blob:
        return 0.0
    ok = sum(1 for b in blob if b in PRINTABLE)
    return ok / len(blob)


def extract_strings(data: bytes, min_len: int) -> list[str]:
    out: list[str] = []
    cur = bytearray()
    for b in data:
        if b in PRINTABLE and b not in (10, 13):
            cur.append(b)
            continue
        if len(cur) >= min_len:
            out.append(cur.decode("latin-1", errors="ignore"))
        cur.clear()
    if len(cur) >= min_len:
        out.append(cur.decode("latin-1", errors="ignore"))
    return out


def xor_with_key(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def run_strings(args: argparse.Namespace) -> int:
    data = load_data(args.input)
    for line in extract_strings(data, args.min_len):
        print(line)
    return 0


def run_xor_single(args: argparse.Namespace) -> int:
    data = load_data(args.input)
    regex = re.compile(args.regex) if args.regex else None

    ranked = []
    for key in range(256):
        plain = xor_with_key(data, bytes([key]))
        score = printable_score(plain)
        text = plain.decode("latin-1", errors="ignore")
        if regex and not regex.search(text):
            continue
        ranked.append((score, key, plain))

    ranked.sort(reverse=True, key=lambda x: x[0])

    if not ranked:
        print("no candidate")
        return 1

    for score, key, plain in ranked[: args.top]:
        print(f"key=0x{key:02x} score={score:.3f}")
        print(plain.decode("latin-1", errors="ignore"))
        print("-" * 60)

    return 0


def top_key_bytes(slice_data: bytes, beam_width: int) -> list[int]:
    scored = []
    for k in range(256):
        plain = bytes(b ^ k for b in slice_data)
        scored.append((printable_score(plain), k))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [k for _, k in scored[:beam_width]]


def run_xor_repeat(args: argparse.Namespace) -> int:
    data = load_data(args.input)
    regex = re.compile(args.regex) if args.regex else None

    best = []
    for key_len in range(args.min_key_len, args.max_key_len + 1):
        key_choices = []
        for pos in range(key_len):
            part = data[pos::key_len]
            key_choices.append(top_key_bytes(part, args.beam_width))

        for combo in itertools.product(*key_choices):
            key = bytes(combo)
            plain = xor_with_key(data, key)
            text = plain.decode("latin-1", errors="ignore")
            score = printable_score(plain)
            if regex and not regex.search(text):
                continue
            best.append((score, key, text))

    best.sort(reverse=True, key=lambda x: x[0])

    if not best:
        print("no candidate")
        return 1

    for score, key, text in best[: args.top]:
        print(f"key={key!r} score={score:.3f}")
        print(text)
        print("-" * 60)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reverse helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_strings = sub.add_parser("strings", help="extract printable strings")
    p_strings.add_argument("--input", required=True)
    p_strings.add_argument("--min-len", type=int, default=4)
    p_strings.set_defaults(func=run_strings)

    p_single = sub.add_parser("xor-single", help="bruteforce single-byte xor")
    p_single.add_argument("--input", required=True)
    p_single.add_argument("--top", type=int, default=5)
    p_single.add_argument("--regex", default="")
    p_single.set_defaults(func=run_xor_single)

    p_repeat = sub.add_parser("xor-repeat", help="recover short repeating xor keys")
    p_repeat.add_argument("--input", required=True)
    p_repeat.add_argument("--min-key-len", type=int, default=2)
    p_repeat.add_argument("--max-key-len", type=int, default=4)
    p_repeat.add_argument("--beam-width", type=int, default=4)
    p_repeat.add_argument("--top", type=int, default=5)
    p_repeat.add_argument("--regex", default="")
    p_repeat.set_defaults(func=run_xor_repeat)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
