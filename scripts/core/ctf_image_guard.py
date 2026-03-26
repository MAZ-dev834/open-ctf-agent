#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run_cmd(cmd: list[str], log_path: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        output = (proc.stdout or "") + (proc.stderr or "")
        log_path.write_text(output, encoding="utf-8", errors="ignore")
        return proc.returncode, output
    except Exception as exc:  # pragma: no cover
        log_path.write_text(f"[error] {exc}\n", encoding="utf-8", errors="ignore")
        return 1, str(exc)


def file_type(path: Path) -> str:
    if not which("file"):
        return ""
    try:
        proc = subprocess.run(["file", "-b", str(path)], check=False, capture_output=True, text=True)
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def validate_image(path: Path) -> tuple[bool, str]:
    try:
        from PIL import Image  # type: ignore

        try:
            img = Image.open(path)
            img.verify()
            return True, "pil"
        except Exception as exc:
            return False, f"pil:{exc.__class__.__name__}"
    except Exception:
        pass

    try:
        import imghdr

        kind = imghdr.what(path)
        if kind:
            return True, f"imghdr:{kind}"
        return False, "imghdr:none"
    except Exception as exc:  # pragma: no cover
        return False, f"imghdr:{exc.__class__.__name__}"


def try_truncate_jpeg(path: Path, out_path: Path) -> bool:
    try:
        data = path.read_bytes()
    except Exception:
        return False
    idx = data.rfind(b"\xff\xd9")
    if idx <= 0:
        return False
    truncated = data[: idx + 2]
    try:
        out_path.write_bytes(truncated)
    except Exception:
        return False
    ok, _ = validate_image(out_path)
    return ok


def try_ffmpeg(path: Path, out_path: Path, log_dir: Path) -> bool:
    if not which("ffmpeg"):
        return False
    rc, _ = run_cmd(
        ["ffmpeg", "-y", "-loglevel", "error", "-err_detect", "ignore_err", "-i", str(path), str(out_path)],
        log_dir / "ffmpeg.log",
    )
    if rc != 0 or not out_path.exists():
        return False
    ok, _ = validate_image(out_path)
    return ok


def try_magick(path: Path, out_path: Path, log_dir: Path) -> bool:
    cmd = "magick" if which("magick") else ("convert" if which("convert") else "")
    if not cmd:
        return False
    rc, _ = run_cmd([cmd, str(path), "-strip", str(out_path)], log_dir / f"{cmd}.log")
    if rc != 0 or not out_path.exists():
        return False
    ok, _ = validate_image(out_path)
    return ok


def write_strings(path: Path, out_path: Path) -> bool:
    if not which("strings"):
        return False
    try:
        proc = subprocess.run(["strings", "-n", "8", str(path)], check=False, capture_output=True, text=True)
        lines = (proc.stdout or "").splitlines()[:200]
        out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", errors="ignore")
        return True
    except Exception:
        return False


def try_binwalk(path: Path, log_dir: Path) -> bool:
    if not which("binwalk"):
        return False
    rc, _ = run_cmd(["binwalk", "-e", "-q", str(path)], log_dir / "binwalk.log")
    return rc == 0


def main() -> int:
    p = argparse.ArgumentParser(description="Guard and salvage potentially invalid images before vision/OCR.")
    p.add_argument("--input", required=True, help="Input file path")
    p.add_argument("--out-dir", default="", help="Output directory for guard artifacts")
    p.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = p.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        print(f"[error] input not found: {in_path}")
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (in_path.parent / "artifacts" / "image_guard")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "input": str(in_path),
        "status": "unknown",
        "file_type": file_type(in_path),
        "validated_by": "",
        "repaired_by": "",
        "repaired_path": "",
        "artifacts": [],
        "notes": [],
    }

    ok, how = validate_image(in_path)
    summary["validated_by"] = how
    if ok:
        summary["status"] = "valid"
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        return 0

    stem = in_path.stem
    suffix = in_path.suffix.lower()

    if suffix in {".jpg", ".jpeg"}:
        trunc_path = out_dir / f"{stem}_trunc.jpg"
        if try_truncate_jpeg(in_path, trunc_path):
            summary["status"] = "repaired"
            summary["repaired_by"] = "truncate_eoi"
            summary["repaired_path"] = str(trunc_path)
            summary["artifacts"].append(str(trunc_path))
            if args.json:
                print(json.dumps(summary, ensure_ascii=False))
            return 0

    ffmpeg_path = out_dir / f"{stem}_ffmpeg.png"
    if try_ffmpeg(in_path, ffmpeg_path, out_dir):
        summary["status"] = "repaired"
        summary["repaired_by"] = "ffmpeg"
        summary["repaired_path"] = str(ffmpeg_path)
        summary["artifacts"].append(str(ffmpeg_path))
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        return 0

    magick_path = out_dir / f"{stem}_magick.png"
    if try_magick(in_path, magick_path, out_dir):
        summary["status"] = "repaired"
        summary["repaired_by"] = "magick"
        summary["repaired_path"] = str(magick_path)
        summary["artifacts"].append(str(magick_path))
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        return 0

    summary["status"] = "invalid_image"
    strings_path = out_dir / f"{stem}_strings.txt"
    if write_strings(in_path, strings_path):
        summary["artifacts"].append(str(strings_path))
        summary["notes"].append("strings_extracted")

    if try_binwalk(in_path, out_dir):
        summary["notes"].append("binwalk_extracted")

    summary["notes"].append("treat_as_binary_carrier")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("[warn] invalid image; consider binwalk/strings/exiftool")
        print(json.dumps(summary, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
