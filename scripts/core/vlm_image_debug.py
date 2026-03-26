#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import tempfile
import sys
from pathlib import Path

try:
    from scripts.core.runtime_config import default_vlm_api_key, default_vlm_base_url, default_vlm_model
except Exception:  # pragma: no cover
    default_vlm_api_key = None
    default_vlm_base_url = None
    default_vlm_model = None

try:
    import requests  # type: ignore
except Exception:
    requests = None

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:
    Image = None
    ImageFilter = None
    ImageOps = None


def infer_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def build_payload(model: str, prompt: str, image_path: Path, temperature: float, max_tokens: int) -> dict:
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime = infer_mime(image_path)
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def extract_text(resp_obj: dict) -> str:
    choices = resp_obj.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                out.append(str(item.get("text") or ""))
        return "\n".join(x for x in out if x)
    return ""


def pil_available() -> bool:
    return Image is not None and ImageOps is not None


def otsu_threshold(gray) -> int:
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


def make_variants(image_path: Path, out_dir: Path) -> list[tuple[str, Path]]:
    variants = [("orig", image_path)]
    if not pil_available():
        return variants
    try:
        base = Image.open(image_path).convert("L")
    except Exception:
        return variants

    def save(name: str, img) -> None:
        path = out_dir / f"{name}.png"
        img.save(path)
        variants.append((name, path))

    work = ImageOps.autocontrast(base)
    big = work.resize((work.width * 2, work.height * 2))
    sharp = big.filter(ImageFilter.MedianFilter(size=3)).filter(ImageFilter.SHARPEN) if ImageFilter else big
    thr = sharp.point(lambda p: 255 if p > otsu_threshold(sharp) else 0)
    inv = ImageOps.invert(thr)
    w, h = sharp.size
    center_band = sharp.crop((0, int(h * 0.28), w, int(h * 0.72)))
    otsu_center = thr.crop((0, int(h * 0.28), w, int(h * 0.72)))
    inv_center = inv.crop((0, int(h * 0.28), w, int(h * 0.72)))
    mid_box = sharp.crop((int(w * 0.12), int(h * 0.22), int(w * 0.88), int(h * 0.78)))

    for name, img in [
        ("gray_big", big),
        ("gray_sharp", sharp),
        ("otsu", thr),
        ("otsu_inv", inv),
        ("center_band", center_band),
        ("otsu_center", otsu_center),
        ("otsu_inv_center", inv_center),
        ("mid_box", mid_box),
    ]:
        save(name, img)
    return variants


def main() -> int:
    ap = argparse.ArgumentParser(description="Debug a local OpenAI-compatible VLM on one image.")
    ap.add_argument("--input", required=True, help="image path")
    ap.add_argument(
        "--base-url",
        default=default_vlm_base_url() if default_vlm_base_url is not None else os.environ.get("CTF_VLM_BASE_URL", "http://127.0.0.1:1234/v1"),
    )
    ap.add_argument(
        "--model",
        default=default_vlm_model() if default_vlm_model is not None else os.environ.get("CTF_VLM_MODEL", "qwen3.5-2b"),
    )
    ap.add_argument(
        "--api-key",
        default=default_vlm_api_key() if default_vlm_api_key is not None else os.environ.get("CTF_VLM_API_KEY", "EMPTY"),
    )
    ap.add_argument(
        "--prompt",
        default=(
            "Read all visible text from this image. Focus on the most likely CTF flag. "
            "Preserve braces, underscores, and punctuation. Return only the extracted text."
        ),
    )
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--timeout-sec", type=int, default=60)
    ap.add_argument("--raw", action="store_true", help="print full JSON response")
    ap.add_argument("--payload-only", action="store_true", help="print request payload and exit")
    ap.add_argument("--all-variants", action="store_true", help="auto-generate image variants and query all of them")
    args = ap.parse_args()

    if requests is None:
        print("requests is not installed", file=sys.stderr)
        return 2

    image_path = Path(args.input).expanduser().resolve()
    if not image_path.exists():
        print(f"file not found: {image_path}", file=sys.stderr)
        return 2

    base = str(args.base_url or "").rstrip("/")
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
    }
    with tempfile.TemporaryDirectory(prefix="vlm_image_debug_") as tmp:
        tmp_dir = Path(tmp)
        variant_list = make_variants(image_path, tmp_dir) if args.all_variants else [("orig", image_path)]
        rc = 0
        for name, current_path in variant_list:
            payload = build_payload(args.model, args.prompt, current_path, args.temperature, args.max_tokens)
            if args.payload_only:
                print(f"## variant={name} path={current_path}")
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                continue
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=args.timeout_sec)
            except Exception as exc:
                print(f"variant={name} request failed: {exc}", file=sys.stderr)
                rc = 1
                continue

            print(f"## variant={name} path={current_path}")
            print(f"status={resp.status_code}")
            try:
                obj = resp.json()
            except Exception:
                print(resp.text)
                if not resp.ok:
                    rc = 1
                continue

            if args.raw:
                print(json.dumps(obj, ensure_ascii=False, indent=2))
            else:
                text = extract_text(obj)
                if text:
                    print(text)
                else:
                    print(json.dumps(obj, ensure_ascii=False, indent=2))
            print()
            if not resp.ok:
                rc = 1
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
