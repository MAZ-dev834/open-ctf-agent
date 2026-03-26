#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

LEET_TRANS = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "2": "z",
        "3": "e",
        "4": "a",
        "5": "s",
        "6": "g",
        "7": "t",
        "8": "b",
        "9": "g",
        "@": "a",
        "$": "s",
    }
)

HINT_WORDS = {
    "hint",
    "clue",
    "decode",
    "decrypt",
    "cipher",
    "xor",
    "key",
    "token",
    "password",
    "admin",
    "login",
    "upload",
    "path",
    "traversal",
    "draw",
    "watch",
    "watching",
    "bat",
    "just",
    "read",
    "file",
    "source",
}


def parse_candidates(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, str):
                out.append({"flag": item.strip(), "score": float(max(0, len(data) - i))})
            elif isinstance(item, dict):
                flag = str(item.get("flag", "")).strip()
                if not flag:
                    continue
                score = item.get("score")
                out.append({"flag": flag, "score": float(score) if score is not None else 0.0})
    return [x for x in out if x.get("flag")]


def extract_inner(flag: str) -> str:
    m = re.match(r"^[A-Za-z0-9_]+\{(.+)\}$", flag.strip())
    return m.group(1) if m else flag.strip()


def leet_hint_penalty(flag: str) -> tuple[float, str]:
    inner = extract_inner(flag)
    leet_text = inner.lower().translate(LEET_TRANS)
    tokens = [t for t in re.split(r"[^a-z]+", leet_text) if len(t) >= 2]
    if not tokens:
        return 0.0, leet_text
    hint_hits = sum(1 for t in tokens if t in HINT_WORDS)
    alpha_chars = sum(1 for ch in leet_text if "a" <= ch <= "z")
    alpha_ratio = alpha_chars / max(1, len(leet_text))

    penalty = 0.0
    if hint_hits >= 2:
        penalty += 0.40
    elif hint_hits == 1 and len(tokens) <= 6:
        penalty += 0.20

    # Phrase-like plain text (often a clue sentence rather than final flag).
    if len(tokens) >= 4 and alpha_ratio >= 0.70:
        penalty += 0.15

    return min(0.60, penalty), leet_text


def run_gate(gate: Path, challenge_dir: Path, cid: int, flag: str, score: float | None, min_score: float | None) -> dict:
    cmd = [
        "python3",
        str(gate),
        "--challenge-dir",
        str(challenge_dir),
        "--id",
        str(cid),
        "--flag",
        flag,
    ]
    if score is not None:
        cmd += ["--candidate-score", str(score)]
    if min_score is not None:
        cmd += ["--min-candidate-score", str(min_score)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        payload = json.loads(line)
    except Exception:
        payload = {"ok": False, "status": "parse_error", "raw": line}
    payload["_rc"] = proc.returncode
    return payload


def append_hint_low(challenge_dir: Path, item: dict) -> None:
    low_path = challenge_dir / "flag_low.txt"
    rec = {
        "ts": time.time(),
        "kind": "leet_hint_candidate",
        "flag": item.get("flag"),
        "base_score": item.get("base_score"),
        "score": item.get("score"),
        "hint_penalty": item.get("hint_penalty"),
        "leet_text": item.get("leet_text"),
    }
    with low_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def resolve_gate_script() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "submit" / "ctf_pipeline_submit_gate.py"


def resolve_strategy(strategy: str, high_threshold: float | None, mid_threshold: float | None, max_submissions: int | None) -> dict:
    strategy_defaults = {
        "conservative": {"high": 0.82, "mid": 0.70, "max_sub": 3},
        "balanced": {"high": 0.78, "mid": 0.62, "max_sub": 5},
        "aggressive": {"high": 0.74, "mid": 0.55, "max_sub": 8},
    }
    sd = strategy_defaults[strategy]
    high_th = float(high_threshold) if high_threshold is not None else float(sd["high"])
    mid_th = float(mid_threshold) if mid_threshold is not None else float(sd["mid"])
    max_sub = int(max_submissions) if max_submissions is not None else int(sd["max_sub"])
    if max_sub < 1:
        max_sub = 1
    return {"high_threshold": high_th, "mid_threshold": mid_th, "max_submissions": max_sub}


def main() -> int:
    p = argparse.ArgumentParser(description="Submit ranked flag candidates through pipeline gate with score thresholding.")
    p.add_argument("--challenge-dir", required=True)
    p.add_argument("--id", required=True, type=int)
    p.add_argument("--candidates-json", required=True, help="JSON list: ['flag', ...] or [{'flag':..., 'score':...}]")
    p.add_argument("--min-candidate-score", type=float, default=None)
    p.add_argument("--leet-penalty", type=float, default=1.0, help="Multiplier for leet hint penalty (0 disables).")
    p.add_argument("--hint-penalty-threshold", type=float, default=0.35, help="Candidates with penalty >= threshold are logged as clue-like.")
    p.add_argument("--log-hint-candidates", choices=["on", "off"], default="on")
    p.add_argument("--strategy", choices=["conservative", "balanced", "aggressive"], default="balanced")
    p.add_argument("--high-threshold", type=float, default=None, help="Override high-score threshold")
    p.add_argument("--mid-threshold", type=float, default=None, help="Override mid-score threshold")
    p.add_argument("--max-submissions", type=int, default=None, help="Override maximum submissions per challenge")
    p.add_argument(
        "--max-consecutive-incorrect",
        type=int,
        default=2,
        help="Stop after this many consecutive incorrect submit results.",
    )
    p.add_argument("--topk", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    gate = resolve_gate_script()
    if not gate.exists():
        print(f"[error] submit gate script not found: {gate}", file=sys.stderr)
        return 2
    challenge_dir = Path(args.challenge_dir).resolve()
    cands = parse_candidates(Path(args.candidates_json).resolve())
    for item in cands:
        base_score = float(item.get("score", 0.0))
        penalty, leet_text = leet_hint_penalty(item["flag"])
        adjusted = max(0.0, base_score - (penalty * max(0.0, args.leet_penalty)))
        item["base_score"] = base_score
        item["hint_penalty"] = penalty
        item["score"] = adjusted
        item["leet_text"] = leet_text[:120]
    strat = resolve_strategy(args.strategy, args.high_threshold, args.mid_threshold, args.max_submissions)
    high_th = float(strat["high_threshold"])
    mid_th = float(strat["mid_threshold"])
    max_sub = int(strat["max_submissions"])

    cands = sorted(cands, key=lambda x: float(x.get("score", 0.0)), reverse=True)[: args.topk]
    hi = [x for x in cands if float(x.get("score", 0.0)) >= high_th]
    mid = [x for x in cands if mid_th <= float(x.get("score", 0.0)) < high_th]
    cands = (hi + mid)[:max_sub]
    if args.log_hint_candidates == "on":
        for item in cands:
            if float(item.get("hint_penalty", 0.0)) >= float(args.hint_penalty_threshold):
                append_hint_low(challenge_dir, item)

    effective_min_score = args.min_candidate_score if args.min_candidate_score is not None else mid_th
    tried = []
    winner = None
    consecutive_incorrect = 0
    stop_reason = ""
    for item in cands:
        flag = item["flag"]
        score = float(item.get("score", 0.0))
        res = run_gate(gate, challenge_dir, args.id, flag, score, effective_min_score)
        status = str(res.get("status", ""))
        rec = {
            "flag": flag,
            "score": score,
            "base_score": float(item.get("base_score", score)),
            "hint_penalty": float(item.get("hint_penalty", 0.0)),
            "leet_text": item.get("leet_text", ""),
            "result": res,
        }
        tried.append(rec)
        if bool(res.get("ok")) and status in {"correct", "already_solved"}:
            winner = rec
            break
        if status == "incorrect":
            consecutive_incorrect += 1
        else:
            consecutive_incorrect = 0

        if status in {
            "filtered_low_score",
            "missing_candidate_score",
            "ratelimited",
            "cooldown_blocked",
            "cooldown_blocked_incorrect",
            "cooldown_blocked_ratelimit",
        }:
            stop_reason = status
            break
        if args.max_consecutive_incorrect > 0 and consecutive_incorrect >= args.max_consecutive_incorrect:
            stop_reason = "consecutive_incorrect_limit"
            break

    out = {"count": len(tried), "winner": winner, "tried": tried}
    out["strategy"] = {
        "name": args.strategy,
        "high_threshold": high_th,
        "mid_threshold": mid_th,
        "max_submissions": max_sub,
        "effective_min_candidate_score": effective_min_score,
    }
    out["stop_reason"] = stop_reason or ("winner_found" if winner else "exhausted")
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"submitted: {len(tried)}")
        if winner:
            print(f"winner: {winner['flag']} score={winner['score']}")
        else:
            print("winner: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
