#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ENV_CACHE: dict[str, str] | None = None


def repo_root() -> Path:
    return REPO_ROOT


def _load_repo_env() -> dict[str, str]:
    global _REPO_ENV_CACHE
    if _REPO_ENV_CACHE is not None:
        return _REPO_ENV_CACHE
    merged: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = repo_root() / name
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                merged[k.strip()] = v.strip().strip("'\"")
        except Exception:
            continue
    _REPO_ENV_CACHE = merged
    return merged


def env_first(*keys: str, default: str = "") -> str:
    repo_env = _load_repo_env()
    for key in keys:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
        repo_value = str(repo_env.get(key, "")).strip()
        if repo_value:
            return repo_value
    return default


def resolve_repo_path(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return (repo_root() / p).resolve()


def default_opencode_attach_url() -> str:
    return env_first("OPENCODE_ATTACH_URL", default="http://127.0.0.1:4096")


def default_opencode_db_path() -> Path:
    raw = env_first("OPENCODE_DB", default=str(Path.home() / ".local/share/opencode/opencode.db"))
    return Path(raw).expanduser()


def default_opencode_config_path() -> Path:
    raw = env_first("OPENCODE_CONFIG", default=str(repo_root() / ".opencode" / "opencode.json"))
    return resolve_repo_path(raw)


def default_vlm_base_url() -> str:
    return env_first(
        "CTF_VLM_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        default="http://127.0.0.1:1234/v1",
    ).rstrip("/")


def default_vlm_model() -> str:
    return env_first("CTF_VLM_MODEL", "OPENAI_MODEL", "MODEL", default="qwen3.5-2b")


def default_vlm_api_key() -> str:
    return env_first("CTF_VLM_API_KEY", "OPENAI_API_KEY", "API_KEY", default="EMPTY")


def default_agent_model() -> str:
    return env_first("CTF_MODEL", "OPENAI_MODEL", "MODEL", default="")


def default_first_blood_model() -> str:
    return env_first(
        "CTF_FIRST_BLOOD_MODEL",
        "FIRST_BLOOD_MODEL",
        "CTF_MODEL",
        "OPENAI_MODEL",
        "MODEL",
        default="",
    )


def runtime_capabilities() -> dict[str, str]:
    opencode_cfg = default_opencode_config_path()
    return {
        "ctf_model": default_agent_model(),
        "ctf_first_blood_model": default_first_blood_model(),
        "repo_root": str(repo_root()),
        "opencode_attach_url": default_opencode_attach_url(),
        "opencode_db": str(default_opencode_db_path()),
        "opencode_config": str(opencode_cfg),
        "opencode_config_exists": "1" if opencode_cfg.exists() else "0",
        "vlm_base_url": default_vlm_base_url(),
        "vlm_model": default_vlm_model(),
    }
