#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path


def record_session_phase(
    *,
    ctx,
    ch: dict,
    session_entry: dict,
    append_session_record_func,
    update_event_index_func,
):
    append_session_record_func(ctx.out_root, session_entry)
    if ctx.event_lock is None:
        update_event_index_func(
            ctx.out_root,
            ch,
            status_entry=ctx.status_entry(ch),
            session_entry=session_entry,
            competition=ctx.competition,
        )
        return
    with ctx.event_lock:
        update_event_index_func(
            ctx.out_root,
            ch,
            status_entry=ctx.status_entry(ch),
            session_entry=session_entry,
            competition=ctx.competition,
        )


def update_remote_readiness_status(
    *,
    ctx,
    ch: dict,
    remote_ready: bool,
    gate_status: str,
    gate_reason: str,
    has_target: bool,
    probe_ready: bool,
    save_status_index_func,
    status_lock=None,
):
    def _write():
        ent = ctx.status.setdefault(str(ch["id"]), {})
        ent["remote_ready"] = bool(remote_ready)
        ent["remote_gate_status"] = gate_status
        ent["remote_gate_reason"] = gate_reason
        ent["has_remote_target"] = bool(has_target)
        ent["container_probe_ready"] = bool(probe_ready)
        ent["provider_probes"] = ch.get("provider_probes", [])
        save_status_index_func(ctx.out_root, ctx.status)

    if status_lock is None:
        _write()
        return
    with status_lock:
        _write()


def record_preflight_failure(
    *,
    ctx,
    ch: dict,
    session_uid: str,
    agent_name: str,
    run_meta: dict,
    run_end_ts: float,
    append_session_record_func,
    update_event_index_func,
    save_status_index_func,
    maybe_record_attempt_func,
    write_solve_report_func,
    event_lock=None,
    status_lock=None,
    run_start_ts: float = 0.0,
):
    end_entry = {
        "phase": "end",
        "ts": run_end_ts,
        "session_uid": session_uid,
        "pipeline_id": ctx.pipeline_id,
        "challenge_id": ch.get("id"),
        "challenge_name": ch.get("name", ""),
        "category": ch.get("category", ""),
        "agent": agent_name,
        "model": ctx.model,
        "title": f"{ctx.competition} + {ch.get('category','')} + {ch.get('name','')}",
        "resolved_challenge_dir": ch.get("resolved_challenge_dir", ""),
        "elapsed_sec": 0.0,
        "returncode": 96,
        "timed_out": False,
        "failure_reason": "stale_context",
        "message": str(run_meta.get("message") or ""),
    }
    record_session_phase(
        ctx=ctx,
        ch=ch,
        session_entry=end_entry,
        append_session_record_func=append_session_record_func,
        update_event_index_func=update_event_index_func,
    )

    def _write_status():
        status_entry = ctx.status.get(str(ch["id"]), {})
        status_entry["last_session_error"] = str(run_meta.get("message") or "")
        save_status_index_func(ctx.out_root, ctx.status)
        return status_entry

    if status_lock is None:
        status_entry = _write_status()
    else:
        with status_lock:
            status_entry = _write_status()

    maybe_record_attempt_func(ch, run_meta, status_entry, run_start_ts, run_end_ts)
    write_solve_report_func(ch, session_uid, agent_name, ctx.model, run_meta, status_entry, run_start_ts, run_end_ts)


def update_run_budget(
    *,
    ctx,
    challenge_id: int,
    run_elapsed: float,
    timed_out: bool,
    difficulty_score: float,
    remote_ready: bool,
    gate_status: str,
    gate_reason: str,
    touch_budget_challenge_func,
    save_budget_state_func,
    budget_lock=None,
):
    def _write():
        st = touch_budget_challenge_func(ctx.budget_state, challenge_id)
        st["session_runs"] = int(st.get("session_runs", 0)) + 1
        st["session_seconds"] = float(st.get("session_seconds", 0.0)) + float(run_elapsed)
        if timed_out:
            st["session_timeouts"] = int(st.get("session_timeouts", 0)) + 1
        st["difficulty_score"] = difficulty_score
        st["remote_ready"] = bool(remote_ready)
        st["remote_gate_status"] = gate_status
        st["remote_gate_reason"] = gate_reason
        st["last_update_ts"] = time.time()
        save_budget_state_func(ctx.out_root, ctx.budget_state)

    if budget_lock is None:
        _write()
        return
    with budget_lock:
        _write()


def finalize_attempt_outputs(
    *,
    ctx,
    ch: dict,
    args_submit_func,
    save_budget_state_func,
    update_event_index_func,
    maybe_record_attempt_func,
    write_solve_report_func,
    ensure_auto_writeup_func,
    maybe_auto_learn_func,
    run_meta: dict,
    session_uid: str,
    agent_name: str,
    run_start_ts: float,
    run_end_ts: float,
):
    args_submit_func()
    if ctx.event_lock is None:
        update_event_index_func(ctx.out_root, ch, status_entry=ctx.status_entry(ch), competition=ctx.competition)
    else:
        with ctx.event_lock:
            update_event_index_func(ctx.out_root, ch, status_entry=ctx.status_entry(ch), competition=ctx.competition)
    if ctx.budget_lock is None:
        save_budget_state_func(ctx.out_root, ctx.budget_state)
    else:
        with ctx.budget_lock:
            save_budget_state_func(ctx.out_root, ctx.budget_state)
    status_entry = ctx.status.get(str(ch["id"]), {})
    maybe_record_attempt_func(ch, run_meta, status_entry, run_start_ts, run_end_ts)
    write_solve_report_func(ch, session_uid, agent_name, ctx.model, run_meta, status_entry, run_start_ts, run_end_ts)
    ensure_auto_writeup_func(ch)
    maybe_auto_learn_func(ch, status_entry)
