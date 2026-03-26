#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    from ctf_meta import normalize_project_key
except Exception:  # pragma: no cover
    import sys

    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.learn.ctf_meta import normalize_project_key

try:
    from scripts.core.ctf_paths import resolve_work_root
except Exception:  # pragma: no cover
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.core.ctf_paths import resolve_work_root

def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_runbook(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^- Title:\s*(.+)$", text, flags=re.M)
    if m:
        out["title"] = m.group(1).strip()
    m = re.search(r"^- Category:\s*(.+)$", text, flags=re.M)
    if m:
        out["category"] = m.group(1).strip()
    return out


def discover_status_entries(search_root: Path) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for pattern in ("*/status.json", "events/*/status.json"):
        for p in search_root.glob(pattern):
            rp = str(p.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            comp = p.parent.name
            data = read_json(p)
            if not isinstance(data, dict):
                continue
            for k, v in data.items():
                if not isinstance(v, dict):
                    continue
                rows.append(
                    {
                        "competition": comp,
                        "status_path": str(p),
                        "id": v.get("id", k),
                        "name": v.get("name", ""),
                        "category": v.get("category", ""),
                        "challenge_dir": v.get("challenge_dir", ""),
                    }
                )
    return rows


def build_hint_maps(status_rows: list[dict]) -> tuple[dict, dict]:
    by_project_name: dict[str, list[dict]] = defaultdict(list)
    by_project_key: dict[str, list[dict]] = defaultdict(list)
    for r in status_rows:
        challenge_dir = str(r.get("challenge_dir") or "").strip()
        if challenge_dir:
            for local_root_name in ("workspace", "ctf-work"):
                local_work_root = Path(challenge_dir) / local_root_name
                if local_work_root.exists():
                    for d in local_work_root.iterdir():
                        if d.is_dir() and d.name != "_archive":
                            ent = dict(r)
                            ent["source"] = f"status.challenge_dir.{local_root_name}"
                            ent["confidence"] = 1.0
                            by_project_name[d.name].append(ent)
                            by_project_key[normalize_project_key(d.name)].append(ent)

        for label, conf in ((r.get("name", ""), 0.78), (Path(challenge_dir).name if challenge_dir else "", 0.72)):
            if not label:
                continue
            key = slugify(label)
            if not key:
                continue
            ent = dict(r)
            ent["source"] = "status.name_heuristic"
            ent["confidence"] = conf
            by_project_key[key].append(ent)
    return by_project_name, by_project_key


def project_metadata(project_dir: Path) -> dict:
    meta = {
        "challenge_id": None,
        "challenge_name": "",
        "category": "",
    }
    for rel in ("task.json", "challenge.json", "attachments/challenge.json", "题目附件/challenge.json"):
        p = project_dir / rel
        if not p.exists():
            continue
        d = read_json(p)
        if not isinstance(d, dict):
            continue
        if meta["challenge_id"] is None and d.get("challenge_id") is not None:
            meta["challenge_id"] = d.get("challenge_id")
        if meta["challenge_id"] is None and d.get("id") is not None:
            meta["challenge_id"] = d.get("id")
        if not meta["challenge_name"]:
            meta["challenge_name"] = str(d.get("name") or d.get("title") or "").strip()
        if not meta["category"]:
            meta["category"] = str(d.get("category") or "").strip()

    rb = parse_runbook(project_dir / "runbook.md")
    if not meta["challenge_name"] and rb.get("title"):
        meta["challenge_name"] = rb["title"]
    if not meta["category"] and rb.get("category"):
        meta["category"] = rb["category"]
    return meta


def select_mapping(
    project_dir: Path,
    by_project_name: dict[str, list[dict]],
    by_project_key: dict[str, list[dict]],
    status_rows: list[dict],
) -> tuple[dict, list[dict]]:
    name = project_dir.name
    key = normalize_project_key(name)
    local = project_metadata(project_dir)

    candidates: list[dict] = []
    candidates.extend(by_project_name.get(name, []))
    candidates.extend(by_project_key.get(key, []))
    if not candidates and local.get("challenge_id") is not None:
        for r in status_rows:
            if str(r.get("id")) == str(local["challenge_id"]):
                ent = dict(r)
                ent["source"] = "task.challenge_id"
                ent["confidence"] = 0.9
                candidates.append(ent)

    def score(c: dict) -> float:
        s = float(c.get("confidence", 0.0))
        if local.get("challenge_id") is not None and str(c.get("id")) == str(local["challenge_id"]):
            s += 0.15
        if local.get("challenge_name") and c.get("name") and slugify(c["name"]) == slugify(local["challenge_name"]):
            s += 0.1
        return s

    candidates = sorted(candidates, key=score, reverse=True)
    chosen = candidates[0] if candidates else {}
    return chosen, candidates


def build_index(ctf_work: Path, search_root: Path) -> tuple[list[dict], dict]:
    status_rows = discover_status_entries(search_root)
    by_name, by_key = build_hint_maps(status_rows)
    rows = []
    issues = {"missing_mapping": [], "conflicts": []}
    if not ctf_work.exists():
        summary = {
            "projects_total": 0,
            "mapped": 0,
            "missing_mapping": 0,
            "conflicts": 0,
        }
        return rows, {"summary": summary, "issues": issues}

    for d in sorted([x for x in ctf_work.iterdir() if x.is_dir() and x.name != "_archive"]):
        chosen, candidates = select_mapping(d, by_name, by_key, status_rows)
        local = project_metadata(d)
        rec = {
            "project_dir": str(d),
            "project_name": d.name,
            "project_key": normalize_project_key(d.name),
            "competition": chosen.get("competition", ""),
            "challenge_id": chosen.get("id", local.get("challenge_id")),
            "challenge_name": chosen.get("name") or local.get("challenge_name", ""),
            "category": chosen.get("category") or local.get("category", ""),
            "source_path": chosen.get("status_path", ""),
            "mapping_source": chosen.get("source", "local_only"),
            "confidence": round(float(chosen.get("confidence", 0.0)), 2) if chosen else 0.0,
            "has_flag": (d / "flag.txt").exists(),
            "has_writeup": (d / "writeup.md").exists(),
            "has_solve": (d / "solve.py").exists(),
            "last_updated": int(d.stat().st_mtime),
        }
        if not rec["competition"] and not rec["challenge_id"] and not rec["challenge_name"]:
            issues["missing_mapping"].append(rec["project_name"])
        if len(candidates) >= 2:
            top = candidates[0]
            second = candidates[1]
            if top.get("competition") != second.get("competition") and abs(float(top.get("confidence", 0)) - float(second.get("confidence", 0))) < 0.05:
                issues["conflicts"].append(
                    {
                        "project_name": rec["project_name"],
                        "top": {
                            "competition": top.get("competition"),
                            "id": top.get("id"),
                            "name": top.get("name"),
                        },
                        "second": {
                            "competition": second.get("competition"),
                            "id": second.get("id"),
                            "name": second.get("name"),
                        },
                    }
                )
        rows.append(rec)
    summary = {
        "projects_total": len(rows),
        "mapped": sum(1 for r in rows if r["competition"] or r["challenge_id"] or r["challenge_name"]),
        "missing_mapping": len(issues["missing_mapping"]),
        "conflicts": len(issues["conflicts"]),
    }
    return rows, {"summary": summary, "issues": issues}


def write_outputs(rows: list[dict], meta: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / "projects_index.jsonl"
    cpath = out_dir / "projects_index.csv"
    ipath = out_dir / "index_issues.json"

    with jpath.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    fields = [
        "project_name",
        "project_key",
        "competition",
        "challenge_id",
        "challenge_name",
        "category",
        "confidence",
        "has_flag",
        "has_writeup",
        "has_solve",
        "mapping_source",
        "source_path",
        "project_dir",
    ]
    with cpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    ipath.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Build project index mapping workspace dirs to competition/challenge metadata.")
    p.add_argument("--ctf-work", default="./workspace/active")
    p.add_argument("--search-root", default=".")
    p.add_argument("--out-dir", default="./shared/ctf-index")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    ctf_work = resolve_work_root(args.ctf_work)
    search_root = Path(args.search_root).resolve()
    rows, meta = build_index(ctf_work, search_root)

    if args.apply:
        write_outputs(rows, meta, Path(args.out_dir).resolve())

    if args.json:
        payload = dict(meta["summary"])
        payload["applied"] = bool(args.apply)
        payload["out_dir"] = str(Path(args.out_dir).resolve())
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("== CTF Index Build ==")
        for k, v in meta["summary"].items():
            print(f"- {k}: {v}")
        print(f"- mode: {'apply' if args.apply else 'dry-run'}")
        if args.apply:
            print(f"- out_dir: {Path(args.out_dir).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
