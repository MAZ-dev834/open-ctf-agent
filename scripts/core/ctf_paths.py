#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


DEFAULT_EVENT_ROOT = Path("./events")
DEFAULT_WORKSPACE_ACTIVE = Path("./workspace/active")
DEFAULT_WORKSPACE_STUDY = Path("./workspace/study")
DEFAULT_WORKSPACE_ARCHIVE = Path("./workspace/archive")
DEFAULT_RUNTIME_LOGS = Path("./runtime/logs")
LEGACY_WORK_ROOT = Path("./ctf-work")
ATTACHMENT_DIR_NAMES = {"attachments", "题目附件"}


def _env_path(*keys: str) -> str:
    for key in keys:
        val = str(os.getenv(key, "")).strip()
        if val:
            return val
    return ""


def default_event_root() -> Path:
    raw = _env_path("CTF_EVENT_ROOT")
    return Path(raw) if raw else DEFAULT_EVENT_ROOT


def default_work_root() -> Path:
    raw = _env_path("CTF_WORKSPACE_ROOT", "CTF_WORK_ROOT")
    return Path(raw) if raw else DEFAULT_WORKSPACE_ACTIVE


def default_study_root() -> Path:
    raw = _env_path("CTF_STUDY_ROOT")
    return Path(raw) if raw else DEFAULT_WORKSPACE_STUDY


def default_archive_root() -> Path:
    raw = _env_path("CTF_ARCHIVE_ROOT")
    return Path(raw) if raw else DEFAULT_WORKSPACE_ARCHIVE


def default_runtime_logs() -> Path:
    raw = _env_path("CTF_RUNTIME_LOG_ROOT")
    return Path(raw) if raw else DEFAULT_RUNTIME_LOGS


def resolve_work_root(path: str | Path | None, *, legacy_fallback: bool = True) -> Path:
    chosen = Path(path) if path else default_work_root()
    chosen = chosen.expanduser()
    if legacy_fallback and not chosen.exists():
        legacy = LEGACY_WORK_ROOT.expanduser()
        if legacy.exists():
            return legacy.resolve()
    return chosen.resolve()


def resolve_challenge_dir(path: str | Path) -> Path:
    current = Path(path).expanduser()
    if current.name in ATTACHMENT_DIR_NAMES and current.parent.exists():
        return current.parent
    return current


def resolve_challenge_file_owner(path: str | Path) -> Path:
    current = Path(path).expanduser()
    parent = current.parent if current.is_file() else current
    if parent.name in ATTACHMENT_DIR_NAMES and parent.parent.exists():
        return parent.parent
    return parent


def challenge_metadata_candidates(challenge_dir: str | Path) -> list[Path]:
    base = resolve_challenge_dir(challenge_dir)
    return [
        base / "task.json",
        base / "challenge.json",
        base / "challenge_context.json",
        base / "attachments" / "task.json",
        base / "attachments" / "challenge.json",
        base / "attachments" / "challenge_context.json",
        base / "题目附件" / "task.json",
        base / "题目附件" / "challenge.json",
        base / "题目附件" / "challenge_context.json",
    ]


def challenge_report_candidates(challenge_dir: str | Path) -> list[Path]:
    base = resolve_challenge_dir(challenge_dir)
    return [
        base / "solve_report.json",
        base / "attachments" / "solve_report.json",
        base / "题目附件" / "solve_report.json",
    ]


def challenge_workspace_dirs(challenge_dir: str | Path) -> list[Path]:
    base = resolve_challenge_dir(challenge_dir)
    preferred = base / "workspace"
    legacy = base / "ctf-work"
    existing = [p for p in (preferred, legacy) if p.exists() and p.is_dir()]
    if existing:
        return existing
    return [preferred]


def pick_challenge_workspace(challenge_dir: str | Path) -> Path:
    return challenge_workspace_dirs(challenge_dir)[0]
