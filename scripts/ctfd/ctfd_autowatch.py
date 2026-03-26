#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set


def load_status(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_id_set(values: Sequence[int]) -> Set[int]:
    out: Set[int] = set()
    for value in values or []:
        try:
            out.add(int(value))
        except Exception:
            continue
    return out


def parse_hhmm(value: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in str(value).split(':')]
    if len(parts) not in (2, 3):
        raise ValueError(f'invalid HH:MM[:SS] time: {value!r}')
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f'invalid HH:MM[:SS] time: {value!r}')
    return hour, minute, second


def next_daily_time(spec: str) -> float:
    now = datetime.now().astimezone()
    hour, minute, second = parse_hhmm(spec)
    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target.timestamp()


def format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')


def sleep_until(ts: float, verbose: bool = True) -> None:
    while True:
        now = time.time()
        remaining = ts - now
        if remaining <= 0:
            return
        chunk = min(remaining, 30.0)
        if verbose:
            print(f'[wait] remaining={remaining:.1f}s target={format_ts(ts)}', flush=True)
        time.sleep(max(1.0, chunk))
        verbose = False


def build_fetch_cmd(args: argparse.Namespace) -> List[str]:
    cmd = [sys.executable, str(Path(__file__).with_name('fetch_ctfd.py')), '--out', args.event_dir]
    if args.base:
        cmd += ['--base', args.base]
    if args.session:
        cmd += ['--session', args.session]
    if args.token:
        cmd += ['--token', args.token]
    if args.env_file:
        cmd += ['--env-file', args.env_file]
    if args.flag_prefix:
        cmd += ['--flag-prefix', args.flag_prefix]
    if args.include_solved:
        cmd += ['--include-solved']
    for cat in args.category or []:
        cmd += ['--category', cat]
    return cmd


def build_pipeline_cmd(args: argparse.Namespace, ids: Iterable[int]) -> List[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).with_name('ctfd_pipeline.py')),
        '--out-root', args.event_dir,
        '--competition', args.competition,
    ]
    if args.mode:
        cmd += ['--mode', args.mode]
    if args.env_file:
        cmd += ['--env-file', args.env_file]
    if args.only_unsolved:
        cmd += ['--only-unsolved']
    if args.auto_submit:
        cmd += ['--auto-submit']
    if args.workers is not None:
        cmd += ['--workers', str(args.workers)]
    if args.max_active_remote is not None:
        cmd += ['--max-active-remote', str(args.max_active_remote)]
    if args.auto_timeout:
        cmd += ['--auto-timeout']
    if args.global_time_budget_min is not None:
        cmd += ['--global-time-budget-min', str(args.global_time_budget_min)]
    if args.base:
        cmd += ['--base', args.base]
    if args.session:
        cmd += ['--session', args.session]
    if args.token:
        cmd += ['--token', args.token]
    if args.agent:
        cmd += ['--agent', args.agent]
    if args.model:
        cmd += ['--model', args.model]
    if args.first_blood_mode:
        cmd += ['--first-blood-mode']
    for cat in args.category or []:
        cmd += ['--category', cat]
    if args.start_containers:
        cmd += ['--start-containers']
    if args.per_task_timeout_sec is not None:
        cmd += ['--per-task-timeout-sec', str(args.per_task_timeout_sec)]
    if args.min_interval is not None:
        cmd += ['--min-interval', str(args.min_interval)]
    if args.pull_submissions:
        cmd += ['--pull-submissions']
    if args.pull_challenge_status:
        cmd += ['--pull-challenge-status', 'on']
    if args.allow_duplicate_sessions:
        cmd += ['--allow-duplicate-sessions']
    if args.resume_incomplete_sessions:
        cmd += ['--resume-incomplete-sessions', 'on']
    if args.min_candidate_score is not None:
        cmd += ['--min-candidate-score', str(args.min_candidate_score)]
    if args.allow_unscored_submit:
        cmd += ['--allow-unscored-submit']
    if args.max_incorrect_per_challenge is not None:
        cmd += ['--max-incorrect-per-challenge', str(args.max_incorrect_per_challenge)]
    if args.submit_cooldown_sec is not None:
        cmd += ['--submit-cooldown-sec', str(args.submit_cooldown_sec)]
    if args.image_watch is not None:
        cmd += ['--image-watch', args.image_watch]
    if args.image_watch_interval_sec is not None:
        cmd += ['--image-watch-interval-sec', str(args.image_watch_interval_sec)]
    if args.image_watch_max_per_scan is not None:
        cmd += ['--image-watch-max-per-scan', str(args.image_watch_max_per_scan)]
    for cid in sorted(set(int(x) for x in ids)):
        cmd += ['--id', str(cid)]
    return cmd


def diff_new_ids(before: Dict[str, dict], after: Dict[str, dict]) -> List[int]:
    out: List[int] = []
    for key, value in after.items():
        if key in before:
            continue
        try:
            cid = int(value.get('id', key))
        except Exception:
            continue
        out.append(cid)
    return sorted(out)


def run_cmd(cmd: Sequence[str], cwd: Path, dry_run: bool = False) -> int:
    printable = ' '.join(subprocess.list2cmdline([part]) for part in cmd)
    print(f'[exec] cwd={cwd} cmd={printable}', flush=True)
    if dry_run:
        return 0
    proc = subprocess.run(list(cmd), cwd=str(cwd), check=False)
    return int(proc.returncode)


def select_new_ids(new_ids: Iterable[int], include_ids: Set[int], exclude_ids: Set[int]) -> List[int]:
    out: List[int] = []
    for cid in new_ids:
        if include_ids and cid not in include_ids:
            continue
        if cid in exclude_ids:
            continue
        out.append(cid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='Watch CTFd for newly released challenges, fetch them, then trigger pipeline automatically.')
    ap.add_argument('--event-dir', required=True, help='Event directory, e.g. events/democtf2026')
    ap.add_argument('--competition', required=True, help='Competition name for ctfd_pipeline session titles')
    ap.add_argument('--env-file', help='Custom .env path; default: <event-dir>/.env')
    ap.add_argument('--base', help='CTFd base URL')
    ap.add_argument('--session', help='CTFd session cookie')
    ap.add_argument('--token', help='CTFd token')
    ap.add_argument('--flag-prefix', help='Fallback flag prefix for fetch_ctfd.py')
    ap.add_argument('--category', action='append', help='Category filter (repeatable, comma-separated)')
    ap.add_argument('--include-solved', action='store_true', help='Pass --include-solved to fetch_ctfd.py')
    ap.add_argument('--start-at', help='Wait until next local HH:MM[:SS] before first poll, e.g. 01:00 or 01:00:05')
    ap.add_argument('--start-delay-sec', type=float, default=0.0, help='Additional delay before first poll')
    ap.add_argument('--poll-interval-sec', type=float, default=20.0, help='Polling interval after the first cycle')
    ap.add_argument('--max-polls', type=int, default=0, help='Stop after N polls (0 = unlimited)')
    ap.add_argument('--run-existing-unsolved-once', action='store_true', help='Before waiting, run a normal pipeline pass for existing unsolved challenges')
    ap.add_argument('--include-id', action='append', type=int, default=[], help='Only auto-run these new challenge ids (repeatable)')
    ap.add_argument('--exclude-id', action='append', type=int, default=[], help='Skip these new challenge ids (repeatable)')
    ap.add_argument('--mode', default='match', choices=['match', 'submit-only', 'maint'], help='Pipeline mode for auto-started runs')
    ap.add_argument('--only-unsolved', action='store_true', help='Pass --only-unsolved to pipeline')
    ap.add_argument('--auto-submit', action='store_true', help='Pass --auto-submit to pipeline')
    ap.add_argument('--workers', type=int, default=1, help='Pipeline workers for each triggered run')
    ap.add_argument('--max-active-remote', type=int, default=1, help='Pipeline remote concurrency for each triggered run')
    ap.add_argument('--auto-timeout', action='store_true', help='Pass --auto-timeout to pipeline')
    ap.add_argument('--global-time-budget-min', type=int, help='Pipeline global time budget')
    ap.add_argument('--agent', help='Pipeline agent override')
    ap.add_argument('--model', help='Pipeline model override; default comes from CTF_MODEL / OPENAI_MODEL / MODEL')
    ap.add_argument('--first-blood-mode', action='store_true', help='一血模式：透传给 pipeline，优先使用 CTF_FIRST_BLOOD_MODEL')
    ap.add_argument('--start-containers', action='store_true', help='Pass --start-containers to pipeline')
    ap.add_argument('--per-task-timeout-sec', type=int, help='Pipeline per-task timeout')
    ap.add_argument('--min-interval', type=int, help='Pipeline submit minimum interval seconds')
    ap.add_argument('--pull-submissions', action='store_true', help='Pass --pull-submissions to pipeline')
    ap.add_argument('--pull-challenge-status', action='store_true', help='Pass --pull-challenge-status on to pipeline')
    ap.add_argument('--allow-duplicate-sessions', action='store_true', help='Pass --allow-duplicate-sessions to pipeline')
    ap.add_argument('--resume-incomplete-sessions', action='store_true', help='Pass --resume-incomplete-sessions on to pipeline')
    ap.add_argument('--min-candidate-score', type=float, help='Pipeline submit threshold')
    ap.add_argument('--allow-unscored-submit', action='store_true', help='Pass --allow-unscored-submit to pipeline')
    ap.add_argument('--max-incorrect-per-challenge', type=int, help='Pipeline incorrect submit cap')
    ap.add_argument('--submit-cooldown-sec', type=int, help='Pipeline submit cooldown')
    ap.add_argument('--image-watch', choices=['on', 'off'], help='Pipeline image-watch mode override')
    ap.add_argument('--image-watch-interval-sec', type=int, help='Pipeline image-watch scan interval')
    ap.add_argument('--image-watch-max-per-scan', type=int, help='Pipeline image-watch max per scan')
    ap.add_argument('--dry-run', action='store_true', help='Print commands without executing them')
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    event_dir = (repo_root / args.event_dir).resolve() if not os.path.isabs(args.event_dir) else Path(args.event_dir).resolve()
    status_path = event_dir / 'status.json'
    include_ids = parse_id_set(args.include_id)
    exclude_ids = parse_id_set(args.exclude_id)

    if args.run_existing_unsolved_once:
        base_cmd = build_pipeline_cmd(args, [])
        rc = run_cmd(base_cmd, repo_root, dry_run=args.dry_run)
        if rc != 0:
            print(f'[warn] initial existing-unsolved pipeline returned rc={rc}', flush=True)

    if args.start_at:
        ts = next_daily_time(args.start_at)
        sleep_until(ts, verbose=True)
    if args.start_delay_sec and args.start_delay_sec > 0:
        print(f'[wait] additional delay {args.start_delay_sec:.1f}s', flush=True)
        time.sleep(args.start_delay_sec)

    polls = 0
    while True:
        polls += 1
        before = load_status(status_path)
        fetch_cmd = build_fetch_cmd(args)
        rc = run_cmd(fetch_cmd, repo_root, dry_run=args.dry_run)
        if rc != 0:
            print(f'[warn] fetch failed rc={rc}', flush=True)
        after = load_status(status_path)
        new_ids = select_new_ids(diff_new_ids(before, after), include_ids, exclude_ids)
        if new_ids:
            print(f'[new] detected challenge ids={new_ids}', flush=True)
            pipe_cmd = build_pipeline_cmd(args, new_ids)
            rc = run_cmd(pipe_cmd, repo_root, dry_run=args.dry_run)
            if rc != 0:
                print(f'[warn] pipeline failed rc={rc} ids={new_ids}', flush=True)
        else:
            print(f'[poll] no new challenges detected (poll #{polls})', flush=True)

        if args.max_polls and polls >= args.max_polls:
            return 0
        time.sleep(max(args.poll_interval_sec, 1.0))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
