#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
import subprocess
import shutil

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "artifacts",
    "logs",
    "runtime",
}
FLAG_PATTERNS = [
    re.compile(r"[A-Za-z0-9_]{0,24}\{[^{}\n]{1,256}\}"),
    re.compile(r"[A-Za-z0-9_]{1,48}\{[A-Za-z0-9_]{2,256}"),
    re.compile(r"_[A-Za-z0-9_]{2,256}\}"),
]


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"files": {}, "updated_at": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {"files": {}, "updated_at": ""}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if parts & SKIP_DIRS:
        return True
    if "image_guard" in parts:
        return True
    return False


def iter_images(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() in IMAGE_EXTS:
                found.append(root)
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if should_skip(p):
                continue
            if p.suffix.lower() in IMAGE_EXTS:
                found.append(p)
    return found


def run_guard(guard_path: Path, target: Path) -> dict:
    try:
        proc = subprocess.run(
            ["python3", str(guard_path), "--input", str(target), "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:  # pragma: no cover
        return {"input": str(target), "status": "error", "error": str(exc)}
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return {"input": str(target), "status": "error", "error": (proc.stderr or "").strip()}
    out = (proc.stdout or "").strip()
    if not out:
        return {"input": str(target), "status": "unknown"}
    try:
        return json.loads(out)
    except Exception:
        # last line fallback
        try:
            return json.loads(out.splitlines()[-1])
        except Exception:
            return {"input": str(target), "status": "unknown"}


def extract_flag_candidates(*texts: str) -> list[str]:
    out: list[str] = []
    seen = set()
    for text in texts:
        if not text:
            continue
        norm = re.sub(r"\s+", "", str(text))
        for pat in FLAG_PATTERNS:
            for m in pat.finditer(norm):
                cand = m.group(0)
                if not cand or cand in seen:
                    continue
                seen.add(cand)
                out.append(cand)
    return out


def run_ocr(ocr_path: Path, out_base: Path, target: Path) -> dict:
    key = hashlib.sha1(str(target).encode("utf-8", errors="ignore")).hexdigest()[:12]
    out_dir = out_base / "ocr" / key
    out_dir.mkdir(parents=True, exist_ok=True)
    def invoke(pass_name: str, max_variants: int, engines: str, timeout_sec: int, model: str = "") -> dict:
        pass_dir = out_dir / pass_name
        pass_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy() if "os" in globals() else None
        if env is not None and model:
            env["CTF_VLM_MODEL"] = model
        try:
            proc = subprocess.run(
                [
                    "python3",
                    str(ocr_path),
                    "--input",
                    str(target),
                    "--out-dir",
                    str(pass_dir),
                    "--goal",
                    "flag",
                    "--engines",
                    engines,
                    "--max-variants",
                    str(max_variants),
                    "--top",
                    "3",
                    "--save-variants",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error": str(exc), "input": str(target)}
        if proc.returncode != 0:
            return {"status": "error", "stderr": (proc.stderr or "").strip(), "input": str(target)}
        report_path = pass_dir / "ocr_report.json"
        if not report_path.exists():
            return {"status": "missing_report", "input": str(target)}
        try:
            report = json.loads(report_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {"status": "bad_report", "input": str(target)}
        top = report.get("top") or []
        candidates: list[str] = []
        for item in top[:3]:
            candidates.extend(extract_flag_candidates(item.get("normalized_text", ""), item.get("text", "")))
        deduped = []
        seen = set()
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            deduped.append(cand)
        return {
            "status": "ok",
            "input": str(target),
            "out_dir": str(pass_dir),
            "engine_status": report.get("engine_status") or {},
            "top": top[:3],
            "candidates": deduped[:5],
            "pass": pass_name,
        }

    first = invoke("orig_qwen2b", 1, "vlm,tesseract", 60, model="qwen3.5-2b")
    if (first.get("candidates") or []) or first.get("status") != "ok":
        return first
    second = invoke("orig_qwen08b", 1, "vlm,tesseract", 45, model="qwen3.5-0.8b")
    if (second.get("candidates") or []) or second.get("status") != "ok":
        second["previous_pass"] = first
        return second
    third = invoke("enhanced_fallback", 4, "vlm,tesseract", 90, model="qwen3.5-2b")
    third["previous_pass"] = second
    third.setdefault("history", []).append(first)
    return third


def update_closure_outputs(summary_dir: Path, payload: dict) -> None:
    summary_dir.mkdir(parents=True, exist_ok=True)
    signal_path = summary_dir / "closure_signal.json"
    flags_path = summary_dir / "flag_candidates.txt"
    current = {"updated_at": "", "hits": []}
    if signal_path.exists():
        try:
            current = json.loads(signal_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            current = {"updated_at": "", "hits": []}
    hits = [x for x in (current.get("hits") or []) if isinstance(x, dict)]
    hits = [x for x in hits if x.get("input") != payload.get("input")]
    hits.append(payload)
    current = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hits": hits[-20:],
    }
    signal_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines: list[str] = []
    for item in current["hits"]:
        inp = item.get("input") or ""
        try:
            inp = Path(inp).name
        except Exception:
            pass
        cands = item.get("candidates") or []
        if cands:
            for cand in cands:
                lines.append(f"{inp}: {cand}")
    flags_path.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")


def scan_once(
    roots: list[Path],
    guard_path: Path,
    ocr_path: Path,
    state: dict,
    results_path: Path,
    max_per_scan: int,
) -> int:
    files = state.setdefault("files", {})
    candidates = []
    for p in iter_images(roots):
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        prev = float(files.get(str(p), 0))
        if mtime > prev:
            candidates.append((mtime, p))
    candidates.sort(key=lambda x: x[0], reverse=True)

    handled = 0
    for _, p in candidates[:max_per_scan]:
        payload = run_guard(guard_path, p)
        ocr = {}
        if str(payload.get("status") or "") in {"valid", "repaired"}:
            ocr = run_ocr(ocr_path, results_path.parent, p)
            if (ocr.get("candidates") or []):
                update_closure_outputs(results_path.parent, ocr)
        if ocr:
            payload["ocr"] = ocr
        files[str(p)] = p.stat().st_mtime if p.exists() else time.time()
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text("", encoding="utf-8", errors="ignore") if not results_path.exists() else None
        with results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handled += 1
    return handled


def main() -> int:
    ap = argparse.ArgumentParser(description="Background image guard watcher for CTF workspace.")
    ap.add_argument("--root", action="append", required=True, help="Root path to scan (repeatable)")
    ap.add_argument("--interval-sec", type=int, default=8, help="Scan interval seconds")
    ap.add_argument("--max-per-scan", type=int, default=30, help="Max new/updated images per scan")
    ap.add_argument("--state", default="", help="State JSON path (default: <first_root>/artifacts/image_guard/image_watch_state.json)")
    ap.add_argument("--once", action="store_true", help="Run a single scan and exit")
    ap.add_argument("--duration-sec", type=int, default=0, help="Optional max runtime seconds (0=run forever)")
    args = ap.parse_args()

    roots = [Path(r).expanduser().resolve() for r in (args.root or [])]
    if not roots:
        print("[watch] no roots provided")
        return 2
    guard_path = Path(__file__).resolve().parent / "ctf_image_guard.py"
    ocr_path = Path(__file__).resolve().parent / "ocr_pipeline.py"
    if not guard_path.exists():
        print(f"[watch] guard not found: {guard_path}")
        return 2
    if not ocr_path.exists():
        print(f"[watch] ocr not found: {ocr_path}")
        return 2

    state_path = Path(args.state).expanduser().resolve() if args.state else (roots[0] / "artifacts" / "image_guard" / "image_watch_state.json")
    results_path = state_path.parent / "image_watch_results.jsonl"
    state = load_state(state_path)

    start = time.time()
    while True:
        handled = scan_once(roots, guard_path, ocr_path, state, results_path, args.max_per_scan)
        save_state(state_path, state)
        if args.once:
            break
        if args.duration_sec and (time.time() - start) > args.duration_sec:
            break
        if handled == 0:
            time.sleep(max(1, int(args.interval_sec)))
        else:
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
