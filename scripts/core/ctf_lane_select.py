#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:  # pragma: no cover
    from ctf_paths import resolve_work_root  # type: ignore


def resolve_project_path(project: str) -> Path:
    raw = Path(project).expanduser()
    if raw.is_dir():
        return raw.resolve()
    base = resolve_work_root(None)
    cand = base / project
    if cand.exists() and cand.is_dir():
        return cand.resolve()
    raise SystemExit(f"project not found: {project}")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_text(project_dir: Path) -> str:
    candidates = [
        project_dir / "task.json",
        project_dir / "challenge.json",
        project_dir / "challenge.txt",
        project_dir / "attachments" / "challenge.txt",
        project_dir / "题目附件" / "challenge.txt",
    ]
    for p in candidates:
        if not p.exists():
            continue
        if p.suffix.lower() == ".json":
            try:
                data = json.loads(read_text(p))
                if isinstance(data, dict):
                    return json.dumps(data, ensure_ascii=False)
            except Exception:
                continue
        else:
            text = read_text(p).strip()
            if text:
                return text
    return ""


def collect_attachments(project_dir: Path) -> list[Path]:
    roots = [project_dir / "attachments", project_dir / "题目附件"]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                files.append(p)
    return files


def classify_lane(project_dir: Path) -> dict:
    text = load_text(project_dir).lower()
    files = collect_attachments(project_dir)
    file_count = len(files)
    total_size = sum(p.stat().st_size for p in files) if files else 0

    # Interaction risk signals
    risk_terms = [
        "oracle", "pow", "query", "cooldown", "rate limit", "timeout", "session",
        "interactive", "stage", "layer", "verify", "challenge server", "nc ",
        "netcat", "remote", "instance", "connection",
    ]
    risk_hits = sum(1 for t in risk_terms if t in text)

    # Heavy artifact signals
    heavy_terms = [
        "pcap", "pcapng", "memory dump", "memdump", "disk image", "e01", "vmdk",
        "firmware", "apk", ".elf", ".exe", ".dll", ".so", "wasm",
    ]
    heavy_hits = sum(1 for t in heavy_terms if t in text)

    reasons: list[str] = []
    lane = "fast"

    if file_count >= 4 or total_size >= 10 * 1024 * 1024:
        lane = "deep"
        reasons.append("attachments_many_or_large")
    if risk_hits >= 2:
        lane = "deep"
        reasons.append("interactive_risk_signals")
    if heavy_hits >= 2:
        lane = "deep"
        reasons.append("heavy_artifact_signals")

    if lane == "fast":
        if file_count <= 1:
            reasons.append("single_or_no_attachment")
        if total_size and total_size <= 2 * 1024 * 1024:
            reasons.append("attachments_small")
        if risk_hits == 0:
            reasons.append("no_interactive_risk_signal")

    return {
        "lane": lane,
        "file_count": file_count,
        "total_size": total_size,
        "risk_hits": risk_hits,
        "heavy_hits": heavy_hits,
        "reasons": reasons,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Recommend fast/deep lane based on challenge context.")
    p.add_argument("--project", required=True, help="Project path or name under workspace/active")
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = p.parse_args()

    project_dir = resolve_project_path(args.project)
    rec = classify_lane(project_dir)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    print(f"lane: {rec['lane']}")
    print(f"file_count: {rec['file_count']}")
    print(f"total_size: {rec['total_size']}")
    print(f"risk_hits: {rec['risk_hits']}")
    print(f"heavy_hits: {rec['heavy_hits']}")
    if rec["reasons"]:
        print("reasons:")
        for r in rec["reasons"]:
            print(f"- {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
