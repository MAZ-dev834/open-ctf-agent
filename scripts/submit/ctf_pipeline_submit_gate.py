#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def append_low_flag(challenge_dir: Path, flag: str, payload: dict):
    low_path = challenge_dir / "flag_low.txt"
    rec = {
        "ts": time.time(),
        "flag": flag,
        "http_status": payload.get("http_status"),
        "response": payload.get("response"),
    }
    with open(low_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return low_path


def promote_flag(challenge_dir: Path, flag: str):
    out = challenge_dir / "flag.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(flag.strip() + "\n")
    return out


def find_event_dir(challenge_dir: Path):
    cur = challenge_dir.resolve()
    for p in [cur] + list(cur.parents):
        if (p / "status.json").exists():
            return p
    return None


def resolve_submit_log_path(log_arg: str | None, event_dir: Path | None) -> str:
    if log_arg:
        return str(log_arg)
    env_log = os.getenv("CTFD_SUBMIT_LOG", "").strip()
    if env_log:
        return env_log
    if event_dir:
        return str(event_dir / "submissions.jsonl")
    raise RuntimeError("missing submit log path: set CTFD_SUBMIT_LOG or pass --log")


def is_submit_success(payload):
    response = payload.get("response") if isinstance(payload, dict) else {}
    data = (response.get("data") or {}) if isinstance(response, dict) else {}
    status = data.get("status")
    message = str(data.get("message", "")).lower()
    if status == "correct":
        return True, status
    if status == "already_solved":
        if "incorrect" in message:
            return False, status
        return True, status
    return False, status


def parse_submit_status(payload: dict) -> tuple[str, str]:
    response = payload.get("response") if isinstance(payload, dict) else {}
    data = (response.get("data") or {}) if isinstance(response, dict) else {}
    return str(data.get("status") or ""), str(data.get("message") or "")


def parse_retry_after_seconds(payload: dict) -> int | None:
    _, message = parse_submit_status(payload)
    m = re.search(r"(\d+)\s*seconds?", message, flags=re.I)
    if not m:
        return None
    try:
        return max(1, int(m.group(1)))
    except Exception:
        return None


def was_recently_submitted(
    log_path: str, challenge_id: int, flag: str, window_sec: float
) -> bool:
    if window_sec <= 0:
        return False
    p = Path(log_path)
    if not p.exists():
        return False
    target = hashlib.sha256(flag.strip().encode("utf-8")).hexdigest()
    now = time.time()
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return False
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if int(rec.get("challenge_id", -1)) != int(challenge_id):
            continue
        ts = float(rec.get("ts", 0.0))
        if now - ts > window_sec:
            return False
        rec_flag = str(rec.get("flag", "")).strip()
        if hashlib.sha256(rec_flag.encode("utf-8")).hexdigest() == target:
            return True
    return False


def run_submit(cmd: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        payload = {
            "http_status": None,
            "response": {
                "error": f"submit_flag.py failed rc={proc.returncode}",
                "stderr": proc.stderr[-500:],
            },
        }
        return proc.returncode, payload
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        payload = json.loads(line)
    except Exception:
        payload = {"http_status": None, "response": line}
    return 0, payload


def recent_submit_stats(log_path: str, challenge_id: int, window_sec: float) -> dict:
    p = Path(log_path)
    now = time.time()
    out = {
        "incorrect_count": 0,
        "ratelimited_count": 0,
        "last_ts": 0.0,
        "last_ratelimit_ts": 0.0,
    }
    if not p.exists() or window_sec <= 0:
        return out
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        try:
            cid = int(rec.get("challenge_id", -1))
        except Exception:
            continue
        if cid != int(challenge_id):
            continue
        ts = float(rec.get("ts", 0.0))
        if ts > 0 and out["last_ts"] == 0.0:
            out["last_ts"] = ts
        if ts > 0 and now - ts > window_sec:
            break
        response = rec.get("response") if isinstance(rec, dict) else {}
        data = (response.get("data") or {}) if isinstance(response, dict) else {}
        status = str(data.get("status", "")).lower()
        http_status = int(rec.get("http_status") or 0)
        if status == "incorrect":
            out["incorrect_count"] += 1
        if status == "ratelimited" or http_status == 429:
            out["ratelimited_count"] += 1
            if ts > out["last_ratelimit_ts"]:
                out["last_ratelimit_ts"] = ts
    return out


def blocked_payload(status: str, message: str, cooldown_until: float | None) -> dict:
    data: dict[str, object] = {"status": status, "message": message}
    if cooldown_until:
        data["cooldown_until"] = cooldown_until
    return {"http_status": None, "response": {"data": data}}


def main():
    ap = argparse.ArgumentParser(
        description="Pipeline submit gate: submit first, then promote to flag.txt on success"
    )
    ap.add_argument("--challenge-dir", required=True)
    ap.add_argument("--id", required=True, type=int)
    ap.add_argument("--flag", required=True)
    ap.add_argument("--base", help="CTFd base URL (fallback env: CTFD_BASE_URL)")
    ap.add_argument("--session", help="CTFd session (fallback env: CTFD_SESSION)")
    ap.add_argument("--token", help="CTFd token (fallback env: CTFD_TOKEN)")
    ap.add_argument(
        "--min-interval",
        type=float,
        default=None,
        help="fallback env: CTFD_MIN_INTERVAL",
    )
    ap.add_argument("--log", default=None, help="fallback env: CTFD_SUBMIT_LOG")
    ap.add_argument(
        "--dedupe-window-sec",
        type=float,
        default=7200.0,
        help="Skip identical recent submissions within this window.",
    )
    ap.add_argument(
        "--respect-429-hint",
        choices=["on", "off"],
        default="on",
        help="Honor retry seconds from ratelimit response message.",
    )
    ap.add_argument(
        "--candidate-score",
        type=float,
        default=None,
        help="Optional score attached to candidate.",
    )
    ap.add_argument(
        "--min-candidate-score",
        type=float,
        default=None,
        help="If set, skip submissions below this threshold.",
    )
    ap.add_argument(
        "--cooldown-window-sec",
        type=float,
        default=None,
        help="Challenge-level cooldown window after repeated incorrect or ratelimited submits.",
    )
    ap.add_argument(
        "--max-incorrect-per-window",
        type=int,
        default=None,
        help="Block submissions when recent incorrect count exceeds this threshold.",
    )
    ap.add_argument(
        "--stats-window-sec",
        type=float,
        default=900.0,
        help="Lookback window for submit stats (incorrect/ratelimit).",
    )
    args = ap.parse_args()

    disable_submit = str(os.getenv("CTF_PIPELINE_DISABLE_SUBMIT", "")).strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }

    base = args.base or os.getenv("CTFD_BASE_URL", "")
    session = args.session or os.getenv("CTFD_SESSION", "")
    token = args.token or os.getenv("CTFD_TOKEN", "")
    min_interval = args.min_interval
    if min_interval is None:
        min_interval = float(os.getenv("CTFD_MIN_INTERVAL", "5"))
    challenge_dir = Path(args.challenge_dir).resolve()
    challenge_dir.mkdir(parents=True, exist_ok=True)

    if disable_submit:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "submit_disabled",
                    "submit_block_reason": "pipeline_submit_disabled",
                },
                ensure_ascii=False,
            )
        )
        return 11

    event_dir = find_event_dir(challenge_dir)
    log_path = resolve_submit_log_path(args.log, event_dir)
    min_candidate_score = args.min_candidate_score
    if min_candidate_score is None:
        env_min = os.getenv("CTFD_MIN_CANDIDATE_SCORE", "").strip()
        if env_min:
            try:
                min_candidate_score = float(env_min)
            except Exception:
                min_candidate_score = 0.60
    if min_candidate_score is None:
        min_candidate_score = 0.60
    allow_unscored = str(
        os.getenv("CTFD_ALLOW_UNSCORED_SUBMIT", "")
    ).strip().lower() in {"1", "true", "on", "yes"}
    cooldown_window_sec = args.cooldown_window_sec
    if cooldown_window_sec is None:
        try:
            cooldown_window_sec = float(os.getenv("CTFD_SUBMIT_COOLDOWN_SEC", "600"))
        except Exception:
            cooldown_window_sec = 600.0
    max_incorrect = args.max_incorrect_per_window
    if max_incorrect is None:
        try:
            max_incorrect = int(os.getenv("CTFD_MAX_INCORRECT_PER_CHALLENGE", "3"))
        except Exception:
            max_incorrect = 3
    candidate_score = args.candidate_score
    if candidate_score is None:
        env_score = os.getenv("CTFD_CANDIDATE_SCORE", "").strip()
        if env_score:
            try:
                candidate_score = float(env_score)
            except Exception:
                candidate_score = None

    if not base:
        payload = blocked_payload(
            "submit_unconfigured",
            "missing base URL: use --base or CTFD_BASE_URL",
            None,
        )
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "submit_unconfigured",
                    "submit_block_reason": "missing_base_url",
                    "flag_low": str(low),
                },
                ensure_ascii=False,
            )
        )
        return 9
    if not session and not token:
        payload = blocked_payload(
            "submit_unconfigured",
            "missing auth: use --session/--token or CTFD_SESSION/CTFD_TOKEN",
            None,
        )
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "submit_unconfigured",
                    "submit_block_reason": "missing_auth",
                    "flag_low": str(low),
                },
                ensure_ascii=False,
            )
        )
        return 10

    if candidate_score is None and not allow_unscored:
        payload = blocked_payload(
            "missing_candidate_score",
            "candidate score is required by default policy",
            None,
        )
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "missing_candidate_score",
                    "submit_block_reason": "score_required",
                    "flag_low": str(low),
                },
                ensure_ascii=False,
            )
        )
        return 6

    if min_candidate_score is not None and (
        candidate_score is None or candidate_score < min_candidate_score
    ):
        payload = {
            "http_status": None,
            "response": {
                "data": {
                    "status": "filtered_low_score",
                    "message": f"candidate_score={candidate_score} < min={min_candidate_score}",
                }
            },
        }
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {"ok": False, "status": "filtered_low_score", "flag_low": str(low)},
                ensure_ascii=False,
            )
        )
        return 4

    stats = recent_submit_stats(log_path, args.id, args.stats_window_sec)
    now = time.time()
    if (
        max_incorrect > 0
        and stats["incorrect_count"] >= max_incorrect
        and stats["last_ts"] > 0
    ):
        cooldown_until = stats["last_ts"] + cooldown_window_sec
        if now < cooldown_until:
            payload = blocked_payload(
                "cooldown_blocked_incorrect",
                f"recent incorrect submissions={stats['incorrect_count']} >= max={max_incorrect}",
                cooldown_until,
            )
            low = append_low_flag(challenge_dir, args.flag, payload)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "status": "cooldown_blocked_incorrect",
                        "submit_block_reason": "incorrect_storm",
                        "cooldown_until": cooldown_until,
                        "flag_low": str(low),
                    },
                    ensure_ascii=False,
                )
            )
            return 7
    if stats["ratelimited_count"] > 0 and stats["last_ratelimit_ts"] > 0:
        cooldown_until = stats["last_ratelimit_ts"] + cooldown_window_sec
        if now < cooldown_until:
            payload = blocked_payload(
                "cooldown_blocked_ratelimit",
                f"recent ratelimited submissions={stats['ratelimited_count']}",
                cooldown_until,
            )
            low = append_low_flag(challenge_dir, args.flag, payload)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "status": "cooldown_blocked_ratelimit",
                        "submit_block_reason": "ratelimit_cooldown",
                        "cooldown_until": cooldown_until,
                        "flag_low": str(low),
                    },
                    ensure_ascii=False,
                )
            )
            return 8

    if was_recently_submitted(log_path, args.id, args.flag, args.dedupe_window_sec):
        payload = {
            "http_status": None,
            "response": {
                "data": {
                    "status": "deduped_recent",
                    "message": "same challenge+flag found in recent submission log",
                }
            },
        }
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {"ok": False, "status": "deduped_recent", "flag_low": str(low)},
                ensure_ascii=False,
            )
        )
        return 5

    submit_py = Path(__file__).resolve().parents[1] / "ctfd" / "submit_flag.py"
    cmd = [
        "python3",
        str(submit_py),
        "--base",
        base,
        "--id",
        str(args.id),
        "--flag",
        args.flag.strip(),
        "--min-interval",
        str(min_interval),
        "--log",
        log_path,
    ]
    if event_dir:
        cmd += ["--event-dir", str(event_dir)]
    if session:
        cmd += ["--session", session]
    if token:
        cmd += ["--token", token]

    rc, payload = run_submit(cmd)
    if rc != 0:
        low = append_low_flag(challenge_dir, args.flag, payload)
        print(
            json.dumps(
                {"ok": False, "status": "submit_error", "flag_low": str(low)},
                ensure_ascii=False,
            )
        )
        return 2

    status, _ = parse_submit_status(payload)
    if status == "ratelimited" and args.respect_429_hint == "on":
        wait_sec = parse_retry_after_seconds(payload)
        if wait_sec is not None:
            time.sleep(wait_sec + 0.25)
            rc, payload = run_submit(cmd)
            if rc != 0:
                low = append_low_flag(challenge_dir, args.flag, payload)
                print(
                    json.dumps(
                        {"ok": False, "status": "submit_error", "flag_low": str(low)},
                        ensure_ascii=False,
                    )
                )
                return 2

    ok, status = is_submit_success(payload)
    if ok:
        out = promote_flag(challenge_dir, args.flag)
        print(
            json.dumps(
                {"ok": True, "status": status, "flag": str(out)}, ensure_ascii=False
            )
        )
        return 0

    low = append_low_flag(challenge_dir, args.flag, payload)
    print(
        json.dumps(
            {
                "ok": False,
                "status": status or "incorrect",
                "submit_block_reason": "",
                "flag_low": str(low),
            },
            ensure_ascii=False,
        )
    )
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
