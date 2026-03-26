#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:
    from ctf_paths import resolve_work_root  # type: ignore


MAX_BYTES = 64 * 1024 * 1024
TEXT_EXTS = {".txt", ".md", ".json", ".jsonl", ".csv", ".log", ".yaml", ".yml", ".py", ".sage"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}
BINARY_EXTS = {".bin", ".dat", ".pcap", ".wav", ".mp3", ".zip", ".gz", ".xz", ".tar"}
PRIORITY_NAMES = {
    "flag": 8.0,
    "candidate": 4.0,
    "final": 4.0,
    "result": 3.0,
    "decoded": 3.0,
    "decode": 3.0,
    "solve": 3.0,
    "output": 2.5,
    "render": 2.0,
    "unwrapped": 2.0,
    "analysis": 1.5,
    "artifact": 1.0,
}
LOW_SIGNAL_NAMES = {
    "log": -3.0,
    "transcript": -3.0,
    "trace": -2.5,
    "debug": -2.0,
    "tmp": -1.5,
    "cache": -1.5,
    "session": -1.0,
}
SKIP_DIRS = {"logs", ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def resolve_project_path(project: str) -> Path:
    raw = Path(project).expanduser()
    if raw.is_dir():
        return raw.resolve()
    base = resolve_work_root(None)
    cand = base / project
    if cand.exists() and cand.is_dir():
        return cand.resolve()
    raise SystemExit(f"project not found: {project}")


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in BINARY_EXTS:
        return "binary"
    return "other"


def _score_name(path: Path) -> tuple[float, list[str]]:
    name = path.name.lower()
    score = 0.0
    reasons: list[str] = []
    for token, value in PRIORITY_NAMES.items():
        if token in name:
            score += value
            reasons.append(f"name:{token}")
    for token, value in LOW_SIGNAL_NAMES.items():
        if token in name:
            score += value
            reasons.append(f"low:{token}")
    if path.suffix.lower() in {".txt", ".json", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bin"}:
        score += 1.0
        reasons.append(f"ext:{path.suffix.lower()}")
    return score, reasons


def _iter_roots(project_dir: Path) -> list[Path]:
    roots: list[Path] = []
    for rel in ["workspace", "artifacts", "attachments", "题目附件", "."]:
        p = (project_dir / rel).resolve() if rel != "." else project_dir.resolve()
        if p.exists() and p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def build_artifact_index(project_dir: Path, *, limit: int = 12) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    roots = _iter_roots(project_dir)
    seen: set[Path] = set()
    for root in roots:
        for path in root.rglob("*"):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                stat = path.stat()
            except Exception:
                continue
            if stat.st_size <= 0 or stat.st_size > MAX_BYTES:
                continue
            score, reasons = _score_name(path)
            rel = path.relative_to(project_dir).as_posix()
            category = _classify(path)
            if category == "image":
                score += 1.5
                reasons.append("type:image")
            elif category == "text":
                score += 1.0
                reasons.append("type:text")
            elif category == "binary":
                score += 0.5
                reasons.append("type:binary")
            if rel.startswith("workspace/"):
                score += 0.8
                reasons.append("root:workspace")
            if rel.startswith("artifacts/"):
                score += 0.4
                reasons.append("root:artifacts")
            items.append(
                {
                    "path": rel,
                    "size": stat.st_size,
                    "type": category,
                    "score": round(score, 2),
                    "reasons": reasons[:8],
                }
            )
    items.sort(key=lambda x: (float(x["score"]), int(x["size"] > 0), -int(x["size"])), reverse=True)
    return {
        "project_dir": str(project_dir),
        "roots": [str(p) for p in roots],
        "items": items[: max(1, limit)],
        "total_candidates": len(items),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank likely high-value local artifacts for artifact-first solving.")
    ap.add_argument("--project", required=True, help="Project path or name under workspace/active")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    project_dir = resolve_project_path(args.project)
    out = build_artifact_index(project_dir, limit=max(1, args.limit))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"project={out['project_dir']}")
        print(f"total_candidates={out['total_candidates']}")
        for item in out["items"]:
            print(f"- {item['score']:.2f} {item['type']} {item['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
