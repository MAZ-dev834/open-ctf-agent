#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path


PLACEHOLDER_HINTS = (
    "fake",
    "test",
    "example",
    "sample",
    "dummy",
    "xxxx",
    "todo",
)


def collect_candidates(args):
    candidates = []
    candidates.extend(args.candidate)

    for path in args.file:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"file not found: {path}")
        text = p.read_text(encoding="utf-8", errors="ignore")
        candidates.append(text)

    if args.stdin:
        candidates.append(sys.stdin.read())

    return candidates


def score_match(text: str) -> tuple:
    """Heuristic ranking for likely real flags.

    Higher score is better. We prefer:
    - longer tokens (partials are often shorter)
    - non-placeholder content
    """
    lowered = text.lower()
    penalty = sum(1 for w in PLACEHOLDER_HINTS if w in lowered)
    has_braces = int("{" in text and "}" in text)
    return (len(text), has_braces, -penalty)


def find_matches(regex, blob: str, merge_ws: bool):
    out = []
    out.extend(regex.findall(blob))
    if merge_ws:
        compact = re.sub(r"\s+", "", blob)
        if compact != blob:
            out.extend(regex.findall(compact))
    return out


def main():
    parser = argparse.ArgumentParser(description="Validate flag candidates with regex")
    parser.add_argument(
        "--pattern",
        required=True,
        help=r"Regex pattern, e.g. 'flag\{[A-Za-z0-9_\-]+\}'",
    )
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate string (repeatable)",
    )
    parser.add_argument(
        "--text",
        dest="candidate",
        action="append",
        help="Deprecated alias of --candidate kept for LLM/tool compatibility",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Read candidate text from file (repeatable)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read candidate text from stdin",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print all matches instead of one selected match",
    )
    parser.add_argument(
        "--dotall",
        action="store_true",
        help="Compile regex with DOTALL to match across newlines",
    )
    parser.add_argument(
        "--merge-whitespace",
        action="store_true",
        help="Also match against whitespace-stripped text (useful for split flags)",
    )

    args = parser.parse_args()
    flags = re.DOTALL if args.dotall else 0
    regex = re.compile(args.pattern, flags)

    try:
        candidates = collect_candidates(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not candidates:
        print("error: no candidate input", file=sys.stderr)
        return 2

    matches = []
    for blob in candidates:
        found = find_matches(regex, blob, args.merge_whitespace)
        if found:
            matches.extend(found)

    if not matches:
        print("no valid flag found")
        return 1

    unique_matches = list(dict.fromkeys(matches))

    if args.all:
        for item in unique_matches:
            print(item)
    else:
        best = sorted(unique_matches, key=score_match, reverse=True)[0]
        if len(unique_matches) > 1:
            print(
                f"warning: multiple matches found ({len(unique_matches)}), selected best-scored candidate",
                file=sys.stderr,
            )
        print(best)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
