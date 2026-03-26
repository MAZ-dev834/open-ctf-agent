#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "then", "only", "also", "need", "just", "when", "where",
    "you", "your", "are", "was", "were", "have", "has", "had", "ctf", "challenge", "flag", "solve", "题目", "一个", "可以", "然后",
}

ADVICE_MAP = {
    "timeout": "Enable throttle/backoff and cap per-branch retries before changing model.",
    "retry": "Enable throttle/backoff and cap per-branch retries before changing model.",
    "traceback": "Reproduce with minimal input and fix parser/runtime errors before new probes.",
    "validator": "Validate flag regex and validator arguments before submitting candidates.",
    "rate": "Use score-thresholded candidate submit and cooldown-aware pacing.",
    "429": "Use score-thresholded candidate submit and cooldown-aware pacing.",
    "oracle": "Measure oracle distinguishability first; do not brute force before signal check.",
    "noise": "Use sequential scoring and candidate pruning rather than majority vote.",
}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def tokenize(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9_\-\u4e00-\u9fff]{2,}", text.lower())
    return {t for t in toks if t not in STOPWORDS}


def overlap_score(query_tokens: set[str], patterns: list[str], commands: list[str]) -> int:
    corpus = " ".join(patterns + commands)
    tokens = tokenize(corpus)
    return len(tokens & query_tokens)


def infer_failure_signals(patterns: list[str]) -> list[str]:
    joined = " ".join(str(x) for x in patterns).lower()
    out = []
    if re.search(r"(timeout|retry|timed out|connection reset|broken pipe|deadline)", joined):
        out.append("timeout_or_retry_storm")
    if re.search(r"(traceback|exception|crash|runtime)", joined):
        out.append("runtime_error")
    if re.search(r"(validator|flag_validate|regex|usage error)", joined):
        out.append("validator_or_gate_misuse")
    if re.search(r"(rate limit|ratelimit|429|cooldown|lockout)", joined):
        out.append("submit_rate_limit")
    if re.search(r"(oracle|noisy|noise|query budget|query limit)", joined):
        out.append("noisy_oracle_or_budget")
    if not out:
        out.append("generic_failure")
    return out


def suggested_avoidance(signals: list[str], patterns: list[str]) -> list[str]:
    text = " ".join(patterns).lower()
    tips = []
    for token, advice in ADVICE_MAP.items():
        if token in text and advice not in tips:
            tips.append(advice)
    if "timeout_or_retry_storm" in signals and not any("throttle" in t.lower() for t in tips):
        tips.append("Add per-stage budget and stop conditions to avoid retry storms.")
    if not tips:
        tips.append("Record branch stop-conditions and pivot after fixed retry budget.")
    return tips[:3]


def main() -> int:
    parser = argparse.ArgumentParser(description="Show likely failure patterns for current challenge context.")
    parser.add_argument("--index", default="./shared/skill-memory/memory_index.jsonl")
    parser.add_argument("--text", default="", help="Challenge title/description")
    parser.add_argument("--text-file", default="", help="Challenge text file")
    parser.add_argument("--category", default="", help="Restrict category")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    text = args.text
    if args.text_file:
        p = Path(args.text_file)
        if p.exists():
            text += "\n" + p.read_text(encoding="utf-8", errors="ignore")
    q = tokenize(text)

    rows = load_rows(Path(args.index).resolve())
    candidates = []
    for r in rows:
        cat = str(r.get("category", "")).lower()
        if args.category and cat != args.category.lower():
            continue
        is_failure_like = (r.get("status") == "unsolved") or (r.get("memory_tier") == "incubating")
        if not is_failure_like:
            continue
        patterns = [str(x) for x in (r.get("patterns") or [])]
        commands = [str(x) for x in (r.get("commands") or [])]
        ov = overlap_score(q, patterns, commands)
        # higher overlap and more recent timestamp tends to be more relevant
        score = ov * 2 + (1 if r.get("status") == "unsolved" else 0)
        candidates.append((score, r))

    candidates.sort(key=lambda x: (x[0], str(x[1].get("timestamp", ""))), reverse=True)

    shown = 0
    seen_proj = set()
    phrase_counter = Counter()
    watchlist = []

    for score, r in candidates:
        proj = r.get("project")
        if proj in seen_proj:
            continue
        seen_proj.add(proj)
        pats = r.get("patterns") or []
        for p in pats:
            key = str(p).strip()
            if key:
                phrase_counter[key] += 1
        watchlist.append(
            {
                "project": proj,
                "category": r.get("category"),
                "status": r.get("status"),
                "memory_tier": r.get("memory_tier"),
                "score": score,
                "patterns": pats[:2],
                "failure_signals": infer_failure_signals([str(x) for x in pats]),
                "suggested_avoidance": suggested_avoidance(
                    infer_failure_signals([str(x) for x in pats]), [str(x) for x in pats]
                ),
            }
        )
        shown += 1
        if shown >= args.limit:
            break

    common = phrase_counter.most_common(5)
    common_failure_signals = [{"signal": sig, "count": cnt} for sig, cnt in common]

    if args.json:
        payload = {
            "category": args.category or "",
            "watchlist": watchlist,
            "common_failure_signals": common_failure_signals,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("failure_watchlist:")
    if not watchlist:
        print("- none")
        return 0
    for item in watchlist:
        print(
            f"- [{item['category']}] {item['project']} status={item['status']} tier={item['memory_tier']} score={item['score']}"
        )
        for p in item["patterns"]:
            print(f"  * {p}")
        print(f"  * signals: {', '.join(item['failure_signals'])}")
        for tip in item["suggested_avoidance"]:
            print(f"  * avoid: {tip}")
    if common_failure_signals:
        print("common_failure_signals:")
        for item in common_failure_signals:
            print(f"- ({item['count']}x) {item['signal']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
