#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Write file content from stdin.")
    parser.add_argument("--path", required=True, help="Destination file path")
    parser.add_argument("--append", action="store_true", help="Append instead of overwrite")
    args = parser.parse_args()

    dst = Path(args.path).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = sys.stdin.read()
    mode = "a" if args.append else "w"
    with dst.open(mode, encoding="utf-8", errors="ignore") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
