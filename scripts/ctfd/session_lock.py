#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path


def is_pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def lock_path_for(out_root, challenge_id):
    return Path(out_root) / ".locks" / f"challenge_{challenge_id}.lock.json"


def compute_ttl(ttl_sec):
    try:
        ttl = int(ttl_sec)
    except Exception:
        ttl = 0
    if ttl <= 0:
        return 7200
    if ttl < 600:
        return 600
    return ttl


def read_lock(lock_path):
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def lock_age(lock_payload):
    try:
        ts = float(lock_payload.get("ts", 0))
    except Exception:
        ts = 0.0
    if ts <= 0:
        return 0.0
    return max(0.0, time.time() - ts)


def is_stale(lock_payload, ttl_sec):
    age = lock_age(lock_payload)
    if age <= 0:
        return False
    return age > ttl_sec


def acquire_lock(lock_path, payload, ttl_sec):
    if lock_path.exists():
        data = read_lock(lock_path)
        pid = int(data.get("pid", -1)) if isinstance(data, dict) else -1
        age = lock_age(data) if isinstance(data, dict) else 0
        if is_pid_alive(pid) and not is_stale(data, ttl_sec):
            print(f"[lock] busy pid={pid} age_sec={int(age)}", file=sys.stderr)
            return False
        try:
            lock_path.unlink()
        except Exception:
            print("[lock] stale lock present but cannot delete", file=sys.stderr)
            return False
    try:
        with open(lock_path, "x", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except FileExistsError:
        print("[lock] busy (created by another process)", file=sys.stderr)
        return False


def release_lock(lock_path, force=False):
    if not lock_path.exists():
        print("[lock] not found")
        return True
    data = read_lock(lock_path)
    pid = int(data.get("pid", -1)) if isinstance(data, dict) else -1
    if is_pid_alive(pid) and pid != os.getpid() and not force:
        print(f"[lock] owned by pid={pid}; use --force to remove", file=sys.stderr)
        return False
    try:
        lock_path.unlink()
        return True
    except Exception:
        print("[lock] failed to remove", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="Session lock helper for manual opencode runs")
    ap.add_argument("--out-root", required=True, help="Event directory, e.g. ./events/democtf2026")
    ap.add_argument("--id", required=True, type=int, help="Challenge ID")
    ap.add_argument("--mode", choices=["acquire", "release", "status"], default="acquire")
    ap.add_argument("--ttl-sec", type=int, default=0, help="Lock TTL seconds (default: 7200, min: 600)")
    ap.add_argument("--force", action="store_true", help="Force release even if owner pid alive")
    ap.add_argument("--pipeline-id", default="", help="Optional pipeline/session id for auditing")
    args = ap.parse_args()

    out_root = Path(args.out_root).resolve()
    lock_path = lock_path_for(out_root, args.id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    ttl = compute_ttl(args.ttl_sec)

    if args.mode == "status":
        if not lock_path.exists():
            print("unlocked")
            return
        data = read_lock(lock_path)
        age = int(lock_age(data)) if isinstance(data, dict) else 0
        stale = is_stale(data, ttl)
        payload = {"path": str(lock_path), "stale": bool(stale), "age_sec": age, "data": data}
        print(json.dumps(payload, ensure_ascii=False))
        return

    if args.mode == "release":
        ok = release_lock(lock_path, force=args.force)
        sys.exit(0 if ok else 2)

    payload = {
        "pid": os.getpid(),
        "ts": time.time(),
        "challenge_id": args.id,
        "pipeline_id": args.pipeline_id or f"manual-{uuid.uuid4()}",
    }
    ok = acquire_lock(lock_path, payload, ttl)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
