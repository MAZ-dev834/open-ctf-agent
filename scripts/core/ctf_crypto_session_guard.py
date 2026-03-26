#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def default_state(project: Path, min_q: int, min_decay: int, max_attempts: int) -> dict:
    return {
        "project": str(project),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "thresholds": {
            "min_query_remaining": int(min_q),
            "min_decay_remaining_sec": int(min_decay),
            "max_stage_attempts": int(max_attempts),
        },
        "stages": {},
        "history": [],
    }


def load_state(path: Path, project: Path, min_q: int, min_decay: int, max_attempts: int) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return default_state(project, min_q, min_decay, max_attempts)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_rec(state: dict, stage: str) -> dict:
    stages = state.setdefault("stages", {})
    if stage not in stages:
        stages[stage] = {
            "attempts": 0,
            "failures": 0,
            "passed": False,
            "model_failures": {},
            "last_result": "",
            "last_note": "",
            "updated_at": now_iso(),
        }
    return stages[stage]


def append_history(state: dict, event: str, payload: dict) -> None:
    hist = state.setdefault("history", [])
    hist.append({"time": now_iso(), "event": event, "payload": payload})
    if len(hist) > 300:
        del hist[:-300]


def check_health(state: dict, stage: str, queries_remaining: int | None, decay_remaining_sec: int | None) -> tuple[bool, list[str]]:
    th = state.get("thresholds", {})
    min_q = int(th.get("min_query_remaining", 120))
    min_decay = int(th.get("min_decay_remaining_sec", 90))
    max_attempts = int(th.get("max_stage_attempts", 2))

    s = stage_rec(state, stage)
    reasons: list[str] = []

    if queries_remaining is not None and queries_remaining < min_q:
        reasons.append(f"queries_remaining<{min_q}")
    if decay_remaining_sec is not None and decay_remaining_sec < min_decay:
        reasons.append(f"decay_remaining_sec<{min_decay}")
    if int(s.get("failures", 0)) >= max_attempts:
        reasons.append(f"stage_failures>={max_attempts}")

    return (len(reasons) == 0), reasons


def main() -> int:
    p = argparse.ArgumentParser(description="Session/stage guard for interactive hard crypto tasks.")
    p.add_argument("--project", required=True, help="Path to challenge project (e.g. ./workspace/active/<challenge>)")
    p.add_argument("--state", default="", help="State file path (default: <project>/artifacts/crypto_session_guard.json)")
    p.add_argument("--stage", default="global", help="Stage label (e.g. layer1/layer2/layer3)")
    p.add_argument("--event", required=True, choices=["init", "heartbeat", "fail", "pass", "summary", "reset-stage"])
    p.add_argument("--model", default="", help="Model/approach label for per-model failure count")
    p.add_argument("--note", default="", help="Optional note")
    p.add_argument("--queries-remaining", type=int, default=None)
    p.add_argument("--decay-remaining-sec", type=int, default=None)
    p.add_argument("--min-query-remaining", type=int, default=120)
    p.add_argument("--min-decay-remaining-sec", type=int, default=90)
    p.add_argument("--max-stage-attempts", type=int, default=2)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    project = Path(args.project).resolve()
    state_path = Path(args.state).resolve() if args.state else (project / "artifacts" / "crypto_session_guard.json")
    state = load_state(state_path, project, args.min_query_remaining, args.min_decay_remaining_sec, args.max_stage_attempts)

    # Keep thresholds fresh from CLI.
    state.setdefault("thresholds", {})
    state["thresholds"]["min_query_remaining"] = int(args.min_query_remaining)
    state["thresholds"]["min_decay_remaining_sec"] = int(args.min_decay_remaining_sec)
    state["thresholds"]["max_stage_attempts"] = int(args.max_stage_attempts)

    s = stage_rec(state, args.stage)
    exit_code = 0
    reasons: list[str] = []

    if args.event == "init":
        append_history(
            state,
            "init",
            {
                "stage": args.stage,
                "thresholds": state["thresholds"],
                "queries_remaining": args.queries_remaining,
                "decay_remaining_sec": args.decay_remaining_sec,
                "note": args.note,
            },
        )
    elif args.event == "heartbeat":
        ok, reasons = check_health(state, args.stage, args.queries_remaining, args.decay_remaining_sec)
        append_history(
            state,
            "heartbeat",
            {
                "stage": args.stage,
                "queries_remaining": args.queries_remaining,
                "decay_remaining_sec": args.decay_remaining_sec,
                "ok": ok,
                "reasons": reasons,
                "note": args.note,
            },
        )
        exit_code = 0 if ok else 2
    elif args.event == "fail":
        s["attempts"] = int(s.get("attempts", 0)) + 1
        s["failures"] = int(s.get("failures", 0)) + 1
        s["last_result"] = "fail"
        s["last_note"] = args.note
        if args.model:
            mf = s.setdefault("model_failures", {})
            mf[args.model] = int(mf.get(args.model, 0)) + 1
        ok, reasons = check_health(state, args.stage, args.queries_remaining, args.decay_remaining_sec)
        append_history(
            state,
            "fail",
            {
                "stage": args.stage,
                "model": args.model,
                "queries_remaining": args.queries_remaining,
                "decay_remaining_sec": args.decay_remaining_sec,
                "ok": ok,
                "reasons": reasons,
                "note": args.note,
            },
        )
        exit_code = 0 if ok else 2
    elif args.event == "pass":
        s["attempts"] = int(s.get("attempts", 0)) + 1
        s["passed"] = True
        s["last_result"] = "pass"
        s["last_note"] = args.note
        append_history(
            state,
            "pass",
            {
                "stage": args.stage,
                "model": args.model,
                "queries_remaining": args.queries_remaining,
                "decay_remaining_sec": args.decay_remaining_sec,
                "note": args.note,
            },
        )
    elif args.event == "reset-stage":
        state.setdefault("stages", {})[args.stage] = {
            "attempts": 0,
            "failures": 0,
            "passed": False,
            "model_failures": {},
            "last_result": "reset",
            "last_note": args.note,
            "updated_at": now_iso(),
        }
        append_history(state, "reset-stage", {"stage": args.stage, "note": args.note})
    elif args.event == "summary":
        append_history(state, "summary", {"stage": args.stage})

    s["updated_at"] = now_iso()
    save_state(state_path, state)

    output = {
        "state_file": str(state_path),
        "stage": args.stage,
        "stage_state": state.get("stages", {}).get(args.stage, {}),
        "thresholds": state.get("thresholds", {}),
        "event": args.event,
        "queries_remaining": args.queries_remaining,
        "decay_remaining_sec": args.decay_remaining_sec,
        "reasons": reasons,
        "exit_code": exit_code,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(
            f"event={args.event} stage={args.stage} exit={exit_code} "
            f"attempts={output['stage_state'].get('attempts', 0)} "
            f"failures={output['stage_state'].get('failures', 0)} "
            f"passed={output['stage_state'].get('passed', False)}"
        )
        if reasons:
            print("reasons:", ", ".join(reasons))
        print(f"state_file={state_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
