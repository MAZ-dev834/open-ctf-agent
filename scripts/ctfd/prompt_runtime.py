#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_prompt_fragment(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
    return ""


def load_pipeline_prompt_fragments(category: str) -> list[str]:
    prompts_dir = _repo_root() / "prompts"
    parts = []
    shared = _read_prompt_fragment(prompts_dir / "pipeline-shared.txt")
    if shared:
        parts.append(shared)
    cat = str(category or "").strip().lower()
    category_map = {
        "web": "pipeline-web.txt",
        "pwn": "pipeline-pwn.txt",
        "rev": "pipeline-rev.txt",
        "crypto": "pipeline-crypto.txt",
        "misc": "pipeline-misc.txt",
        "forensics": "pipeline-forensics.txt",
        "osint": "pipeline-osint.txt",
        "malware": "pipeline-malware.txt",
    }
    cat_name = category_map.get(cat)
    if cat_name:
        cat_part = _read_prompt_fragment(prompts_dir / cat_name)
        if cat_part:
            parts.append(cat_part)
    return parts


def compose_pipeline_prompt(*, category: str, challenge_prompt: str) -> str:
    parts = load_pipeline_prompt_fragments(category)
    cp = str(challenge_prompt or "").strip()
    if cp:
        parts.append(cp)
    return "\n\n".join(p for p in parts if str(p).strip()).strip() + "\n"
