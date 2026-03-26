#!/usr/bin/env python3
from __future__ import annotations

import time


def execute_challenge_run(
    *,
    ctx,
    ch: dict,
    agent_name: str,
    remote_sem,
    reconcile_runtime_paths_func,
    load_event_index_func,
    save_status_index_func,
    save_event_index_func,
    maybe_start_container_func,
    evaluate_remote_readiness_func,
    write_task_files_func,
    launch_session_func,
    append_session_record_func,
    update_event_index_func,
    save_budget_state_func,
    touch_budget_challenge_func,
    estimate_difficulty_func,
    record_preflight_failure_func,
    update_remote_readiness_status_func,
    record_session_phase_func,
    update_run_budget_func,
    finalize_attempt_outputs_func,
    maybe_record_attempt_func,
    write_solve_report_func,
    ensure_auto_writeup_func,
    maybe_auto_learn_func,
    auto_submit_if_requested_func,
    print_func,
):
    run_meta = {}
    run_start_ts = time.time()
    run_end_ts = run_start_ts
    session_uid = f"{ctx.pipeline_id}:{ch['id']}:{int(time.time())}"

    if getattr(ctx.args, "submit_only", False):
        print_func(f"[submit-only] id={ch['id']} scan+submit")
    else:
        def _reconcile():
            idx = load_event_index_func(ctx.out_root)
            rec = reconcile_runtime_paths_func(ctx.out_root, ch, ctx.status, idx)
            if rec.get("changed"):
                save_status_index_func(ctx.out_root, ctx.status)
                save_event_index_func(ctx.out_root, idx)
            return rec

        if ctx.status_lock is None:
            reconcile = _reconcile()
        else:
            with ctx.status_lock:
                reconcile = _reconcile()
        if not reconcile.get("ok"):
            run_meta = {
                "timed_out": False,
                "returncode": 96,
                "preflight_failed": True,
                "failure_reason": "stale_context",
                "message": str(reconcile.get("message") or reconcile.get("reason") or "challenge_dir unresolved"),
            }
            run_end_ts = time.time()
            record_preflight_failure_func(
                ctx=ctx,
                ch=ch,
                session_uid=session_uid,
                agent_name=agent_name,
                run_meta=run_meta,
                run_end_ts=run_end_ts,
                append_session_record_func=append_session_record_func,
                update_event_index_func=update_event_index_func,
                save_status_index_func=save_status_index_func,
                maybe_record_attempt_func=maybe_record_attempt_func,
                write_solve_report_func=write_solve_report_func,
                event_lock=ctx.event_lock,
                status_lock=ctx.status_lock,
                run_start_ts=run_start_ts,
            )
            return

        maybe_start_container_func(ctx.args, ch)
        remote_ready, gate_status, reason, has_target, probe_ready = evaluate_remote_readiness_func(ch)
        ch["remote_ready"] = remote_ready
        ch["remote_gate_status"] = gate_status
        ch["remote_gate_reason"] = reason
        ch["has_remote_target"] = has_target
        ch["container_probe_ready"] = probe_ready
        update_remote_readiness_status_func(
            ctx=ctx,
            ch=ch,
            remote_ready=remote_ready,
            gate_status=gate_status,
            gate_reason=reason,
            has_target=has_target,
            probe_ready=probe_ready,
            save_status_index_func=save_status_index_func,
            status_lock=ctx.status_lock,
        )
        task_path, prompt_path, context_path, env_json_path, env_sh_path = write_task_files_func(ch)
        print_func(
            f"[task] id={ch['id']} task={task_path} prompt={prompt_path} context={context_path} env={env_json_path}"
        )
        start_entry = {
            "phase": "start",
            "ts": time.time(),
            "session_uid": session_uid,
            "opencode_session_id": str(ch.get("_resume_opencode_session_id") or ""),
            "pipeline_id": ctx.pipeline_id,
            "challenge_id": ch.get("id"),
            "challenge_name": ch.get("name", ""),
            "category": ch.get("category", ""),
            "agent": agent_name,
            "model": ctx.model,
            "title": f"{ctx.competition} + {ch.get('category','')} + {ch.get('name','')}",
            "task_path": task_path,
            "prompt_path": prompt_path,
            "context_path": context_path,
            "env_json_path": env_json_path,
            "env_sh_path": env_sh_path,
            "resolved_challenge_dir": ch.get("resolved_challenge_dir", ch.get("challenge_dir", "")),
            "remote_ready": bool(ch.get("remote_ready")),
            "remote_gate_status": ch.get("remote_gate_status", ""),
        }
        record_session_phase_func(
            ctx=ctx,
            ch=ch,
            session_entry=start_entry,
            append_session_record_func=append_session_record_func,
            update_event_index_func=update_event_index_func,
        )
        ctx.mark_round_started(int(ch["id"]))
        run_start = time.time()
        run_start_ts = run_start
        sem = remote_sem if has_target else None
        if sem is not None:
            sem.acquire()
        try:
            run_meta = launch_session_func(ctx.args, ch, task_path, prompt_path, context_path, env_json_path, env_sh_path)
        finally:
            if sem is not None:
                sem.release()
        bound_session_id = str((run_meta or {}).get("opencode_session_id") or "")
        if bound_session_id:
            bind_entry = {
                "phase": "bind",
                "ts": time.time(),
                "session_uid": session_uid,
                "opencode_session_id": bound_session_id,
                "pipeline_id": ctx.pipeline_id,
                "challenge_id": ch.get("id"),
                "challenge_name": ch.get("name", ""),
                "category": ch.get("category", ""),
                "agent": start_entry.get("agent"),
                "model": ctx.model,
                "title": start_entry.get("title"),
                "resolved_challenge_dir": ch.get("resolved_challenge_dir", ch.get("challenge_dir", "")),
            }
            record_session_phase_func(
                ctx=ctx,
                ch=ch,
                session_entry=bind_entry,
                append_session_record_func=append_session_record_func,
                update_event_index_func=update_event_index_func,
            )
        run_end_ts = time.time()
        run_elapsed = run_end_ts - run_start
        end_entry = {
            "phase": "end",
            "ts": time.time(),
            "session_uid": session_uid,
            "opencode_session_id": bound_session_id,
            "pipeline_id": ctx.pipeline_id,
            "challenge_id": ch.get("id"),
            "challenge_name": ch.get("name", ""),
            "category": ch.get("category", ""),
            "agent": start_entry.get("agent"),
            "model": ctx.model,
            "title": start_entry.get("title"),
            "task_path": task_path,
            "prompt_path": prompt_path,
            "context_path": context_path,
            "resolved_challenge_dir": ch.get("resolved_challenge_dir", ch.get("challenge_dir", "")),
            "elapsed_sec": round(run_elapsed, 3),
            "returncode": run_meta.get("returncode") if isinstance(run_meta, dict) else None,
            "timed_out": bool(run_meta.get("timed_out")) if isinstance(run_meta, dict) else False,
            "failure_reason": run_meta.get("failure_reason") if isinstance(run_meta, dict) else "",
            "message": run_meta.get("message") if isinstance(run_meta, dict) else "",
        }
        record_session_phase_func(
            ctx=ctx,
            ch=ch,
            session_entry=end_entry,
            append_session_record_func=append_session_record_func,
            update_event_index_func=update_event_index_func,
        )
        update_run_budget_func(
            ctx=ctx,
            challenge_id=ch["id"],
            run_elapsed=run_elapsed,
            timed_out=bool(run_meta and run_meta.get("timed_out")),
            difficulty_score=estimate_difficulty_func(ch),
            remote_ready=bool(remote_ready),
            gate_status=gate_status,
            gate_reason=reason,
            touch_budget_challenge_func=touch_budget_challenge_func,
            save_budget_state_func=save_budget_state_func,
            budget_lock=ctx.budget_lock,
        )

    finalize_attempt_outputs_func(
        ctx=ctx,
        ch=ch,
        args_submit_func=lambda: auto_submit_if_requested_func(
            ctx.args, ch, ctx.status, status_lock=ctx.status_lock, budget_state=ctx.budget_state
        ),
        save_budget_state_func=save_budget_state_func,
        update_event_index_func=update_event_index_func,
        maybe_record_attempt_func=maybe_record_attempt_func,
        write_solve_report_func=write_solve_report_func,
        ensure_auto_writeup_func=ensure_auto_writeup_func,
        maybe_auto_learn_func=maybe_auto_learn_func,
        run_meta=run_meta,
        session_uid=session_uid,
        agent_name=agent_name,
        run_start_ts=run_start_ts,
        run_end_ts=run_end_ts,
    )
