#!/usr/bin/env python3
"""Minimal OCR pipeline wrapper.

Runs OCR on an input image and writes:
- ocr_report.json (candidates + metadata)
- ocr_best.txt (best candidate text)

Uses tesseract CLI if available. Optional rotation variants are generated
with ImageMagick `convert` when present.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.core.runtime_config import default_vlm_api_key, default_vlm_base_url, default_vlm_model
except Exception:  # pragma: no cover
    default_vlm_api_key = None
    default_vlm_base_url = None
    default_vlm_model = None

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageFilter = None
    ImageOps = None


def _split_engines(value: str) -> list[str]:
    parts = re.split(r"[ ,]+", (value or "").strip())
    return [p for p in parts if p]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _requests_available():
    try:
        import requests  # type: ignore

        return requests
    except Exception:
        return None


def _convert_available() -> bool:
    return shutil.which("convert") is not None


def _pil_available() -> bool:
    return Image is not None and ImageOps is not None


def _split_psm_list(psm: int | None, psm_list: str) -> list[int | None]:
    if psm is not None:
        return [psm]
    vals: list[int | None] = []
    for part in re.split(r"[ ,]+", (psm_list or "").strip()):
        if not part:
            continue
        try:
            vals.append(int(part))
        except Exception:
            continue
    return vals or [6]


def _run_tesseract(
    image: Path,
    lang: str,
    psm: int | None,
    timeout_sec: int,
    char_whitelist: str,
) -> str:
    cmd = ["tesseract", str(image), "stdout", "-l", lang]
    if psm is not None:
        cmd += ["--psm", str(psm)]
    if char_whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={char_whitelist}"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=timeout_sec)
        return out.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def _vlm_config() -> dict:
    base_url = (
        default_vlm_base_url() if default_vlm_base_url is not None else (
            os.environ.get("CTF_VLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE")
            or "http://127.0.0.1:1234/v1"
        )
    ).strip()
    model = (
        default_vlm_model() if default_vlm_model is not None else (
            os.environ.get("CTF_VLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("MODEL")
            or "qwen3.5-2b"
        )
    ).strip()
    api_key = (
        default_vlm_api_key() if default_vlm_api_key is not None else (
            os.environ.get("CTF_VLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("API_KEY")
            or "EMPTY"
        )
    ).strip()
    prompt = (
        os.environ.get("CTF_VLM_PROMPT")
        or "Read all visible text from this image. Focus on CTF flag-like strings such as xxx{...}, "
        "CTF{...}, or partial fragments like _xxx_xxx}. Return only the extracted text, preserving braces, "
        "underscores, punctuation, and line breaks when useful. Do not describe the image."
    )
    return {
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "prompt": prompt,
    }


def _vlm_available() -> bool:
    cfg = _vlm_config()
    return bool(cfg["base_url"] and cfg["model"] and _requests_available() is not None)


def _run_vlm(image: Path, timeout_sec: int, prompt: str) -> str:
    requests = _requests_available()
    if requests is None:
        return ""
    cfg = _vlm_config()
    if not cfg["base_url"] or not cfg["model"]:
        return ""
    try:
        mime = "image/png"
        suf = image.suffix.lower()
        if suf in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suf == ".webp":
            mime = "image/webp"
        elif suf == ".gif":
            mime = "image/gif"
        elif suf in {".tif", ".tiff"}:
            mime = "image/tiff"
        data = base64.b64encode(image.read_bytes()).decode("ascii")
        payload = {
            "model": cfg["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or cfg["prompt"]},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                    ],
                }
            ],
            "temperature": 0,
        }
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        obj = resp.json()
        choices = obj.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(str(item.get("text")))
            return "\n".join(parts).strip()
        return ""
    except Exception:
        return ""


def _otsu_threshold(gray) -> int:
    hist = gray.histogram()
    total = sum(hist)
    sum_total = sum(i * h for i, h in enumerate(hist))
    sum_b = 0.0
    w_b = 0
    var_max = -1.0
    threshold = 127
    for i, h in enumerate(hist):
        w_b += h
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * h
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > var_max:
            var_max = var_between
            threshold = i
    return threshold


def _pil_variants(input_path: Path, out_dir: Path, max_variants: int) -> list[dict]:
    if not _pil_available():
        return [{"name": "orig", "path": input_path}]
    try:
        base = Image.open(input_path).convert("L")
    except Exception:
        return [{"name": "orig", "path": input_path}]

    def save_variant(name: str, img) -> dict | None:
        out_path = out_dir / f"ocr_{name}.png"
        try:
            img.save(out_path)
            return {"name": name, "path": out_path}
        except Exception:
            return None

    variants: list[dict] = [{"name": "orig", "path": input_path}]
    work = ImageOps.autocontrast(base)
    big = work.resize((work.width * 2, work.height * 2))
    if ImageFilter is not None:
        sharp = big.filter(ImageFilter.MedianFilter(size=3)).filter(ImageFilter.SHARPEN)
    else:
        sharp = big
    threshold = _otsu_threshold(sharp)
    thr = sharp.point(lambda p: 255 if p > threshold else 0)
    thr_inv = ImageOps.invert(thr)

    crops = []
    w, h = sharp.size
    crops.append(("center_band", sharp.crop((0, int(h * 0.28), w, int(h * 0.72)))))
    crops.append(("mid_box", sharp.crop((int(w * 0.12), int(h * 0.22), int(w * 0.88), int(h * 0.78)))))
    crops.append(("thr_center_band", thr.crop((0, int(h * 0.28), w, int(h * 0.72)))))
    crops.append(("thr_inv_center_band", thr_inv.crop((0, int(h * 0.28), w, int(h * 0.72)))))

    candidates = [
        ("gray_autocontrast", work),
        ("gray_big", big),
        ("gray_sharp", sharp),
        ("thr", thr),
        ("thr_inv", thr_inv),
        *crops,
    ]
    for name, img in candidates:
        if len(variants) >= max_variants:
            break
        item = save_variant(name, img)
        if item is not None:
            variants.append(item)
    return variants


def _make_variants(input_path: Path, out_dir: Path, max_variants: int) -> list[dict]:
    variants = [{"name": "orig", "path": input_path}]
    if max_variants <= 1:
        return variants
    pil_variants = _pil_variants(input_path, out_dir, max_variants)
    if len(pil_variants) > 1:
        return pil_variants[:max_variants]
    if not _convert_available():
        return variants

    specs = [
        ("rot90", ["-rotate", "90"]),
        ("rot180", ["-rotate", "180"]),
        ("rot270", ["-rotate", "270"]),
        ("gray", ["-colorspace", "Gray"]),
        ("autocontrast", ["-autocontrast"]),
        ("threshold", ["-threshold", "50%"]),
    ]
    for name, args in specs:
        if len(variants) >= max_variants:
            break
        out_path = out_dir / f"ocr_{name}.png"
        try:
            subprocess.check_call(
                ["convert", str(input_path), *args, str(out_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            variants.append({"name": name, "path": out_path})
        except Exception:
            continue
    return variants


def _score_text(text: str, goal: str, flag_re: re.Pattern | None) -> tuple[int, int]:
    if not text:
        return (0, 0)
    compact = _normalize_text(text)
    matches = 0
    if flag_re is not None:
        matches = max(len(flag_re.findall(text)), len(flag_re.findall(compact)))
    structure_bonus = 0
    if "{" in compact and "}" in compact:
        structure_bonus += 20
    if "_" in compact:
        structure_bonus += 10
    if re.search(r"[A-Za-z]{3,}\{", compact):
        structure_bonus += 40
    if goal == "flag" and flag_re is not None:
        return (matches * 1000 + structure_bonus + len(compact), matches)
    return (structure_bonus + len(compact), matches)


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" {", "{").replace("{ ", "{").replace(" }", "}").replace(" _", "_").replace("_ ", "_")
    text = text.replace("|", "I")
    compact = re.sub(r"\s+", "", text)
    compact = compact.replace("CT F{", "CTF{").replace("C T F{", "CTF{")
    return compact or text.strip()


def _collect_candidates(
    variants: list[dict],
    lang: str,
    psms: list[int | None],
    timeout_sec: int,
    goal: str,
    flag_re,
    char_whitelist: str,
):
    candidates: list[dict] = []
    for v in variants:
        for psm in psms:
            text = _run_tesseract(v["path"], lang, psm, timeout_sec, char_whitelist)
            normalized = _normalize_text(text)
            score, matches = _score_text(normalized, goal, flag_re)
            candidates.append(
                {
                    "engine": "tesseract",
                    "variant": v["name"],
                    "psm": psm,
                    "path": str(v["path"]),
                    "text": text,
                    "normalized_text": normalized,
                    "score": score,
                    "matches": matches,
                }
            )
    return candidates


def _collect_vlm_candidates(variants: list[dict], timeout_sec: int, goal: str, flag_re, prompt: str):
    candidates: list[dict] = []
    for v in variants:
        text = _run_vlm(v["path"], timeout_sec, prompt)
        normalized = _normalize_text(text)
        score, matches = _score_text(normalized, goal, flag_re)
        candidates.append(
            {
                "engine": "vlm",
                "variant": v["name"],
                "path": str(v["path"]),
                "text": text,
                "normalized_text": normalized,
                "score": score,
                "matches": matches,
            }
        )
    return candidates


def main() -> int:
    p = argparse.ArgumentParser(description="OCR pipeline (tesseract-based)")
    p.add_argument("--input", required=True, help="input image path")
    p.add_argument("--out-dir", default=None, help="output directory for OCR artifacts")
    p.add_argument("--json-out", default=None, help="explicit json report path")
    p.add_argument("--goal", default="text", help="text or flag")
    p.add_argument("--flag-regex", default=None, help="regex to score flag candidates")
    p.add_argument("--max-variants", type=int, default=1)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--engines", default="vlm,tesseract")
    p.add_argument("--psm", type=int, default=None)
    p.add_argument("--psm-list", default="6,7,11,13")
    p.add_argument("--tesseract-lang", default="eng")
    p.add_argument("--char-whitelist", default="")
    p.add_argument("--vlm-prompt", default="")
    p.add_argument("--timeout-sec", type=int, default=120)
    p.add_argument("--save-variants", action="store_true", help="save generated variants under out-dir/variants")
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"file not found: {input_path}", file=sys.stderr)
        return 2

    engines = _split_engines(args.engines)
    if not engines:
        print("no OCR engines selected", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else input_path.parent / "artifacts" / "ocr"
    _ensure_dir(out_dir)
    json_out = Path(args.json_out) if args.json_out else out_dir / "ocr_report.json"
    best_out = out_dir / "ocr_best.txt"
    best_norm_out = out_dir / "ocr_best_normalized.txt"

    flag_re = re.compile(args.flag_regex) if args.flag_regex else None
    psms = _split_psm_list(args.psm, args.psm_list)

    if args.save_variants:
        variants_dir = out_dir / "variants"
        _ensure_dir(variants_dir)
        variants = _make_variants(input_path, variants_dir, max(1, args.max_variants))
    else:
        with tempfile.TemporaryDirectory(prefix="ocr_pipeline_") as tmp:
            tmp_dir = Path(tmp)
            variants = _make_variants(input_path, tmp_dir, max(1, args.max_variants))
    candidates: list[dict] = []
    engine_status: dict[str, str] = {}
    for engine in engines:
        if engine == "vlm":
            if not _vlm_available():
                engine_status["vlm"] = "skipped:not_configured"
                continue
            engine_status["vlm"] = "ok"
            candidates.extend(_collect_vlm_candidates(variants, args.timeout_sec, args.goal, flag_re, args.vlm_prompt))
            continue
        if engine == "tesseract":
            if not _tesseract_available():
                engine_status["tesseract"] = "skipped:not_installed"
                continue
            engine_status["tesseract"] = "ok"
            candidates.extend(
                _collect_candidates(
                    variants, args.tesseract_lang, psms, args.timeout_sec, args.goal, flag_re, args.char_whitelist
                )
            )
            continue
        engine_status[engine] = "skipped:unsupported"

    if not candidates:
        print(f"no OCR candidates produced; engine_status={json.dumps(engine_status, ensure_ascii=False)}", file=sys.stderr)
        return 2

    candidates.sort(key=lambda x: (x["score"], x["matches"]))
    candidates.reverse()
    top_candidates = candidates[: max(1, args.top)]

    best_text = top_candidates[0]["text"] if top_candidates else ""
    best_normalized = top_candidates[0].get("normalized_text", "") if top_candidates else ""
    best_out.write_text(best_text + ("\n" if best_text and not best_text.endswith("\n") else ""), encoding="utf-8")
    best_norm_out.write_text(
        best_normalized + ("\n" if best_normalized and not best_normalized.endswith("\n") else ""), encoding="utf-8"
    )

    report = {
        "input": str(input_path),
        "out_dir": str(out_dir),
        "goal": args.goal,
        "flag_regex": args.flag_regex,
        "variants": len(candidates),
        "engines": engines,
        "engine_status": engine_status,
        "psms": psms,
        "top": top_candidates,
        "save_variants": args.save_variants,
    }
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ocr_variants={len(candidates)}")
    print(f"ocr_best_len={len(best_text)}")
    print(f"ocr_best_path={best_out}")
    print(f"ocr_best_normalized_path={best_norm_out}")
    print(f"ocr_report_path={json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
