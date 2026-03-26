#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from pathlib import Path

CATEGORY_HINTS = {
    "web": ["http", "cookie", "jwt", "xss", "sqli", "ssti", "ssrf", "upload", "csrf", "session", "api", "flask", "django", "node"],
    "pwn": ["rop", "pie", "canary", "libc", "heap", "uaf", "format", "bof", "overflow", "got", "plt", "tcache", "seccomp"],
    "crypto": [
        "rsa", "aes", "ecc", "ecdh", "ecdsa", "ed25519", "dsa", "schnorr",
        "prng", "mt19937", "lcg", "nonce", "rng", "seed",
        "hash", "sha", "md5", "length extension", "merkle", "hmac",
        "lattice", "lll", "babai", "svp", "cvp", "hnp", "hidden number", "coppersmith",
        "small root", "partial key", "approx gcd", "agcd", "knapsack", "subset sum",
        "dlog", "pohlig", "pollard", "wiener", "fermat", "hastad", "common modulus",
        "oracle", "padding oracle", "bleichenbacher", "pkcs", "oaep", "cbc", "ecb",
        "gcm", "poly1305", "chacha", "ctr", "cbc-mac", "mac",
        "lwe", "lpn", "isogeny",
    ],
    "rev": ["reverse", "ghidra", "decompile", "obfus", "bytecode", "apk", "elf", "ida", "radare", "symbolic"],
    "forensics": ["pcap", "pcapng", "stego", "forensics", "metadata", "memory dump", "memdump", "disk image", "dd", "e01", "evtx", "vmdk",
                  "volatility", "mft", "usn", "registry", "binwalk", "tshark", "wireshark", "usb", "uart", "exif"],
    "osint": ["osint", "geo", "geolocation", "location", "map", "street view", "whois", "dns", "wayback", "archive", "handle", "username", "social"],
    "malware": ["malware", "packed", "obfuscated", "obfus", "c2", "beacon", "ransomware", "dropper", "pe", "dotnet", ".net", "dll", "shellcode"],
    "misc": ["encoding", "decode", "jail", "sandbox", "esolang", "rf", "sdr", "game", "vm", "puzzle", "protocol", "constraint"],
}

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "then", "only", "also", "need", "just", "when", "where",
    "you", "your", "are", "was", "were", "have", "has", "had", "ctf", "challenge", "flag", "solve", "题目", "一个", "可以", "然后",
}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def load_failure_signals(path: Path, limit: int = 20) -> list[str]:
    if not path.exists():
        return []
    signals: list[str] = []
    in_weak_block = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.lower().startswith("- observed weak patterns:"):
            in_weak_block = True
            continue
        if in_weak_block:
            low = ln.lower()
            if low.startswith("- source logs:") or low.startswith("- failure classes:"):
                in_weak_block = False
                continue
            if ln.startswith("## "):
                in_weak_block = False
                continue
            if ln.startswith("- ") or ln.startswith("* "):
                sig = ln[2:].strip()
                sig = re.sub(r"\s*\(x\d+\)\s*$", "", sig)
                if "/" in sig or ".log" in sig.lower():
                    continue
                if len(sig) < 6:
                    continue
                if sig:
                    signals.append(sig)
    return list(dict.fromkeys(signals))[:limit]


def load_failure_signals_json(path: Path, limit: int = 40) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    out: list[str] = []
    projects = data.get("projects", {})
    if isinstance(projects, dict):
        for rec in projects.values():
            if not isinstance(rec, dict):
                continue
            signal_counts = rec.get("signal_counts", {})
            if isinstance(signal_counts, dict):
                for name in signal_counts:
                    if isinstance(name, str) and name.strip():
                        out.append(name.strip())
    return list(dict.fromkeys(out))[:limit]


def load_combined_failure_signals(paths: list[Path], limit: int = 40) -> list[str]:
    merged: list[str] = []
    for p in paths:
        merged.extend(load_failure_signals(p, limit=limit))
    return list(dict.fromkeys(merged))[:limit]


def tokenize(text: str) -> list[str]:
    text = text.lower()
    toks = re.findall(r"[a-z0-9_\-\u4e00-\u9fff]{2,}", text)
    return [t for t in toks if t not in STOPWORDS]


def infer_category(text: str) -> tuple[str, dict[str, int]]:
    low = text.lower()
    scores: dict[str, int] = {}
    for cat, keys in CATEGORY_HINTS.items():
        score = 0
        for k in keys:
            if k in low:
                score += 1
        scores[cat] = score
    best = max(scores.items(), key=lambda kv: kv[1])[0]
    if scores[best] == 0:
        return "unknown", scores
    return best, scores


def parse_timestamp(ts: str) -> dt.datetime | None:
    ts = (ts or "").strip()
    if not ts:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in fmts:
        try:
            return dt.datetime.strptime(ts, fmt)
        except Exception:
            continue
    return None


def recency_decay(ts: str, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    t = parse_timestamp(ts)
    if t is None:
        return 0.6
    now = dt.datetime.now(t.tzinfo) if t.tzinfo else dt.datetime.now()
    age_days = max(0.0, (now - t).total_seconds() / 86400.0)
    # Exponential decay with half-life.
    return math.exp(-math.log(2) * age_days / half_life_days)


def score_record(
    rec: dict,
    query_tokens: set[str],
    *,
    selected_category: str,
    inferred_category: str,
    validated_log_scale: float,
    category_match_boost: float,
    recency_half_life_days: float,
    freshness_weight: float,
) -> tuple[float, dict]:
    if rec.get("status") != "solved":
        return -1.0, {}

    conf = float(rec.get("confidence", 0.0) or 0.0)
    patterns = rec.get("patterns", []) or []
    commands = rec.get("commands", []) or []
    text = " ".join(str(x) for x in (patterns + commands)).lower()
    rec_tokens = set(tokenize(text))
    overlap = len(query_tokens & rec_tokens)
    validated = int(rec.get("validated_count", 0) or 0)
    rec_cat = str(rec.get("category", "unknown")).lower()

    conf_term = conf * 0.55
    overlap_term = min(overlap, 10) * 0.05
    validated_term = min(0.25, math.log1p(max(0, validated)) * max(0.0, validated_log_scale))

    ref_cat = selected_category if selected_category != "unknown" else inferred_category
    category_term = category_match_boost if ref_cat and ref_cat != "unknown" and rec_cat == ref_cat else 0.0

    freshness = recency_decay(str(rec.get("timestamp", "")), recency_half_life_days)
    freshness_term = max(0.0, freshness_weight) * freshness

    score = conf_term + overlap_term + validated_term + category_term + freshness_term
    return score, {
        "conf_term": round(conf_term, 3),
        "overlap_term": round(overlap_term, 3),
        "validated_term": round(validated_term, 3),
        "category_term": round(category_term, 3),
        "freshness_term": round(freshness_term, 3),
        "freshness": round(freshness, 3),
        "overlap": overlap,
    }


def failure_penalty(
    rec: dict,
    failure_token_sets: list[set[str]],
    *,
    max_penalty: float = 0.25,
    overlap_threshold: int = 2,
    penalty_step: float = 0.05,
) -> tuple[float, list[str]]:
    if not failure_token_sets:
        return 0.0, []
    patterns = rec.get("patterns", []) or []
    commands = rec.get("commands", []) or []
    corpus_tokens = set(tokenize(" ".join(str(x) for x in (patterns + commands))))
    matched_idx: list[str] = []
    for i, fset in enumerate(failure_token_sets):
        if not fset:
            continue
        if len(corpus_tokens & fset) >= overlap_threshold:
            matched_idx.append(str(i))
    if not matched_idx:
        return 0.0, []
    penalty = min(max_penalty, penalty_step * len(matched_idx))
    return penalty, matched_idx


def build_action_hints(text: str, category: str) -> list[str]:
    low = text.lower()
    actions: list[str] = []

    # Cross-cutting first moves
    if any(k in low for k in ("source", "源码", "provided code", "zip")):
        actions.append("read provided source/attachments first; map input -> transform -> check")
    if any(k in low for k in ("nc ", "netcat", "remote", "instance", "server")):
        actions.append("confirm interaction protocol and rate limits before brute-force")

    if category == "crypto":
        if any(k in low for k in ("rsa", "modulus", "n=", "e=", "d=")):
            actions.append("check RSA structure: small e, shared factors, partial key, common modulus")
        if any(k in low for k in ("lattice", "lll", "hnp", "coppersmith", "small root")):
            actions.append("estimate lattice dimensions/noise bounds; verify HNP/LLL preconditions")
        if any(k in low for k in ("ecdsa", "ecdh", "ecc", "nonce", "k reuse")):
            actions.append("test nonce reuse/partial leakage; recover private key via HNP")
        if any(k in low for k in ("oracle", "padding", "bleichenbacher", "oaep", "cbc")):
            actions.append("measure oracle distinguishability before large queries")
        if not actions:
            actions.append("identify primitive + leakage model; search for exact model/paper keywords")

    elif category == "web":
        if any(k in low for k in ("auth", "login", "cookie", "session", "jwt")):
            actions.append("trace auth/state transitions; reproduce one minimal request chain")
        if any(k in low for k in ("upload", "file", "path traversal", "lfi", "rfi")):
            actions.append("map file handling and path normalization; attempt controlled upload/reading")
        if any(k in low for k in ("sqli", "xss", "ssti", "ssrf")):
            actions.append("verify vuln class with a minimal payload before fuzzing")
        if not actions:
            actions.append("request/response map first; then automate minimal chain")

    elif category == "rev":
        actions.append("locate compare/check site first; trace inputs backward")
        if any(k in low for k in ("vm", "bytecode", "wasm", "obfus", "packer")):
            actions.append("decide static vs light dynamic; avoid full tracing until constraints appear")

    elif category == "pwn":
        actions.append("confirm mitigations and crash primitive; identify stack/heap/fmt direction")
        if any(k in low for k in ("libc", "ld", "one_gadget")):
            actions.append("align libc/ld early; stabilize offsets before exploit")

    elif category == "forensics":
        actions.append("do file triage: type/metadata/strings/extract; then targeted tools")
        if any(k in low for k in ("pcap", "pcapng", "wireshark", "tshark")):
            actions.append("filter by protocols and carve artifacts; track offsets")

    elif category == "osint":
        actions.append("extract unique identifiers first; pivot via reliable sources")

    elif category == "malware":
        actions.append("check packer/obfuscation; carve config/IOC before heavy dynamic analysis")

    elif category == "misc":
        actions.append("build artifact index; automate decode/extract loops early")

    # Keep the list short and non-redundant
    deduped: list[str] = []
    for a in actions:
        if a not in deduped:
            deduped.append(a)
        if len(deduped) >= 4:
            break
    return deduped


def build_search_keywords(text: str, category: str) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    for key in CATEGORY_HINTS.get(category, []):
        if key in low and key not in hits:
            hits.append(key)
        if len(hits) >= 6:
            break
    # Add a few top tokens from the prompt for specificity
    for tok in tokenize(text):
        if tok not in hits and len(tok) >= 3:
            hits.append(tok)
        if len(hits) >= 8:
            break
    return hits[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description="Recommend high-confidence memory entries from challenge text.")
    parser.add_argument("--text", default="", help="Challenge title/description text")
    parser.add_argument("--text-file", default="", help="Path to text file containing challenge description")
    parser.add_argument("--index", default="./shared/skill-memory/memory_index.jsonl")
    parser.add_argument("--failure-file", default="./shared/skill-memory/failure-patterns.md")
    parser.add_argument("--failure-auto-file", default="./shared/skill-memory/failure-patterns-auto.md")
    parser.add_argument("--failure-auto-json", default="./shared/skill-memory/failure-patterns-auto.json")
    parser.add_argument("--category", default="", help="Force category")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--max-risk-penalty", type=float, default=0.25)
    parser.add_argument("--risk-overlap-threshold", type=int, default=2)
    parser.add_argument("--risk-penalty-step", type=float, default=0.05)
    parser.add_argument("--validated-log-scale", type=float, default=0.08)
    parser.add_argument("--category-match-boost", type=float, default=0.08)
    parser.add_argument("--recency-half-life-days", type=float, default=45.0)
    parser.add_argument("--freshness-weight", type=float, default=0.12)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    src_text = args.text
    if args.text_file:
        p = Path(args.text_file)
        if p.exists():
            src_text += "\n" + p.read_text(encoding="utf-8", errors="ignore")

    rows = load_rows(Path(args.index).resolve())
    failure_signals = load_combined_failure_signals(
        [
            Path(args.failure_file).resolve(),
            Path(args.failure_auto_file).resolve(),
        ]
    )
    failure_signals.extend(load_failure_signals_json(Path(args.failure_auto_json).resolve()))
    failure_signals = list(dict.fromkeys(failure_signals))
    failure_token_sets = [set(tokenize(sig)) for sig in failure_signals]

    inferred, cat_scores = infer_category(src_text)
    category = args.category.lower().strip() if args.category else inferred
    q_tokens = set(tokenize(src_text))
    action_hints = build_action_hints(src_text, category)
    search_keywords = build_search_keywords(src_text, category)

    filtered: list[tuple[float, dict, float, list[str], dict]] = []
    for r in rows:
        if category != "unknown" and str(r.get("category", "")).lower() != category:
            continue
        conf = float(r.get("confidence", 0.0) or 0.0)
        if conf < args.min_confidence:
            continue

        base, breakdown = score_record(
            r,
            q_tokens,
            selected_category=category,
            inferred_category=inferred,
            validated_log_scale=max(0.0, args.validated_log_scale),
            category_match_boost=max(0.0, args.category_match_boost),
            recency_half_life_days=max(1.0, args.recency_half_life_days),
            freshness_weight=max(0.0, args.freshness_weight),
        )
        if base < 0:
            continue

        pen, risk_refs = failure_penalty(
            r,
            failure_token_sets,
            max_penalty=args.max_risk_penalty,
            overlap_threshold=max(1, args.risk_overlap_threshold),
            penalty_step=max(0.0, args.risk_penalty_step),
        )
        filtered.append((base - pen, r, pen, risk_refs, breakdown))

    filtered.sort(key=lambda x: x[0], reverse=True)

    top = []
    for score, r, pen, risk_refs, breakdown in filtered[: args.limit]:
        top.append(
            {
                "project": r.get("project"),
                "category": r.get("category"),
                "confidence": r.get("confidence"),
                "score": round(score, 2),
                "risk_penalty": round(pen, 2),
                "risk_signal_refs": risk_refs,
                "breakdown": breakdown,
                "patterns": (r.get("patterns", []) or [])[:3],
                "commands": (r.get("commands", []) or [])[:3],
            }
        )

    if args.json:
        payload = {
            "inferred_category": inferred,
            "category_scores": cat_scores,
            "selected_category": category,
            "failure_signal_count": len(failure_signals),
            "next_actions": action_hints,
            "search_keywords": search_keywords,
            "recommendations": top,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"inferred_category: {inferred}")
    print("category_scores:")
    for cat, sc in sorted(cat_scores.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {cat}: {sc}")
    print(f"selected_category: {category}")
    print(f"failure_signal_count: {len(failure_signals)}")
    if action_hints:
        print("next_actions:")
        for act in action_hints:
            print(f"  - {act}")
    if search_keywords:
        print("search_keywords:")
        for kw in search_keywords[:6]:
            print(f"  - {kw}")

    if not top:
        print("recommendations: none")
        return 0

    print("recommendations:")
    for item in top:
        b = item["breakdown"]
        print(
            f"- [{item['category']}] {item['project']} conf={item['confidence']} score={item['score']:.2f} penalty={item['risk_penalty']:.2f}"
        )
        print(
            f"    terms: conf={b['conf_term']:.3f} overlap={b['overlap_term']:.3f} validated={b['validated_term']:.3f} category={b['category_term']:.3f} fresh={b['freshness_term']:.3f}"
        )
        for p in item["patterns"]:
            print(f"    * {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
