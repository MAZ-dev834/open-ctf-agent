#!/usr/bin/env python3
from __future__ import annotations


def choose_agent_name(ch: dict, requested_agent: str, resolve_agent_name_func) -> str:
    resolved = resolve_agent_name_func(requested_agent)
    return resolved or "ctf"


def prepare_challenge_dispatch(
    *,
    ctx,
    ch: dict,
    requested_agent: str,
    resolve_agent_name_func,
    canonical_category_func,
    recommended_agent_for_category_func,
    resolve_resumable_session_for_challenge_func,
    validate_resumable_session_agent_func,
    should_skip_for_duplicate_session_func,
    resolve_opencode_session_for_active_record_func,
    close_orphan_duplicate_session_func,
    acquire_lock_func,
    build_session_title_func,
    append_session_record_func,
    load_event_index_func,
    load_status_index_func,
    update_event_index_func,
    print_func,
    stderr_print_func,
):
    agent_name = choose_agent_name(ch, requested_agent, resolve_agent_name_func)
    if requested_agent == "ctf-main" and canonical_category_func(ch.get("category", "")) != "unknown":
        stderr_print_func(
            f"[warn] id={ch['id']} category={ch.get('category','')} was forced onto ctf-main; "
            f"specialist route would be {recommended_agent_for_category_func(ch.get('category', ''))}"
        )

    ch.pop("_resume_opencode_session_id", None)

    resumable_sid = resolve_resumable_session_for_challenge_func(ch, ctx.status_entry(ch))
    if resumable_sid:
        ok_resume, resume_reason = validate_resumable_session_agent_func(resumable_sid, agent_name)
        if ok_resume:
            ch["_resume_opencode_session_id"] = resumable_sid
            print_func(f"[session] reuse id={ch['id']} opencode_session={resumable_sid}")
        else:
            print_func(
                f"[session] refuse_resume id={ch['id']} opencode_session={resumable_sid} "
                f"expected_agent={agent_name} reason={resume_reason}"
            )

    dup = should_skip_for_duplicate_session_func(ch)
    if dup is not None:
        resume_sid = ""
        if getattr(ctx.args, "resume_incomplete_sessions", False):
            resume_sid = resolve_opencode_session_for_active_record_func(ch, dup, ctx.competition)
        if not resume_sid:
            resume_sid = str(ch.get("_resume_opencode_session_id") or "").strip()
        if resume_sid:
            ok_resume, resume_reason = validate_resumable_session_agent_func(resume_sid, agent_name)
            if ok_resume:
                ch["_resume_opencode_session_id"] = resume_sid
                print_func(
                    f"[session] resume id={ch['id']} existing_session={dup.get('session_uid','')}"
                    f" opencode_session={resume_sid}"
                )
            else:
                print_func(
                    f"[session] refuse_resume id={ch['id']} existing_session={dup.get('session_uid','')}"
                    f" opencode_session={resume_sid} expected_agent={agent_name} reason={resume_reason}"
                )
                resume_sid = ""
        else:
            print_func(
                f"[session] skip id={ch['id']} existing_session={dup.get('session_uid','')}"
                " has no resolvable opencode session id; auto-closing orphan and continuing"
            )
            close_orphan_duplicate_session_func(
                out_root=ctx.out_root,
                competition=ctx.competition,
                ch=ch,
                dup=dup,
                agent_name=agent_name,
                model=ctx.model,
                build_session_title_func=build_session_title_func,
                append_session_record_func=append_session_record_func,
                load_event_index_func=load_event_index_func,
                load_status_index_func=load_status_index_func,
                update_event_index_func=update_event_index_func,
            )

    lock_path, lock_message = acquire_lock_func(ch)
    if lock_message:
        if "stale" in lock_message or "warn" in lock_message:
            stderr_print_func(lock_message)
        else:
            print_func(lock_message)

    return {
        "agent_name": agent_name,
        "lock_path": lock_path,
    }
