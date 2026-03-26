#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import os
import re
import subprocess
import sys
import textwrap
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._content_chunks: list[str] = []
        self._skip_depth = 0
        self._content_depth = 0

    def _is_content_container(self, tag: str, attrs: dict[str, str]) -> bool:
        if tag in {"article", "main"}:
            return True
        if tag == "div":
            val_id = attrs.get("id", "").lower()
            if val_id in {"content", "post", "article", "entry-content"}:
                return True
            class_val = attrs.get("class", "").lower()
            if any(k in class_val for k in ("content", "prose", "markdown", "post", "article", "entry")):
                return True
        return False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if data and data.strip():
            cleaned = data.strip()
            self._chunks.append(cleaned)
            if self._content_depth > 0:
                self._content_chunks.append(cleaned)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        attrs_map = {k: (v or "") for k, v in attrs}
        if self._is_content_container(tag, attrs_map):
            self._content_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag in {"article", "main", "div"} and self._content_depth > 0:
            self._content_depth -= 1

    def text(self) -> str:
        if len(self._content_chunks) >= 10:
            return "\n".join(self._content_chunks)
        return "\n".join(self._chunks)


def slugify(value: str) -> str:
    val = value.lower()
    val = re.sub(r"[^a-z0-9]+", "-", val)
    val = re.sub(r"-+", "-", val).strip("-")
    return val or "study"


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def download_url(url: str, dst: Path) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ctf-study/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        content_type = resp.headers.get("Content-Type", "")
    dst.write_bytes(data)
    return data, content_type


def fetch_jina_text(url: str, dst: Path) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        return ""
    clean_url = parsed._replace(fragment="").geturl()
    jina_url = f"https://r.jina.ai/{clean_url}"
    try:
        raw, _ = download_url(jina_url, dst)
    except Exception:
        return ""
    text = raw.decode(errors="ignore")
    if not text:
        return ""
    lowered = text.lower()
    if "error" in lowered and len(text) < 200:
        return ""
    return text


def render_url(url: str, timeout_ms: int = 30000) -> str:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout  # type: ignore
    except Exception:
        return ""

    fragment = urllib.parse.urlparse(url).fragment
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except PlaywrightTimeout:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_selector("article, main, #content", timeout=8000)
        except PlaywrightTimeout:
            pass
        if fragment:
            page.evaluate(
                """(id) => {
                    const el = document.getElementById(id) || document.querySelector(`[name="${id}"]`);
                    if (el) { el.scrollIntoView(); }
                }""",
                fragment,
            )
            page.wait_for_timeout(800)
        content = page.content()
        browser.close()
    lower = content.lower()
    if any(
        marker in lower
        for marker in (
            "security verification",
            "verify you are not a bot",
            "checking your browser",
            "cf-browser-verification",
            "cloudflare",
        )
    ):
        return ""
    return content


def detect_type(source: str, content_type: str | None = None) -> str:
    s = source.lower()
    if s.endswith(".pdf"):
        return "pdf"
    if s.endswith((".md", ".markdown", ".txt")):
        return "text"
    if s.endswith((".html", ".htm")):
        return "html"
    if content_type and "html" in content_type:
        return "html"
    return "text"


def is_heading_candidate(line: str) -> bool:
    if len(line) > 80:
        return False
    if line.count(" ") > 10:
        return False
    return True


def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    if s in {"#", "##", "###", "----", "-----", "------"}:
        return False
    if s[0] in {",", ".", ";", ":"}:
        return False
    if len(s) < 4:
        return False
    if re.fullmatch(r"[=\\-_*]+", s):
        return False
    if re.fullmatch(r"\\d+", s):
        return False
    if "_" in s and s.count(" ") == 0:
        return False
    if "(" in s or ")" in s:
        return False
    if re.fullmatch(r"[A-Z0-9_]{3,}", s):
        return False
    if re.fullmatch(r"(import|from|def|class|return|if|for|while|try|except|lambda)", s, re.I):
        return False
    if s.islower() and s.count(" ") == 0:
        return False
    if not is_heading_candidate(s):
        return False
    if re.search(r"\b\d{4}\b", s) and len(s) <= 20:
        return False
    if re.search(r"[。.!?;:！？,]", s):
        return False
    if s.count(" ") > 6:
        return False
    return True


def find_marker(lines: list[str], markers: list[str]) -> int:
    for idx, line in enumerate(lines):
        low = line.lower()
        if not is_heading_candidate(line):
            continue
        for pat in markers:
            if re.search(pat, low):
                return idx
    return -1


def split_problem_writeup(lines: list[str]) -> tuple[list[str], list[str], str]:
    problem_markers = [
        r"题目",
        r"题目描述",
        r"challenge",
        r"problem",
        r"description",
        r"任务",
        r"要求",
    ]
    writeup_markers = [
        r"题解",
        r"解题",
        r"writeup",
        r"solution",
        r"analysis",
        r"思路",
        r"过程",
    ]

    p_idx = find_marker(lines, problem_markers)
    w_idx = find_marker(lines, writeup_markers)
    note = "no_marker"

    if w_idx != -1 and (p_idx == -1 or w_idx < p_idx):
        problem = lines[:w_idx]
        writeup = lines[w_idx + 1 :]
        note = "writeup_marker_split"
    elif p_idx != -1:
        if w_idx != -1 and w_idx > p_idx:
            problem = lines[p_idx + 1 : w_idx]
            writeup = lines[w_idx + 1 :]
            note = "problem_writeup_markers"
        else:
            problem = lines[p_idx + 1 :]
            writeup = []
            note = "problem_only"
    else:
        problem = []
        writeup = lines

    problem = [ln for ln in problem if ln]
    writeup = [ln for ln in writeup if ln]

    if len(writeup) < 12 and len(lines) > len(writeup):
        writeup = lines
        if problem:
            note = "fallback_combined"
    return problem, writeup, note


def normalize_section_hint(fragment: str) -> str:
    frag = fragment.strip().strip("#")
    frag = frag.replace("-", " ").replace("_", " ")
    return frag.lower()


def extract_fragment_hint(source: str) -> str:
    if not source:
        return ""
    parsed = urllib.parse.urlparse(source)
    return parsed.fragment or ""


def filter_section(lines: list[str], section_hint: str) -> list[str]:
    if not section_hint:
        return lines
    key = normalize_section_hint(section_hint)
    if not key:
        return lines
    starts = [i for i, ln in enumerate(lines) if key in ln.lower()]
    if not starts:
        return lines
    best_slice = None
    best_score = -1
    best_len = 0
    min_span = 12
    for start in starts:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if looks_like_heading(lines[j]) and (j - start) >= min_span:
                end = j
                break
        span = lines[start:end]
        code_hits = 0
        keyword_hits = 0
        for ln in span:
            if re.search(r"\b(import|from|def|class|return|sage|gf\(|cipher)\b", ln, re.I):
                code_hits += 1
            if re.search(r"[{}();]", ln):
                code_hits += 1
            if re.search(r"(rsa|aes|gf\(|feistel|lattice|hash|ecc|crypto)", ln, re.I):
                keyword_hits += 1
        score = code_hits * 2 + keyword_hits
        if score > best_score or (score == best_score and len(span) > best_len):
            best_score = score
            best_len = len(span)
            best_slice = span
    return best_slice or lines


def guess_category(lines: Iterable[str], min_hits: int = 3) -> tuple[str, float]:
    counters = {
        "pwn": 0,
        "rev": 0,
        "web": 0,
        "crypto": 0,
        "misc": 0,
    }
    patterns = {
        "pwn": r"(heap|tcache|uaf|buffer overflow|format string|rop|got|plt|leak|hook|canary|pie|aslr|glibc|fastbin)",
        "rev": r"(decompile|xrefs|obfusc|packer|anti-debug|strings|control flow|cfg|ghidra|radare2)",
        "web": r"(sqli|xss|ssti|ssrf|csrf|auth|upload|path traversal|lfi|rfi|deserial|jwt)",
        "crypto": r"(rsa|ecdsa|nonce|lattice|lll|prng|mt19937|aes|cbc|ctr|hash|dh|ecc|feistel|block cipher|cipher|keystream|galois|gf\(|field|polynomial|interpolation|grobner|xl|ckks|rlwe|lwe|bootstrapping|homomorphic|gmpy2|sympy|sqrt_mod|crt)",
        "misc": r"(pcap|stego|metadata|zip|forensics|exif|binwalk|yara|wireshark)",
    }
    compiled: dict[str, re.Pattern[str]] = {}
    for k, pat in patterns.items():
        try:
            compiled[k] = re.compile(pat, re.I)
        except re.error:
            continue

    for ln in lines:
        for k, cre in compiled.items():
            if cre.search(ln):
                counters[k] += 1

    best = max(counters.items(), key=lambda x: x[1])
    total = sum(counters.values())
    if total == 0:
        return "unknown", 0.0
    confidence = best[1] / total
    if best[1] < min_hits:
        return "unknown", confidence
    return best[0], confidence


CODE_EXTS = {
    ".py",
    ".pyw",
    ".sage",
    ".sagews",
    ".sagemath",
    ".ipynb",
    ".txt",
    ".md",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".js",
    ".ts",
    ".rs",
    ".go",
    ".java",
    ".cs",
    ".rb",
    ".pl",
    ".sh",
}


def extract_code_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for m in re.finditer(r"```([a-zA-Z0-9_+-]*)\\n(.*?)```", text, re.S):
        lang = (m.group(1) or "").strip().lower()
        code = (m.group(2) or "").strip()
        if code:
            blocks.append({"lang": lang, "code": code, "origin": "writeup"})
    return blocks


def extract_code_blocks_from_markdown(text: str) -> list[dict[str, str]]:
    return extract_code_blocks(text)


def extract_code_blocks_from_html(text: str) -> list[dict[str, str]]:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return []
    try:
        soup = BeautifulSoup(text, "lxml")
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
    blocks: list[dict[str, str]] = []
    for pre in soup.find_all("pre"):
        code = pre.get_text("\n", strip=True)
        if not code:
            continue
        lang = ""
        code_tag = pre.find("code")
        if code_tag:
            classes = code_tag.get("class", []) or []
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "").strip().lower()
                    break
                if cls.startswith("lang-"):
                    lang = cls.replace("lang-", "").strip().lower()
                    break
        blocks.append({"lang": lang, "code": code, "origin": "writeup"})
    return blocks


def extract_markdown_links(text: str) -> list[str]:
    links = re.findall(r"\\[[^\\]]+\\]\\(([^)]+)\\)", text)
    return [ln.strip() for ln in links if ln.strip()]


def extract_html_links(text: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return []
    try:
        soup = BeautifulSoup(text, "lxml")
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
    links = []
    for tag in soup.find_all("a"):
        href = tag.get("href") or ""
        href = href.strip()
        if href:
            links.append(href)
    return links


def is_attachment_link(url: str) -> bool:
    low = url.lower()
    if low.startswith(("mailto:", "javascript:", "#")):
        return False
    path = urllib.parse.urlparse(low).path
    ext = Path(path).suffix
    if ext in CODE_EXTS:
        return True
    return False


def safe_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    if not name:
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] + ".txt"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def download_with_limit(url: str, dst: Path, max_bytes: int = 2_000_000) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ctf-study/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            size = resp.headers.get("Content-Length")
            if size and int(size) > max_bytes:
                return False
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return False
            dst.write_bytes(data)
        return True
    except Exception:
        return False


def infer_lang_from_filename(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in {".py", ".pyw"}:
        return "python"
    if ext in {".sage", ".sagews", ".sagemath"}:
        return "sage"
    if ext == ".ipynb":
        return "json"
    if ext in {".c", ".h"}:
        return "c"
    if ext in {".cpp", ".hpp"}:
        return "cpp"
    if ext == ".js":
        return "javascript"
    if ext == ".ts":
        return "typescript"
    if ext == ".rs":
        return "rust"
    if ext == ".go":
        return "go"
    if ext == ".java":
        return "java"
    if ext == ".cs":
        return "csharp"
    if ext == ".rb":
        return "ruby"
    if ext == ".pl":
        return "perl"
    if ext == ".sh":
        return "sh"
    return ""


def extract_payloads(text: str) -> list[str]:
    patterns = [
        r"%\d+\$[a-zA-Z]",
        r"%p",
        r"%s",
        r"%n",
        r"/bin/sh",
        r"__free_hook",
        r"system\(",
        r"execve\(",
        r"eval\(",
        r"union select",
        r"or 1=1",
        r"sleep\(",
        r"benchmark\(",
    ]
    combined = r"(?:%s)" % "|".join(patterns)
    candidates = []
    for m in re.findall(combined, text, re.I):
        candidates.append(m)
    return list(dict.fromkeys(candidates))


def detect_signals(text: str) -> set[str]:
    low = text.lower()
    signals = set()
    patterns = {
        "oracle": r"oracle|query|queries|ask the server",
        "sage": r"sage\.all|polynomialring|zmod|finitefield|gf\(",
        "lll": r"\blll\b|fpylll|lattice",
        "crt": r"crt|chinese remainder",
        "feistel": r"feistel",
        "prng": r"mt19937|mersenne|getrandbits|prng",
        "ecc": r"elliptic|ecdh|ecdsa|curve|point",
        "rsa": r"\brsa\b|modulus|public exponent",
        "discrete_log": r"dlp|discrete log|baby-step|giant-step|pollard",
        "polynomial": r"polynomial|interpolation|grobner|xl",
        "z3": r"z3|smt",
        "pwntools": r"pwntools|from pwn import|context\.binary",
        "rop": r"rop|ret2|plt|got",
        "fmt": r"format string|%n|%hhn|printf",
        "heap": r"heap|tcache|fastbin|unsorted bin",
        "leak": r"leak|libc base|canary|pie",
        "http": r"http|requests|session|cookie|csrf|jwt",
        "sqli": r"sqli|union select|sleep\(",
        "xss": r"xss|<script",
        "ssti": r"ssti|jinja|template",
        "reversing": r"ghidra|ida|radare|xrefs|decompile|strings",
        "emulation": r"unicorn|capstone",
        "stego": r"stego|exif|binwalk|pcap|wireshark",
    }
    for name, pat in patterns.items():
        if re.search(pat, low):
            signals.add(name)
    return signals


def analyze_python_code(code: str) -> tuple[set[str], list[str]]:
    signals: set[str] = set()
    notes: list[str] = []
    imports: set[str] = set()
    calls: set[str] = set()
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.add(name.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    calls.add(func.id)
                elif isinstance(func, ast.Attribute):
                    calls.add(func.attr)
    except Exception:
        pass

    low = code.lower()
    if any(mod.startswith("sage") for mod in imports) or "sage.all" in low:
        signals.add("sage")
        notes.append("脚本使用 Sage 进行代数/有限域建模。")
    if any("z3" in mod for mod in imports) or "z3" in low:
        signals.add("z3")
        notes.append("脚本使用 Z3 进行约束求解。")
    if any("Crypto" in mod or "crypto" in mod for mod in imports) or "crypto.util" in low:
        notes.append("脚本使用 PyCryptodome 做密码相关运算。")
    if any("gmpy2" in mod for mod in imports) or "gmpy2" in low:
        notes.append("脚本使用 gmpy2 做大数/数论运算。")
    if any("sympy" in mod for mod in imports) or "sympy" in low:
        notes.append("脚本使用 SymPy 做符号计算。")
    if any(mod in {"pwn", "pwntools"} or mod.startswith("pwn") for mod in imports) or "from pwn import" in low:
        signals.add("pwntools")
        notes.append("脚本使用 pwntools 驱动本地/远程交互。")
    if any("requests" in mod for mod in imports) or "requests" in low:
        signals.add("http")
        notes.append("脚本使用 requests 自动化 HTTP 交互。")

    if "PolynomialRing" in calls or "Zmod" in calls or "GF" in calls or "FiniteField" in calls or "polynomialring" in low or "zmod(" in low:
        signals.add("polynomial")
        notes.append("脚本构造多项式环/有限域并建立方程。")
    if "EllipticCurve" in calls or "elliptic" in low:
        signals.add("ecc")
        notes.append("脚本涉及椭圆曲线计算。")
    if "lll" in calls or "lll" in low:
        signals.add("lll")
        notes.append("脚本进行 LLL 格规约。")
    if "crt" in calls or "crt" in low:
        signals.add("crt")
        notes.append("脚本使用 CRT 合并同余。")
    if "getrandbits" in low or "mt19937" in low:
        signals.add("prng")
        notes.append("脚本使用 PRNG/MT19937 输出进行恢复。")
    if "feistel" in low:
        signals.add("feistel")
        notes.append("脚本针对 Feistel 结构进行建模。")

    return signals, list(dict.fromkeys(notes))


def analyze_code_snippet(code: str, lang: str, origin: str) -> tuple[set[str], list[str]]:
    lang = (lang or "").lower()
    notes: list[str] = []
    signals: set[str] = set()
    if origin and origin != "writeup":
        notes.append(f"解析附件/代码块来源：{origin}")
    if lang in {"python", "py", "sage"}:
        sigs, extra_notes = analyze_python_code(code)
        signals |= sigs
        notes.extend(extra_notes)
        return signals, list(dict.fromkeys(notes))
    low = code.lower()
    if "pwntools" in low or "from pwn import" in low:
        signals.add("pwntools")
        notes.append("脚本使用 pwntools 驱动交互。")
    if "z3" in low:
        signals.add("z3")
        notes.append("脚本使用 Z3 进行约束求解。")
    if "requests" in low or "http" in low:
        signals.add("http")
        notes.append("脚本自动化 HTTP 交互。")
    if "elliptic" in low:
        signals.add("ecc")
        notes.append("脚本涉及椭圆曲线计算。")
    if "lll" in low:
        signals.add("lll")
        notes.append("脚本进行 LLL 格规约。")
    if "feistel" in low:
        signals.add("feistel")
        notes.append("脚本针对 Feistel 结构进行建模。")
    return signals, list(dict.fromkeys(notes))


def build_workflow(category: str, signals: set[str], lang: str) -> list[str]:
    zh = lang == "zh"
    steps: list[str] = []
    if category == "crypto":
        steps.append("识别密码结构与可控输入/输出关系（从题面与代码确认假设）" if zh else "Identify the scheme and the controllable input/output relation from the statement/code.")
        if "oracle" in signals:
            steps.append("刻画 oracle 约束，将响应转成可解的数学关系" if zh else "Model the oracle responses as solvable mathematical relations.")
        if "feistel" in signals and "polynomial" in signals:
            steps.append("将轮函数建模为 GF 上低次多项式，拆轮得到中间态关系" if zh else "Model the round function as a low-degree polynomial over GF and split rounds to relate the middle state.")
        if "sage" in signals or "polynomial" in signals:
            steps.append("用 Sage/PolynomialRing 建模并构造线性系统或插值恢复系数" if zh else "Model in Sage/PolynomialRing and build linear systems/interpolation to recover coefficients.")
        if "lll" in signals:
            steps.append("构造格/矩阵并做 LLL 还原隐藏量" if zh else "Build a lattice/matrix and apply LLL to recover hidden values.")
        if "crt" in signals:
            steps.append("用 CRT 合并同余解" if zh else "Combine congruences with CRT.")
        if "prng" in signals:
            steps.append("从部分输出恢复 PRNG 状态并预测后续输出" if zh else "Recover PRNG state from partial outputs to predict future outputs.")
        if "ecc" in signals or "discrete_log" in signals:
            steps.append("将问题化为曲线/群上的 DLP 或因子分解并用对应算法求解" if zh else "Reduce to DLP/factorization on curves/groups and solve with the corresponding algorithm.")
        steps.append("实现求解脚本并回代验证，输出 flag" if zh else "Implement the solver, validate by substitution, and output the flag.")
        return steps
    if category == "pwn":
        steps.append("checksec 明确保护，确定需要的泄露与控制目标" if zh else "Run checksec to map protections and decide required leaks/control.")
        if "fmt" in signals:
            steps.append("定位格式化字符串偏移，设计读/写原语" if zh else "Find format-string offset and design read/write primitives.")
        if "heap" in signals:
            steps.append("构造堆布局并利用 tcache/fastbin 等机制建立写原语" if zh else "Shape the heap and use tcache/fastbin mechanics to build a write primitive.")
        if "rop" in signals:
            steps.append("准备 ROP/ret2 载荷，完成控制流劫持" if zh else "Prepare ROP/ret2 payload to hijack control flow.")
        if "leak" in signals:
            steps.append("泄露 libc/堆/栈基址，计算真实地址" if zh else "Leak libc/heap/stack base and compute real addresses.")
        steps.append("本地复现后迁移到远程，拿 shell/读取 flag" if zh else "Validate locally, then move to remote to get shell/read flag.")
        return steps
    if category == "rev":
        steps.append("静态分析定位关键校验/解密逻辑（字符串、xrefs、CFG）" if zh else "Use static analysis to locate key checks/decoding logic (strings/xrefs/CFG).")
        if "emulation" in signals:
            steps.append("必要时用模拟执行还原关键路径" if zh else "Use emulation to recover critical paths when needed.")
        if "z3" in signals:
            steps.append("将约束转为 SMT/方程并自动求解" if zh else "Translate constraints to SMT/equations and solve.")
        steps.append("重写算法脚本化求逆，批量验证得到 flag" if zh else "Reimplement/invert the algorithm in a script and verify to recover the flag.")
        return steps
    if category == "web":
        steps.append("梳理流程与状态（登录、权限、会话）并定位入口点" if zh else "Map the flow/state (auth/session) and identify entry points.")
        if "sqli" in signals:
            steps.append("验证 SQL 注入并构造数据泄露/提权链" if zh else "Confirm SQLi and craft data exfil/priv-esc chain.")
        if "xss" in signals:
            steps.append("构造可触发 XSS 的载荷并拿到目标 token/权限" if zh else "Craft a reliable XSS payload to steal token/privileges.")
        if "ssti" in signals:
            steps.append("验证模板注入并提升到命令执行/敏感数据读取" if zh else "Confirm SSTI and escalate to RCE/data read.")
        steps.append("脚本化请求复现，稳定拿到 flag" if zh else "Automate requests to reproduce and obtain the flag.")
        return steps
    if category == "forensics":
        steps.append("先做廉价取证体检（file/strings/exif/binwalk/metadata）锁定强信号附件" if zh else "Run cheap forensics triage (file/strings/exif/binwalk/metadata) to find the strongest artifact.")
        if "pcap" in signals:
            steps.append("优先重建通信视角（协议、流、导出对象、时间线）" if zh else "Prioritize protocol/stream/object/timeline reconstruction for packet captures.")
        if "memory" in signals or "volatility" in signals:
            steps.append("先用框架枚举进程/模块/可疑对象，再缩小到目标证据" if zh else "Enumerate processes/modules/suspicious objects first, then narrow to the target evidence.")
        if "stego" in signals or "exif" in signals or "binwalk" in signals:
            steps.append("检查图层、alpha、bitplane、嵌入段和容器结构，不要只做 OCR" if zh else "Check layers, alpha, bitplanes, embedded segments, and container structure instead of relying on OCR alone.")
        steps.append("把提取链脚本化，确保中间产物可复现和可比较" if zh else "Script the extraction chain so intermediate artifacts are reproducible and comparable.")
        return steps
    if category == "osint":
        steps.append("先抽取唯一标识符（用户名、域名、时间、地理线索、平台账号）再做外部检索" if zh else "Extract unique identifiers first (handles/domains/time/geolocation/platform accounts) before external pivots.")
        steps.append("优先使用一手来源和官方渠道，避免被二手转载带偏" if zh else "Prioritize primary sources and official channels to avoid being dragged off-path by mirrors or reposts.")
        if "geo" in signals or "geolocation" in signals or "map" in signals:
            steps.append("用地图、街景、地物和时间线交叉验证，不要只靠单张图匹配" if zh else "Cross-check maps, street view, landmarks, and timeline instead of relying on single-image matching.")
        if "wayback" in signals or "archive" in signals or "social" in signals:
            steps.append("同步检查历史快照和社交平台时间线，确认线索出现顺序" if zh else "Check archives and social timelines together to confirm the order in which clues appeared.")
        steps.append("把来源链接和关键证据点记录下来，最后再收敛到 flag" if zh else "Record source links and key evidence points before converging on the flag.")
        return steps
    if category == "malware":
        steps.append("静态优先：确认文件类型、打包痕迹、字符串、导入表和可疑配置位点" if zh else "Start with static analysis: confirm type, packing signs, strings, imports, and likely config locations.")
        if "dotnet" in signals or ".net" in signals:
            steps.append("优先走 .NET 元数据和 IL 恢复链，不要先盲跑样本" if zh else "Prefer .NET metadata/IL recovery before blindly executing the sample.")
        if "shellcode" in signals or "packed" in signals or "obfus" in signals:
            steps.append("先解包或还原 payload，再讨论行为分析" if zh else "Unpack or recover the payload before behavior analysis.")
        steps.append("动态分析只在隔离环境中进行，并把网络、文件和进程痕迹落盘" if zh else "Do dynamic analysis only in isolation and persist network/file/process artifacts.")
        steps.append("最后把配置、解密链或行为链脚本化，避免只留下人工观察结论" if zh else "Script config extraction, decryption, or behavior reconstruction instead of relying on manual observations.")
        return steps
    if category == "misc":
        steps.append("快速文件体检（file/strings/metadata/解包）锁定可疑点" if zh else "Run quick triage (file/strings/metadata/unpack) to locate artifacts.")
        if "stego" in signals:
            steps.append("尝试隐写/取证工具（binwalk/exif/pcap）提取隐藏数据" if zh else "Use stego/forensics tools (binwalk/exif/pcap) to extract hidden data.")
        steps.append("编写脚本自动化解码/提取流程" if zh else "Automate decode/extract steps with a script.")
        return steps
    steps.append("提取题目结构与关键约束，验证假设后脚本化求解" if zh else "Extract structure/constraints, validate assumptions, then script the solve.")
    return steps


def infer_key_points_from_code(code: str, category: str) -> list[str]:
    points: list[str] = []
    low = code.lower()
    if category == "pwn":
        if "__free_hook" in low:
            points.append("Uses __free_hook overwrite to redirect control flow.")
        if "system(" in low:
            points.append("Calls system to execute command after control hijack.")
        if "%n" in low or "%hhn" in low:
            points.append("Uses format string write primitive (%n/%hhn).")
        if "tcache" in low or "fastbin" in low:
            points.append("Relies on heap bin/tcache manipulation.")
    if category == "web":
        if "requests" in low or "curl" in low:
            points.append("Automates HTTP exploitation with scripted requests.")
        if "jwt" in low:
            points.append("JWT manipulation involved in auth bypass.")
    if category == "crypto":
        if "lll" in low or "fpylll" in low:
            points.append("Lattice/LLL reduction used to recover secrets.")
    if category == "rev":
        if "unicorn" in low or "capstone" in low:
            points.append("Uses emulation/disassembly to recover logic.")
    return points


def extract_pdf_text(path: Path) -> str:
    if shutil_which("pdftotext"):
        try:
            out = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return out.stdout
        except Exception:
            pass
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        return ""


def extract_html_text(data: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(data)
    return parser.text()


def extract_html_sectioned_text(data: str, section_hint: str = "") -> str:
    def extract_clean_text(raw_html: str) -> str:
        try:
            import trafilatura  # type: ignore

            extracted = trafilatura.extract(
                raw_html,
                include_comments=False,
                include_tables=False,
                include_links=False,
                favor_recall=True,
            )
            if extracted:
                return extracted
        except Exception:
            pass
        try:
            from readability import Document  # type: ignore

            doc = Document(raw_html)
            html_summary = doc.summary(html_partial=True)
            soup = BeautifulSoup(html_summary, "lxml")
            return soup.get_text("\n", strip=True)
        except Exception:
            return ""

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return extract_html_text(data)

    parser = "lxml"
    try:
        soup = BeautifulSoup(data, parser)
    except Exception:
        soup = BeautifulSoup(data, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    container = soup.find("article") or soup.find("main") or soup.body or soup
    for tag in container.find_all(["nav", "aside", "header", "footer"]):
        tag.decompose()

    headings = {"h1", "h2", "h3", "h4", "h5", "h6"}
    sections: list[dict[str, object]] = []
    current = {"title": "", "id": "", "lines": []}

    def gather_section_from_heading(heading) -> str:
        title = heading.get_text(" ", strip=True)
        level = 6
        if heading.name in headings:
            try:
                level = int(heading.name[1])
            except Exception:
                level = 6
        lines = [title] if title else []
        for elem in heading.find_all_next():
            if elem not in container.descendants:
                break
            if elem.name in headings:
                try:
                    nxt = int(elem.name[1])
                except Exception:
                    nxt = level
                if nxt <= level:
                    break
            if elem.name in {"p", "li", "blockquote"}:
                t = elem.get_text(" ", strip=True)
                if t:
                    lines.append(t)
            elif elem.name == "pre":
                t = elem.get_text("\n", strip=True)
                if t:
                    lines.append(t)
            elif elem.name == "code" and (not elem.parent or elem.parent.name != "pre"):
                t = elem.get_text(" ", strip=True)
                if t:
                    lines.append(t)
        return "\n".join(lines)

    hint = normalize_section_hint(section_hint) if section_hint else ""
    if not hint:
        cleaned = extract_clean_text(data)
        if cleaned and len(cleaned) > 200:
            return cleaned
    if hint:
        target = container.find(id=hint) or container.find(attrs={"name": hint})
        if target and target.name not in headings:
            parent_heading = target.find_parent(headings)
            if parent_heading:
                return gather_section_from_heading(parent_heading)
        if target and target.name in headings:
            return gather_section_from_heading(target)

    for elem in container.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "code", "li", "blockquote"],
        recursive=True,
    ):
        text = elem.get_text(" ", strip=True)
        if not text:
            continue
        if elem.name in headings:
            if current["title"] or current["lines"]:
                sections.append(current)
            current = {
                "title": text,
                "id": elem.get("id", "") or elem.get("name", "") or "",
                "lines": [],
            }
            continue
        if elem.name == "code" and elem.parent and elem.parent.name == "pre":
            continue
        current["lines"].append(text)

    if current["title"] or current["lines"]:
        sections.append(current)

    if not sections:
        return extract_html_text(data)

    if hint:
        candidates = []
        for sec in sections:
            title = str(sec.get("title", ""))
            sec_id = str(sec.get("id", "")).lower()
            title_norm = normalize_section_hint(title)
            if hint == sec_id or hint == title_norm or hint in title_norm:
                candidates.append(sec)
        if not candidates:
            for sec in sections:
                lines = sec.get("lines", [])
                if any(hint in str(ln).lower() for ln in lines[:10]):
                    candidates.append(sec)
        if candidates:
            best = max(candidates, key=lambda s: len(s.get("lines", [])))
            out = []
            title = str(best.get("title", ""))
            if title:
                out.append(title)
            out.extend([str(x) for x in best.get("lines", [])])
            return "\n".join(out)

    out = []
    for sec in sections:
        title = str(sec.get("title", ""))
        if title:
            out.append(title)
        out.extend([str(x) for x in sec.get("lines", [])])
    return "\n".join(out)


def normalize_lines(text: str) -> list[str]:
    unescaped = html.unescape(text)
    lines = [ln.strip() for ln in unescaped.splitlines()]
    return [ln for ln in lines if ln]


def filter_noise_lines(lines: list[str]) -> list[str]:
    noise_patterns = [
        r"astro-",
        r"data-astro",
        r"classlist\\.",
        r"navigator\\.clipboard",
        r"document\\.",
        r"window\\.",
        r"addeventlistener",
        r"queryselector",
        r"getelementbyid",
        r"settimeout",
        r"pre\\.style\\.",
        r"onclick=",
        r"toggledarkmode",
        r"toclinks",
        r"scroll",
        r"^const\\s",
        r"^let\\s",
        r"^var\\s",
    ]
    out: list[str] = []
    for ln in lines:
        low = ln.lower()
        if any(re.search(pat, low) for pat in noise_patterns):
            continue
        out.append(ln)
    return out


def looks_like_codeish(line: str) -> bool:
    if re.search(r"[=;{}]", line):
        return True
    if re.search(r"\\b(import|from|def|class|return|if|for|while)\\b", line, re.I):
        return True
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", line) and re.search(r"[=;]", line):
        return True
    if line.strip().endswith(".py"):
        return True
    return False


def is_good_key_point(line: str) -> bool:
    if len(line) < 12 or len(line) > 200:
        return False
    low = line.lower()
    if line.endswith(":"):
        return False
    if low.startswith("title:") or low.startswith("url source:"):
        return False
    if "kore.one" in low:
        return False
    if "writeup" in low and "solution" not in low and "path" not in low:
        return False
    if re.match(r"^#+\\s", line):
        return False
    if re.search(r"```|<[^>]+>|&[a-z]+;", line):
        return False
    if re.search(r"(pre\\.style|document\\.|window\\.|queryselector|addeventlistener)", low):
        return False
    if looks_like_codeish(line):
        return False
    letters = sum(1 for ch in line if ch.isalpha() or ("\u4e00" <= ch <= "\u9fff"))
    if letters / max(1, len(line)) < 0.3:
        return False
    return True


def shorten_line(line: str, max_len: int = 200) -> str:
    if len(line) <= max_len:
        return line
    # try sentence boundary
    for sep in [". ", "。", "！", "?", "；", ";"]:
        if sep in line:
            head = line.split(sep)[0] + (sep.strip() if sep.strip() in {".", "。", "！", "?", ";"} else "")
            head = head.strip()
            if 12 <= len(head) <= max_len:
                return head
    return line[:max_len].rstrip()

def detect_language(text: str) -> str:
    if not text:
        return "zh"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    total = cjk + letters
    if total == 0:
        return "zh"
    return "zh" if (cjk / total) >= 0.2 else "en"


def select_key_points(lines: Iterable[str], category: str, limit: int = 12) -> list[str]:
    keywords = {
        "pwn": r"(heap|tcache|uaf|buffer overflow|format string|rop|got|plt|leak|hook|canary|pie|aslr)",
        "rev": r"(decompile|xrefs|obfusc|packer|anti-debug|strings|control flow|cfg)",
        "web": r"(sqli|xss|ssti|ssrf|csrf|auth|upload|path traversal|lfi|rfi|deserial|jinja|template|flag)",
        "crypto": r"(rsa|ecdsa|nonce|lattice|lll|prng|mt19937|aes|cbc|ctr|hash|feistel|block cipher|cipher|keystream|galois|gf\(|field|polynomial|interpolation|grobner|xl|ckks|rlwe|lwe|bootstrapping|homomorphic)",
        "misc": r"(pcap|stego|metadata|zip|forensics|exif|binwalk|yara)",
        "unknown": r"(漏洞|利用|绕过|leak|overflow|format|string|uaf|xss|sqli|ssti|ssrf|rop|heap|解密|逆向|payload|feistel|gf\(|galois|xl|grobner|ckks|rlwe|lwe|mt19937|cipher|keystream)",
    }
    pattern_source = keywords.get(category, keywords["unknown"])
    try:
        pattern = re.compile(pattern_source, re.I)
    except re.error:
        pattern = re.compile(r".*")
    candidates: list[tuple[int, int, str]] = []
    action_pat = re.compile(r"(发现|利用|绕过|构造|泄露|读取|执行|注入|触发|bypass|leak|read|execute|inject|exploit|abuse)", re.I)
    for idx, ln in enumerate(lines):
        cleaned = ln.strip("-* \t")
        cleaned = shorten_line(cleaned, 200)
        if not is_good_key_point(cleaned):
            continue
        score = 0
        if pattern.search(cleaned):
            score += 2
        if action_pat.search(cleaned):
            score += 1
        if score > 0:
            candidates.append((score, idx, cleaned))

    if candidates:
        # pick highest scoring lines, preserve original order for ties
        candidates.sort(key=lambda x: (-x[0], x[1]))
        picked = []
        seen = set()
        for _, _, text in candidates:
            if text in seen:
                continue
            seen.add(text)
            picked.append(text)
            if len(picked) >= limit:
                break
        return picked

    # fallback: accept any good line
    out: list[str] = []
    for ln in lines:
        cleaned = ln.strip("-* \t")
        cleaned = shorten_line(cleaned, 200)
        if not is_good_key_point(cleaned):
            continue
        if cleaned not in out:
            out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def select_problem_points(lines: Iterable[str], limit: int = 8) -> list[str]:
    pattern = re.compile(
        r"(flag|输入|输出|限制|附件|源码|链接|host|port|nc |http|题目|描述|给定|任务|目标|要求)",
        re.I,
    )
    out: list[str] = []
    for ln in lines:
        if len(ln) < 8 or len(ln) > 220:
            continue
        if ln.strip().startswith("$") and "curl" in ln.lower():
            continue
        if "curl -s" in ln.lower() or "curl -i" in ln.lower():
            continue
        if pattern.search(ln) and ln not in out:
            out.append(ln)
        if len(out) >= limit:
            break
    if not out:
        for ln in lines:
            if len(ln) < 8 or len(ln) > 200:
                continue
            if ln not in out:
                out.append(ln)
            if len(out) >= limit:
                break
    return out


def merge_points(primary: list[str], secondary: list[str], limit: int = 14) -> list[str]:
    out = []
    seen = set()
    for item in primary + secondary:
        norm = re.sub(r"\\s+", " ", item.strip())
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
        if len(out) >= limit:
            break
    return out


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def looks_like_html(raw_text: str) -> bool:
    head = raw_text[:2000].lower()
    return "<html" in head or "<!doctype html" in head or "<article" in head or "<main" in head


def fetch_source_text(
    source: str,
    attachments_dir: Path,
    label: str,
    section_hint: str = "",
    render: bool = True,
    jina: bool = True,
) -> tuple[str, str, str]:
    if not source:
        return "", ""
    if re.match(r"^https?://", source):
        ext = Path(source.split("?")[0]).suffix or ".txt"
        download_path = attachments_dir / f"{label}{ext}"
        if jina and not source.lower().endswith(".pdf"):
            jina_path = attachments_dir / f"{label}.jina.txt"
            jina_text = fetch_jina_text(source, jina_path)
            if jina_text:
                if section_hint:
                    jina_lines = filter_noise_lines(normalize_lines(jina_text))
                    jina_lines = filter_section(jina_lines, section_hint)
                    jina_text = "\n".join(jina_lines)
                return jina_text, str(jina_path), "text"
        if render and not source.lower().endswith(".pdf"):
            rendered = render_url(source)
            if rendered:
                download_path = attachments_dir / f"{label}.html"
                download_path.write_text(rendered, encoding="utf-8")
                detected = "html"
                text = extract_html_sectioned_text(rendered, section_hint)
                return text, str(download_path), detected
        raw, content_type = download_url(source, download_path)
        detected = detect_type(download_path.name, content_type)
        if detected == "pdf":
            text = extract_pdf_text(download_path)
        else:
            text = raw.decode(errors="ignore")
            if detected == "html" or looks_like_html(text):
                text = extract_html_sectioned_text(text, section_hint)
        return text, str(download_path), detected

    src_path = Path(source).expanduser().resolve()
    if not src_path.exists():
        raise SystemExit(f"source not found: {src_path}")
    dst_path = attachments_dir / src_path.name
    if src_path != dst_path:
        dst_path.write_bytes(src_path.read_bytes())
    detected = detect_type(dst_path.name)
    if detected == "pdf":
        text = extract_pdf_text(dst_path)
    else:
        text = dst_path.read_text(encoding="utf-8", errors="ignore")
        if detected == "html" or looks_like_html(text):
            text = extract_html_sectioned_text(text, section_hint)
    return text, str(dst_path), detected


def main() -> int:
    parser = argparse.ArgumentParser(description="Study writeups and extract reusable points.")
    parser.add_argument("--source", default="", help="URL or file path to writeup (html/pdf/md/txt)")
    parser.add_argument("--problem", default="", help="Optional URL or file path to problem description")
    parser.add_argument("--writeup", default="", help="Optional URL or file path to writeup/solution")
    parser.add_argument("--section", default="", help="Optional section/anchor to focus on (e.g. noisy-forest)")
    parser.add_argument("--render", default="on", choices=["on", "off"], help="Use headless browser rendering for URLs")
    parser.add_argument("--jina", default="on", choices=["on", "off"], help="Use r.jina.ai text extraction for URLs")
    parser.add_argument("--category", default="auto", choices=["auto", "pwn", "rev", "web", "crypto", "misc", "forensics", "osint", "malware", "unknown"])
    parser.add_argument("--title", default="", help="Optional title for the study entry")
    parser.add_argument("--work-root", default="./workspace/study")
    args = parser.parse_args()

    if not args.source and not args.problem and not args.writeup:
        raise SystemExit("must provide --source or --problem/--writeup")

    source = args.source or args.writeup or args.problem
    category = args.category
    render_enabled = args.render == "on"
    jina_enabled = args.jina == "on"

    section_hint = args.section
    if not section_hint:
        section_hint = extract_fragment_hint(args.source or "")

    title = args.title or Path(source).stem or "study"
    slug = slugify(title)
    work_dir = Path(args.work_root).resolve() / f"ctf-study-{slug}"
    attachments_dir = work_dir / "attachments"
    logs_dir = work_dir / "logs"

    attachments_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    problem_text = ""
    writeup_text = ""
    problem_source = args.problem
    writeup_source = args.writeup
    problem_path = ""
    writeup_path = ""
    problem_type = ""
    writeup_type = ""

    if args.problem or args.writeup:
        if args.problem:
            problem_text, problem_path, problem_type = fetch_source_text(
                args.problem,
                attachments_dir,
                "problem",
                extract_fragment_hint(args.problem),
                render=render_enabled,
                jina=jina_enabled,
            )
        if args.writeup:
            writeup_text, writeup_path, writeup_type = fetch_source_text(
                args.writeup,
                attachments_dir,
                "writeup",
                extract_fragment_hint(args.writeup),
                render=render_enabled,
                jina=jina_enabled,
            )
        else:
            writeup_text, writeup_path, writeup_type = fetch_source_text(
                source,
                attachments_dir,
                "source",
                section_hint,
                render=render_enabled,
                jina=jina_enabled,
            )
            writeup_source = source
        combined_text = "\n".join([problem_text, writeup_text]).strip()
    else:
        combined_text, source_path, source_type = fetch_source_text(
            source,
            attachments_dir,
            "source",
            section_hint,
            render=render_enabled,
            jina=jina_enabled,
        )
        problem_source = ""
        writeup_source = source
        writeup_path = source_path
        writeup_type = source_type

    if not combined_text:
        combined_text = "(no text extracted)"

    writeup_raw = ""
    if writeup_path:
        try:
            writeup_raw = Path(writeup_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            writeup_raw = ""

    code_snippets: list[dict[str, str]] = []
    attachment_links: list[str] = []
    if writeup_raw:
        if writeup_type == "html" or looks_like_html(writeup_raw):
            code_snippets.extend(extract_code_blocks_from_html(writeup_raw))
            attachment_links.extend(extract_html_links(writeup_raw))
        else:
            code_snippets.extend(extract_code_blocks_from_markdown(writeup_raw))
            attachment_links.extend(extract_markdown_links(writeup_raw))

    if not code_snippets:
        code_snippets.extend(extract_code_blocks(writeup_text or combined_text))

    attachment_paths: list[Path] = []
    if attachment_links and writeup_source and re.match(r"^https?://", writeup_source):
        base = writeup_source
        seen_links: set[str] = set()
        for link in attachment_links:
            if link in seen_links:
                continue
            seen_links.add(link)
            if not is_attachment_link(link):
                continue
            full = urllib.parse.urljoin(base, link)
            if not re.match(r"^https?://", full):
                continue
            filename = safe_filename_from_url(full)
            dst = attachments_dir / filename
            if download_with_limit(full, dst):
                attachment_paths.append(dst)

    for path in attachment_paths:
        if path.suffix.lower() not in CODE_EXTS:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not content.strip():
            continue
        code_snippets.append(
            {
                "lang": infer_lang_from_filename(path.name),
                "code": content,
                "origin": path.name,
            }
        )

    combined_lines = filter_noise_lines(normalize_lines(combined_text))
    if section_hint and args.section and not (problem_text or writeup_text):
        combined_lines = filter_section(combined_lines, section_hint)
    if problem_text or writeup_text:
        problem_lines = filter_noise_lines(normalize_lines(problem_text))
        solution_lines = filter_noise_lines(normalize_lines(writeup_text))
        split_note = "explicit_sources"
    else:
        problem_lines, solution_lines, split_note = split_problem_writeup(combined_lines)
    if not solution_lines:
        solution_lines = combined_lines

    if section_hint and args.section:
        solution_lines = filter_section(solution_lines, section_hint)

    section_title = ""
    if section_hint:
        for ln in solution_lines[:6]:
            if looks_like_heading(ln) and len(ln) <= 80:
                section_title = ln.strip().rstrip("#").strip()
                break
        if not section_title:
            section_title = normalize_section_hint(section_hint).replace("-", " ").title()
    if category == "auto":
        min_hits = 1 if section_hint else 3
        category, confidence = guess_category(solution_lines or combined_lines, min_hits=min_hits)
    else:
        confidence = 1.0

    code_points = []
    for block in code_snippets[:6]:
        code_points.extend(infer_key_points_from_code(block.get("code", ""), category))

    key_points = select_key_points(solution_lines + problem_lines, category)
    problem_points = select_problem_points(problem_lines)
    if section_title and section_hint:
        problem_points = [section_title]
    elif section_title and not problem_points:
        problem_points = [section_title]
    elif section_title and problem_points:
        codeish = sum(1 for ln in problem_points if looks_like_codeish(ln))
        if codeish >= max(1, len(problem_points) // 2):
            problem_points = [section_title]
    payload_points = []
    payloads = extract_payloads(writeup_text or combined_text)
    if payloads:
        payload_points.append("Payload indicators: " + ", ".join(payloads[:12]))

    key_points = merge_points(key_points, code_points + payload_points)

    code_notes: list[str] = []
    signal_text = "\n".join([combined_text, "\n".join(block.get("code", "") for block in code_snippets)])
    signals = detect_signals(signal_text)
    for block in code_snippets[:8]:
        sigs, notes = analyze_code_snippet(block.get("code", ""), block.get("lang", ""), block.get("origin", ""))
        signals |= sigs
        for note in notes:
            if note not in code_notes:
                code_notes.append(note)

    # Write metadata
    meta = {
        "title": title,
        "category": category,
        "source": source,
        "problem_source": problem_source,
        "writeup_source": writeup_source,
        "split_note": split_note,
        "section_title": section_title,
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    write_text(work_dir / "challenge.json", __import__("json").dumps(meta, indent=2, ensure_ascii=False))

    # Build writeup.md
    lang = detect_language("\n".join(solution_lines[:200]) or combined_text)
    labels = {
        "zh": {
            "title": f"# 学习：{title}",
            "summary": "## 摘要",
            "problem_summary": "## 题目摘要",
            "writeup_summary": "## 解题摘要",
            "script_analysis": "## 脚本分析",
            "workflow": "## 解题路径",
            "analysis": "## 分析",
            "attempts": "## 试错与迭代",
            "inference": "## 推断",
            "problem_excerpt": "## 题目摘录",
            "writeup_excerpt": "## 解题摘录",
            "type": "类型",
            "confidence": "置信度",
            "source": "来源",
            "no_problem": "（未提取到题目摘要）",
            "no_keypoints": "（未提取到关键点）",
            "no_script_analysis": "（未提取到脚本特征）",
            "no_workflow": "（未提取到解题路径）",
            "no_problem_excerpt": "（无题目摘录）",
            "no_writeup_excerpt": "（无解题摘录）",
            "analysis_hint": "- （可选）",
            "attempts_hint": "- （可选）",
            "inference_hint": "- 若内容稀少，可给出最小推断步骤并明确标注为推断",
        },
        "en": {
            "title": f"# Study: {title}",
            "summary": "## Summary",
            "problem_summary": "## Problem Summary",
            "writeup_summary": "## Writeup Summary",
            "script_analysis": "## Script Analysis",
            "workflow": "## Solution Path",
            "analysis": "## Analysis",
            "attempts": "## Attempts",
            "inference": "## Inference",
            "problem_excerpt": "## Problem Excerpt",
            "writeup_excerpt": "## Writeup Excerpt",
            "type": "Type",
            "confidence": "Confidence",
            "source": "Source",
            "no_problem": "(no problem summary extracted)",
            "no_keypoints": "(no key points extracted)",
            "no_script_analysis": "(no script insights extracted)",
            "no_workflow": "(no solution path extracted)",
            "no_problem_excerpt": "(no problem excerpt)",
            "no_writeup_excerpt": "(no writeup excerpt)",
            "analysis_hint": "- (optional)",
            "attempts_hint": "- (optional)",
            "inference_hint": "- If sparse, infer minimal steps and mark as inference",
        },
    }[lang]

    out_lines = [
        labels["title"],
        "",
        labels["summary"],
        f"- {labels['type']}: {category}",
        f"- {labels['confidence']}: {confidence:.2f}",
        f"- {labels['source']}: {source}",
        "",
        labels["problem_summary"],
    ]
    if problem_points:
        for p in problem_points:
            out_lines.append(f"- {p}")
    else:
        out_lines.append(f"- {labels['no_problem']}")

    out_lines.extend(
        [
            "",
            labels["writeup_summary"],
        ]
    )
    if key_points:
        for p in key_points:
            out_lines.append(f"- {p}")
    else:
        out_lines.append(f"- {labels['no_keypoints']}")

    out_lines.extend(
        [
            "",
            labels["script_analysis"],
        ]
    )
    if code_notes:
        for note in code_notes:
            out_lines.append(f"- {note}")
    else:
        out_lines.append(f"- {labels['no_script_analysis']}")

    workflow = build_workflow(category, signals, lang)
    # If we have specific key points, prefer them as solution path.
    action_pat = re.compile(r"(发现|利用|绕过|构造|泄露|读取|执行|注入|触发|bypass|leak|read|execute|inject|exploit|abuse)", re.I)
    keyword_pat = re.compile(r"(xss|sqli|ssti|ssrf|rce|jinja|template|grammar|parser|feistel|rop|heap|uaf|crypto|rsa|lattice|rev|decomp|stego|forensics|leak|bypass|exploit)", re.I)
    specific_steps = [p for p in key_points if action_pat.search(p) or keyword_pat.search(p)]
    if len(specific_steps) >= 3:
        workflow = specific_steps[:6]
    out_lines.extend(
        [
            "",
            labels["workflow"],
        ]
    )
    if workflow:
        for step in workflow:
            out_lines.append(f"- {step}")
    else:
        out_lines.append(f"- {labels['no_workflow']}")

    out_lines.extend(
        [
            "",
            labels["analysis"],
            labels["analysis_hint"],
            "",
            labels["attempts"],
            labels["attempts_hint"],
            "",
            labels["inference"],
            labels["inference_hint"],
            "",
            labels["problem_excerpt"],
        ]
    )
    problem_excerpt = "\n".join(problem_lines[:120])
    writeup_excerpt = "\n".join(solution_lines[:200])
    if not problem_excerpt:
        problem_excerpt = labels["no_problem_excerpt"]
    out_lines.append("```text")
    out_lines.append(problem_excerpt)
    out_lines.append("```")
    out_lines.extend(
        [
            "",
            labels["writeup_excerpt"],
            "```text",
            writeup_excerpt or labels["no_writeup_excerpt"],
            "```",
        ]
    )

    write_text(work_dir / "writeup.md", "\n".join(out_lines) + "\n")

    # Trigger learning update
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "ctf_learn.py"),
            "--project",
            str(work_dir),
            "--status",
            "unsolved",
        ],
        check=False,
    )

    print(f"[+] study workspace: {work_dir}")
    print(f"[+] writeup: {work_dir / 'writeup.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
