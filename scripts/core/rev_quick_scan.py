#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


def iter_candidate_files(root: Path) -> list[Path]:
    skip_dirs = {"__pycache__", ".git", "artifacts", "logs"}
    out: list[Path] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            p = Path(base) / name
            if p.is_file():
                out.append(p)
    return out


def score_binary(path: Path) -> tuple[int, int]:
    name = path.name.lower()
    score = 0
    if os.access(path, os.X_OK):
        score += 2
    if not any(name.endswith(ext) for ext in (".so", ".dll", ".dylib")):
        score += 1
    if name.startswith("lib") or "ld-" in name or name.startswith("ld"):
        score -= 1
    try:
        size = path.stat().st_size
    except Exception:
        size = 0
    return (score, size)


def pick_binary(project: Path) -> Path | None:
    roots = [
        project,
        project / "attachments",
        project / "attachments" / "extracted",
        project / "题目附件",
        project / "题目附件" / "extracted",
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in iter_candidate_files(root):
            if is_elf(p):
                candidates.append(p)
    if not candidates:
        return None
    return sorted(candidates, key=score_binary, reverse=True)[0]


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(cmd: list[str], timeout: int = 20) -> dict:
    exe = cmd[0]
    if shutil.which(exe) is None:
        return {"cmd": cmd, "rc": 127, "out": "", "err": f"{exe} not found"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {"cmd": cmd, "rc": proc.returncode, "out": proc.stdout, "err": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "rc": 124, "out": "", "err": f"timeout>{timeout}s"}


def strings_sample(path: Path, min_len: int = 6, limit: int = 200) -> dict:
    res = run_cmd(["strings", "-n", str(min_len), str(path)], timeout=25)
    lines = res["out"].splitlines() if res["out"] else []
    return {
        "cmd": res.get("cmd"),
        "rc": res.get("rc"),
        "err": res.get("err"),
        "total_lines": len(lines),
        "sample": lines[:limit],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Quick rev scan: file/readelf/objdump/strings.")
    p.add_argument("--binary", default="", help="Target binary path")
    p.add_argument("--project", default="", help="Project directory (auto-pick ELF)")
    p.add_argument("--out-dir", default="", help="Output directory (default: <project>/artifacts)")
    args = p.parse_args()

    binary = Path(args.binary).expanduser() if args.binary else None
    project = Path(args.project).expanduser().resolve() if args.project else None

    if binary is None:
        if not project:
            raise SystemExit("provide --binary or --project")
        binary = pick_binary(project)
        if binary is None:
            raise SystemExit("no ELF binary found under project")

    if not binary.exists():
        raise SystemExit(f"binary not found: {binary}")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else None
    if out_dir is None:
        if not project:
            raise SystemExit("provide --out-dir when --project is not set")
        out_dir = project / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "binary": str(binary.resolve()),
        "size_bytes": binary.stat().st_size,
        "sha256": sha256sum(binary),
        "file": run_cmd(["file", "-b", str(binary)]),
        "readelf": run_cmd(["readelf", "-h", str(binary)]),
        "objdump": run_cmd(["objdump", "-x", str(binary)]),
        "strings": strings_sample(binary, min_len=6, limit=200),
    }

    json_path = out_dir / "rev_quick_scan.json"
    txt_path = out_dir / "rev_quick_scan.txt"

    json_path.write_text(__import__("json").dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        f"binary: {payload['binary']}",
        f"size_bytes: {payload['size_bytes']}",
        f"sha256: {payload['sha256']}",
        "",
        "== file ==",
        payload["file"]["out"].strip(),
        payload["file"]["err"].strip(),
        "",
        "== readelf -h ==",
        payload["readelf"]["out"].strip(),
        payload["readelf"]["err"].strip(),
        "",
        "== objdump -x ==",
        payload["objdump"]["out"].strip(),
        payload["objdump"]["err"].strip(),
        "",
        f"== strings sample (n={len(payload['strings']['sample'])}) ==",
        "\n".join(payload["strings"]["sample"]),
    ]
    txt_path.write_text("\n".join([ln for ln in lines if ln is not None]) + "\n", encoding="utf-8")

    print(f"[+] rev_quick_scan: {json_path}")
    print(f"[+] rev_quick_scan_txt: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
