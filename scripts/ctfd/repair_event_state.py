#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def normalize_text(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def canonical_category(raw: str) -> str:
    c = normalize_text(raw)
    mapping = {
        "web exploitation": "web",
        "web": "web",
        "pwn": "pwn",
        "binary exploitation": "pwn",
        "rev": "rev",
        "reverse engineering": "rev",
        "re": "rev",
        "crypto": "crypto",
        "cryptography": "crypto",
        "misc": "misc",
        "miscellaneous": "misc",
        "forensics": "forensics",
        "forensic": "forensics",
        "dfir": "forensics",
        "digital forensics": "forensics",
        "osint": "osint",
        "geoint": "osint",
        "geo": "osint",
        "threat intel": "osint",
        "threat intelligence": "osint",
        "malware": "malware",
        "hardware": "forensics",
        "stego": "forensics",
        "steganography": "forensics",
    }
    return mapping.get(c, "unknown")


def infer_category_from_path(path: Path) -> str:
    parts = [p for p in path.parts]
    for marker in ("events",):
        if marker in parts:
            idx = parts.index(marker)
            if len(parts) > idx + 2:
                raw = parts[idx + 2]
                return display_category(raw)
    if len(parts) >= 3:
        return display_category(parts[-3])
    return "Unknown"


def recommended_agent_for_category(raw_cat: str) -> str:
    cat = canonical_category(raw_cat)
    return {
        "web": "ctf-web",
        "pwn": "ctf-pwn",
        "rev": "ctf-rev",
        "crypto": "ctf-crypto",
        "forensics": "ctf-forensics",
        "osint": "ctf-osint",
        "malware": "ctf-malware",
        "misc": "ctf-misc",
        "unknown": "ctf-main",
    }.get(cat, "ctf-main")


def display_category(raw_cat: str) -> str:
    cat = canonical_category(raw_cat)
    return {
        "web": "Web",
        "pwn": "Pwn",
        "rev": "Rev",
        "crypto": "Crypto",
        "forensics": "Forensics",
        "osint": "OSINT",
        "malware": "Malware",
        "misc": "Misc",
        "unknown": "Unknown",
    }[cat]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def dump_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_task_files(event_dir: Path):
    for path in sorted(event_dir.rglob("task.json")):
        yield path


def repair_task_file(task_path: Path) -> dict | None:
    try:
        obj = load_json(task_path)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    before_cat = str(obj.get("category") or "")
    before_agent = str(obj.get("recommended_agent") or "")
    path_cat = infer_category_from_path(task_path)
    normalized_cat = display_category(before_cat)
    after_cat = path_cat if path_cat != "Unknown" else normalized_cat
    after_agent = recommended_agent_for_category(after_cat)
    changed = False
    if before_cat != after_cat:
        obj["category"] = after_cat
        changed = True
    if before_agent != after_agent:
        obj["recommended_agent"] = after_agent
        changed = True
    return {
        "path": task_path,
        "payload": obj,
        "changed": changed,
        "before_category": before_cat,
        "path_category": path_cat,
        "after_category": after_cat,
        "before_agent": before_agent,
        "after_agent": after_agent,
    }


def repair_context_file(context_path: Path) -> dict | None:
    try:
        obj = load_json(context_path)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    before_cat = str(obj.get("category") or "")
    before_agent = str(obj.get("recommended_agent") or "")
    path_cat = infer_category_from_path(context_path)
    normalized_cat = display_category(before_cat)
    after_cat = path_cat if path_cat != "Unknown" else normalized_cat
    after_agent = recommended_agent_for_category(after_cat)
    changed = False
    if before_cat != after_cat:
        obj["category"] = after_cat
        changed = True
    if before_agent != after_agent:
        obj["recommended_agent"] = after_agent
        changed = True
    return {
        "path": context_path,
        "payload": obj,
        "changed": changed,
    }


def repair_status_file(status_path: Path) -> tuple[dict, list[dict]]:
    status = load_json(status_path)
    if not isinstance(status, dict):
        return status, []
    changes = []
    for key, item in status.items():
        if not isinstance(item, dict):
            continue
        before_cat = str(item.get("category") or "")
        challenge_dir = str(item.get("challenge_dir") or "")
        path_cat = infer_category_from_path(Path(challenge_dir)) if challenge_dir else "Unknown"
        normalized_cat = display_category(before_cat)
        after_cat = path_cat if path_cat != "Unknown" else normalized_cat
        before_agent = str(item.get("recommended_agent") or "")
        after_agent = recommended_agent_for_category(after_cat)
        changed = False
        if before_cat != after_cat:
            item["category"] = after_cat
            changed = True
        if before_agent != after_agent:
            item["recommended_agent"] = after_agent
            changed = True
        if changed:
            changes.append(
                {
                    "id": key,
                    "before_category": before_cat,
                    "path_category": path_cat,
                    "after_category": after_cat,
                    "before_agent": before_agent,
                    "after_agent": after_agent,
                }
            )
    return status, changes


def repair_event_state(event_dir: Path | str, *, apply: bool = False) -> dict:
    event_dir = Path(event_dir).expanduser().resolve()
    if not event_dir.exists():
        raise FileNotFoundError(f"event dir not found: {event_dir}")

    task_changes = []
    context_changes = []
    for task_path in iter_task_files(event_dir):
        task_res = repair_task_file(task_path)
        if task_res and task_res["changed"]:
            task_changes.append(task_res)
        context_path = task_path.with_name("challenge_context.json")
        if context_path.exists():
            ctx_res = repair_context_file(context_path)
            if ctx_res and ctx_res["changed"]:
                context_changes.append(ctx_res)

    status_path = event_dir / "status.json"
    status_changes = []
    status_payload = None
    if status_path.exists():
        status_payload, status_changes = repair_status_file(status_path)

    if apply:
        for item in task_changes:
            dump_json(item["path"], item["payload"])
        for item in context_changes:
            dump_json(item["path"], item["payload"])
        if status_payload is not None and status_changes:
            dump_json(status_path, status_payload)

    return {
        "event_dir": event_dir,
        "task_changes": task_changes,
        "context_changes": context_changes,
        "status_changes": status_changes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair event task/context/status category and recommended agent drift.")
    ap.add_argument("--event-dir", required=True, help="Path to events/<event>")
    ap.add_argument("--apply", action="store_true", help="Write changes to disk")
    args = ap.parse_args()

    result = repair_event_state(args.event_dir, apply=args.apply)
    event_dir = result["event_dir"]
    task_changes = result["task_changes"]
    context_changes = result["context_changes"]
    status_changes = result["status_changes"]

    print(f"event_dir: {event_dir}")
    print(f"task_changes: {len(task_changes)}")
    print(f"context_changes: {len(context_changes)}")
    print(f"status_changes: {len(status_changes)}")
    for item in task_changes[:20]:
        rel = item["path"].relative_to(event_dir)
        print(
            f"TASK {rel} | category {item['before_category']} -> {item['after_category']} "
            f"(path={item['path_category']}) | "
            f"agent {item['before_agent']} -> {item['after_agent']}"
        )
    for item in status_changes[:20]:
        print(
            f"STATUS id={item['id']} | category {item['before_category']} -> {item['after_category']} "
            f"(path={item['path_category']}) | "
            f"agent {item['before_agent']} -> {item['after_agent']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
