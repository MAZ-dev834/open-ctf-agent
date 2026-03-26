#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

try:
    from ctf_meta import load_category_meta, normalize_project_key
except Exception:  # pragma: no cover
    import sys

    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.learn.ctf_meta import load_category_meta, normalize_project_key

DEFAULT_PATTERN = {
    "pwn": [
        "Start with checksec and map mitigations to required leak strategy.",
        "Validate crash primitive locally before touching remote service.",
        "Keep exploit scripts parameterized for host/port and libc offsets.",
    ],
    "rev": [
        "Prioritize static control-flow recovery before deep dynamic tracing.",
        "Rebuild key transforms in script to keep the solve deterministic.",
        "Track string/xref anchors early to cut search space.",
    ],
    "web": [
        "Map auth and state transitions before fuzzing endpoints.",
        "Reproduce one minimal request chain, then automate it.",
        "Use source-first analysis when attachments include backend code.",
    ],
    "crypto": [
        "Identify scheme class first, then test assumptions with tiny samples.",
        "Prefer deterministic math scripts over manual calculator steps.",
        "Keep recovered constants/keys in one reproducible solver.",
    ],
    "misc": [
        "Run fast file triage first (type/metadata/strings/extract).",
        "Automate repeated decode/extract loops with a script.",
        "Record each failed hypothesis to avoid duplicate paths.",
    ],
    "unknown": [
        "Tighten hypotheses quickly and script every repeated action.",
        "Store reproducible commands and artifacts in challenge directory.",
        "Promote reusable patterns after each solve attempt.",
    ],
}

SECTION_HINTS = [
    "解题摘要",
    "解题路径",
    "解题过程",
    "脚本分析",
    "script analysis",
    "solution path",
    "workflow",
    "writeup summary",
    "key points",
    "步骤",
    "流程",
    "复现",
    "复用点",
    "可复用",
    "总结",
    "analysis",
    "思路",
]

PREFERRED_SECTION_HINTS = [
    "解题路径",
    "解题过程",
    "solution path",
    "workflow",
    "步骤",
    "流程",
]

KEY_SIGNAL_HINTS = [
    "key signals",
    "key signal",
    "key terms",
    "key term",
    "关键术语",
    "关键词",
    "关键点",
    "关键模型",
]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_category(project_dir: Path) -> str:
    category, _, _, _ = load_category_meta(project_dir, read_text)
    return category


def looks_like_command(cmd: str) -> bool:
    cmd = cmd.strip().strip("`")
    if not cmd:
        return False
    if cmd.startswith(("http://", "https://")):
        return False
    if re.fullmatch(r"\([^)]*\)", cmd):
        return False
    has_flag = bool(re.search(r"(\s|^)--?\w", cmd))
    has_tool = bool(
        re.search(
            r"\b(python3?|sage|gdb|pwndbg|peda|objdump|readelf|checksec|nm|strings|r2|radare2|ghidra|curl|wget|nc|socat|strace|ltrace|docker|pip|apt|tshark|binwalk|zsteg|exiftool)\b",
            cmd,
        )
    )
    has_ext = bool(re.search(r"(\.py|\.sh|\.pl|\.rb)(\s|$)", cmd))
    has_path = bool(re.search(r"(^|\s)(/[^\s]+|\./[^\s]+)", cmd))
    if has_flag or has_tool or has_ext or has_path:
        return True
    if re.fullmatch(r"[A-Za-z0-9_+*/().\s-]+", cmd):
        return False
    return False


def extract_commands(text: str, limit: int = 8) -> list[str]:
    cmds: list[str] = []
    for cmd in re.findall(r"`([^`\n]{3,180})`", text):
        cmd = cmd.strip()
        if not cmd:
            continue
        if cmd.startswith(("http://", "https://")):
            continue
        if "http://" in cmd or "https://" in cmd:
            continue
        if re.match(r"^/[^\s]+", cmd):
            continue
        if not looks_like_command(cmd):
            continue
        if cmd not in cmds:
            cmds.append(cmd)
        if len(cmds) >= limit:
            break
    return cmds


def normalize_point(line: str) -> str:
    ln = line.strip()
    ln = ln.lstrip("-*").strip()
    ln = re.sub(r"^\d+\.?\s+", "", ln)
    ln = re.sub(r"^(EN|CN)\s*[:：]\s*", "", ln, flags=re.I)
    ln = re.sub(r"\s+", " ", ln)
    return ln


def is_good_point(line: str) -> bool:
    if len(line) < 12 or len(line) > 220:
        return False
    low = line.lower()
    if "http://" in low or "https://" in low:
        return False
    if line.count("|") >= 2:
        return False
    if low.startswith("title:"):
        return False
    if "writeup" in low and "solution" not in low and "path" not in low:
        return False
    if re.match(r"^/[^\s]+", line):
        return False
    if re.match(r"^[\w./-]+\.[a-zA-Z0-9]{1,5}$", line):
        return False
    if low.startswith("payload indicators"):
        return False
    if line.endswith(":"):
        return False
    if re.match(r"^#+\s", line):
        return False
    if re.search(r"```|<[^>]+>|&[a-z]+;", line):
        return False
    if re.search(
        r"(pre\.style|document\.|window\.|queryselector|addeventlistener)", low
    ):
        return False
    if re.search(r"\b(import|from|def|class|return|if|for|while)\b", low) and re.search(
        r"[()=;{}]", line
    ):
        return False
    letters = sum(1 for ch in line if ch.isalpha() or ("\u4e00" <= ch <= "\u9fff"))
    if letters / max(1, len(line)) < 0.3:
        return False
    return True


def extract_section_lines(text: str, hints: list[str]) -> list[str]:
    lines = text.splitlines()
    candidates: list[tuple[str, list[str]]] = []
    for i, ln in enumerate(lines):
        m = re.match(r"^#{2,3}\s*(.+)$", ln.strip())
        if not m:
            continue
        title = m.group(1).strip().lower()
        for hint in hints:
            if hint.lower() in title:
                start = i + 1
                end = len(lines)
                for j in range(start, len(lines)):
                    if re.match(r"^#{2,3}\s+", lines[j].strip()):
                        end = j
                        break
                candidates.append((title, lines[start:end]))
                break
    if not candidates:
        return []

    best: list[str] = []
    best_score = -1
    keyword_re = re.compile(
        r"(xss|sqli|ssti|ssrf|rce|uaf|heap|rop|canary|pie|libc|jinja|template|lfi|rfi|deserial|crypto|rsa|lattice|rev|decomp|stego|forensics|leak|bypass|exploit)",
        re.I,
    )
    for title, section in candidates:
        usable = [
            normalize_point(ln) for ln in section if is_good_point(normalize_point(ln))
        ]
        score = len(usable)
        keyword_hits = sum(1 for ln in usable if keyword_re.search(ln))
        score += keyword_hits * 2
        bonus = 0
        for pref in PREFERRED_SECTION_HINTS:
            if pref.lower() in title:
                bonus = 2
                break
        score += bonus
        if score > best_score:
            best_score = score
            best = section
    if best_score <= 0:
        return []
    return best


def extract_key_signals(text: str, limit: int = 4) -> list[str]:
    lines = text.splitlines()
    blocks: list[list[str]] = []
    for i, ln in enumerate(lines):
        m = re.match(r"^#{2,3}\s*(.+)$", ln.strip())
        if not m:
            continue
        title = m.group(1).strip().lower()
        if not any(hint in title for hint in KEY_SIGNAL_HINTS):
            continue
        start = i + 1
        end = len(lines)
        for j in range(start, len(lines)):
            if re.match(r"^#{2,3}\s+", lines[j].strip()):
                end = j
                break
        blocks.append(lines[start:end])

    if not blocks:
        return []

    out: list[str] = []
    for block in blocks:
        for raw in block:
            ln = normalize_point(raw)
            if not ln:
                continue
            low = ln.lower()
            if "http://" in low or "https://" in low:
                continue
            # Split short signal lists like: "HNP / Coppersmith / LLL"
            parts = re.split(r"[，,、;/|]+", ln)
            for part in parts:
                p = part.strip().strip("`")
                if not p:
                    continue
                if len(p) < 3:
                    continue
                if p not in out:
                    out.append(p)
                if len(out) >= limit:
                    return out
    return out


def extract_patterns(text: str, category: str, limit: int = 6) -> list[str]:
    patterns: list[str] = []
    signals = extract_key_signals(text, limit=min(4, limit))
    for s in signals:
        if s not in patterns:
            patterns.append(s)
        if len(patterns) >= limit:
            return patterns
    focus_lines = extract_section_lines(text, SECTION_HINTS)
    use_focus = bool(focus_lines)
    lines = focus_lines if use_focus else text.splitlines()
    lines = [normalize_point(ln) for ln in lines]

    for ln in lines:
        if not ln:
            continue
        if not is_good_point(ln):
            continue
        low = ln.lower().strip()
        if low in {
            "summary",
            "steps",
            "reproduction",
            "category",
            "target",
            "flag format",
        }:
            continue
        if re.match(r"^\d+\.", ln):
            continue
        if low.startswith("flag format"):
            continue
        if not use_focus and not re.search(
            r"(漏洞|利用|绕过|leak|overflow|format|uaf|xss|sqli|ssti|ssrf|rop|heap|解密|逆向|payload|crypto|rsa|feistel|gf\()",
            ln,
            re.I,
        ):
            continue
        if ln not in patterns:
            patterns.append(ln)
        if len(patterns) >= limit:
            return patterns

    if use_focus and len(patterns) < min(3, limit):
        extra_lines = [normalize_point(ln) for ln in text.splitlines()]
        for ln in extra_lines:
            if not ln:
                continue
            if not is_good_point(ln):
                continue
            if not re.search(
                r"(漏洞|利用|绕过|leak|overflow|format|uaf|xss|sqli|ssti|ssrf|rop|heap|解密|逆向|payload|crypto|rsa|feistel|gf\()",
                ln,
                re.I,
            ):
                continue
            if ln not in patterns:
                patterns.append(ln)
            if len(patterns) >= limit:
                return patterns

    if not patterns:
        for item in DEFAULT_PATTERN.get(category, DEFAULT_PATTERN["unknown"]):
            if item not in patterns:
                patterns.append(item)
            if len(patterns) >= limit:
                break
    return patterns


def replace_block(text: str, start: str, end: str, payload: str) -> str:
    if start in text and end in text and text.index(start) < text.index(end):
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        return f"{head}{start}\n{payload}\n{end}{tail}"
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}\n{start}\n{payload}\n{end}\n"


def ensure_writeup(project_dir: Path, source_writeup: Path | None) -> Path:
    writeup = project_dir / "writeup.md"
    if not writeup.exists():
        writeup.write_text(
            "# 题解\n\n## 摘要\n\n## 分析\n\n## 解题过程\n\n## 试错与迭代\n\n## 复现\n`python3 solve.py`\n",
            encoding="utf-8",
        )

    if source_writeup is not None and source_writeup.exists():
        src = read_text(source_writeup).strip()
        if src:
            dst = read_text(writeup)
            marker_start = "<!-- USER-WRITEUP:START -->"
            marker_end = "<!-- USER-WRITEUP:END -->"
            payload = "## User Writeup\n\n" + src
            writeup.write_text(
                replace_block(dst, marker_start, marker_end, payload), encoding="utf-8"
            )

    return writeup


def append_memory(memory_file: Path, entry: str) -> None:
    if not memory_file.exists():
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        title = memory_file.stem.replace("-", " ").title()
        memory_file.write_text(f"# {title}\n\n", encoding="utf-8")
    with memory_file.open("a", encoding="utf-8") as f:
        f.write(entry)


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def detect_source_type(source_writeup: Path | None, writeup_text: str) -> str:
    if source_writeup and source_writeup.exists():
        return "user_writeup"
    if "<!-- USER-WRITEUP:START -->" in writeup_text:
        return "user_writeup"
    return "agent_writeup"


def has_flag_file(project_dir: Path) -> bool:
    return (project_dir / "flag.txt").exists() or (project_dir / "flag").exists()


def score_confidence(
    *,
    status: str,
    category: str,
    patterns: list[str],
    commands: list[str],
    has_flag: bool,
    has_solve: bool,
) -> float:
    score = 0.25
    if status == "solved":
        score += 0.30
    else:
        score -= 0.05
    if has_flag:
        score += 0.15
    if has_solve:
        score += 0.10
    if commands:
        score += 0.10
    if len(patterns) >= 3:
        score += 0.10
    if category == "unknown":
        score -= 0.10

    defaults = set(DEFAULT_PATTERN.get(category, []))
    if patterns and all(p in defaults for p in patterns):
        score -= 0.15

    return max(0.0, min(1.0, round(score, 2)))


def load_existing_records(index_path: Path) -> list[dict]:
    if not index_path.exists():
        return []
    records: list[dict] = []
    for raw in index_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except Exception:
            continue
    return records


def append_failure_patterns(
    path: Path, now: str, project: str, category: str, patterns: list[str], note: str
) -> None:
    lines = [
        f"## {now} | {project} | {category}",
        f"- Failure note: {note}",
        "- Observed weak patterns:",
    ]
    for p in patterns[:6]:
        lines.append(f"  - {p}")
    lines.append("")
    append_memory(path, "\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote challenge writeup into reusable skill memory."
    )
    parser.add_argument(
        "--project", required=True, help="Path to challenge project directory"
    )
    parser.add_argument("--status", default="solved", choices=["solved", "unsolved"])
    parser.add_argument(
        "--source-writeup", default="", help="Path to user-provided writeup markdown"
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.55,
        help="Minimum confidence for stable memory",
    )
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    if not project_dir.exists():
        raise SystemExit(f"project not found: {project_dir}")

    source_writeup = (
        Path(args.source_writeup).resolve() if args.source_writeup else None
    )
    writeup_path = ensure_writeup(project_dir, source_writeup)
    writeup_text = read_text(writeup_path)
    category, raw_category, sub_category, category_source = load_category_meta(
        project_dir, read_text
    )
    patterns = extract_patterns(writeup_text, category)
    commands = extract_commands(writeup_text)

    auto_block = ["## Reusable Patterns"]
    for p in patterns:
        auto_block.append(f"- {p}")
    auto_block.append("")
    auto_block.append("## Useful Commands")
    if commands:
        for c in commands:
            auto_block.append(f"- `{c}`")
    else:
        auto_block.append("- (no command extracted)")

    start = "<!-- AUTO-LEARN:START -->"
    end = "<!-- AUTO-LEARN:END -->"
    updated = replace_block(writeup_text, start, end, "\n".join(auto_block))
    writeup_path.write_text(updated, encoding="utf-8")

    root_dir = project_dir.parent.parent
    shared_dir = root_dir / "shared"
    memory_root = shared_dir / "skill-memory"
    incubating_dir = memory_root / "incubating"
    index_path = memory_root / "memory_index.jsonl"

    flag_present = has_flag_file(project_dir)
    solve_present = (project_dir / "solve.py").exists()
    source_type = detect_source_type(source_writeup, updated)
    confidence = score_confidence(
        status=args.status,
        category=category,
        patterns=patterns,
        commands=commands,
        has_flag=flag_present,
        has_solve=solve_present,
    )
    reproducible = bool(flag_present and solve_present)

    project_name = project_dir.name
    project_key = normalize_project_key(project_name)

    records = load_existing_records(index_path)
    historical_validated = sum(
        1
        for r in records
        if (
            str(r.get("project_key", "")).strip() == project_key
            or normalize_project_key(str(r.get("project", "")).strip()) == project_key
        )
        and r.get("status") == "solved"
        and isinstance(r.get("confidence"), (int, float))
    )
    validated_count = historical_validated + (1 if args.status == "solved" else 0)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry_lines = [
        f"## {now} | {project_name} | key={project_key} | {category} | {args.status} | conf={confidence:.2f} | src={source_type}",
        "- Reusable points:",
    ]
    for p in patterns:
        entry_lines.append(f"  - {p}")
    if not patterns:
        entry_lines.append("  - (none)")
    entry_lines.append("- Commands:")
    if commands:
        for c in commands:
            entry_lines.append(f"  - `{c}`")
    else:
        entry_lines.append("  - (none)")
    entry_lines.append("")
    entry = "\n".join(entry_lines)

    to_stable = args.status == "solved" and confidence >= args.min_confidence

    memory_paths: list[Path] = []
    if to_stable:
        memory_paths.append(shared_dir / "skill-evolution.md")
        memory_paths.append(memory_root / f"{category}.md")
    else:
        memory_paths.append(incubating_dir / f"{category}.md")

    for mp in memory_paths:
        append_memory(mp, entry)

    if args.status == "unsolved":
        append_failure_patterns(
            memory_root / "failure-patterns.md",
            now,
            project_name,
            category,
            patterns,
            note="unsolved_or_low_confidence_path",
        )
    elif not to_stable:
        append_failure_patterns(
            memory_root / "failure-patterns.md",
            now,
            project_name,
            category,
            patterns,
            note="solved_but_low_confidence_path",
        )

    index_record = {
        "timestamp": now,
        "project": project_name,
        "project_key": project_key,
        "category": category,
        "raw_category": raw_category,
        "sub_category": sub_category,
        "source_path": category_source,
        "status": args.status,
        "confidence": confidence,
        "source_type": source_type,
        "reproducible": reproducible,
        "validated_count": validated_count,
        "has_flag_file": flag_present,
        "has_solve_py": solve_present,
        "patterns": patterns,
        "commands": commands,
        "memory_tier": "stable" if to_stable else "incubating",
        "memory_targets": [str(p.relative_to(root_dir)) for p in memory_paths],
        "last_seen": now,
    }
    append_jsonl(index_path, index_record)

    print(f"[+] Updated writeup: {writeup_path}")
    for mp in memory_paths:
        print(f"[+] Updated memory: {mp}")
    print(f"[+] Updated index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
