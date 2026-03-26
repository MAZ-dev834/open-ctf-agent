---
name: ctf-pwn
description: Binary exploitation workflow and tooling. Use when the core task is memory corruption, sandbox escape, exploit primitive construction, or remote/local binary exploitation. Do not use when the main blocker is pure reverse engineering, generic decoding, or protocol scripting without exploitation.
---

# Pwn CTF Workflow

## Use This Skill When
- A local ELF/PE/service must be exploited to obtain the flag.
- The core blocker is finding or stabilizing a memory-corruption primitive.
- Remote interaction exists, but exploitation is still the main task.

## Do Not Use This Skill When
- The binary only needs reverse engineering to derive an input or flag.
- The service is a protocol puzzle without memory-safety or sandbox implications.
- The challenge is primarily crypto, OSINT, or forensics.

## Session Start
1. Inventory the binary, loader, libc, and architecture.
2. Identify the input surface and execution model before writing exploit code.
3. Create exactly 4 todos:
   - `inventory binary, libs, and protections`
   - `identify input surface and parser boundaries`
   - `triage bug class with bounded probes`
   - `obtain one stable exploit primitive`
4. Do not open a `final exploit` todo until the bug class and one primitive are confirmed.
5. Prefer local proof first; move to remote only after the local path is understood.

## Todo Policy
- Todos must name a real stage. Good examples:
  - `confirm protections with pwn_profile`
  - `locate menu handler and parser loop`
  - `prove controlled read primitive`
  - `verify remote libc assumptions`
- Do not create vague todos such as `work on exploit` or `adjust payload`.
- Keep at most 3 active todos at once.
- If one primitive fails, open the next todo around a different primitive, not another offset tweak.

## Primitive-First Rule
- Prefer this order:
  - controlled read
  - controlled write
  - leak
  - PC control
  - full exploit chain
- Do not jump directly to one_gadget or a long ROP chain without evidence that simpler primitives are insufficient.
- For blind fmt or output-starved targets, first unblind or restore observability before large brute force.

## Branch Control
- If the same exploit family is adjusted 3 times with only offset/gadget/timing tweaks and the crash shape does not change, close that branch todo.
- When switching branches, define the new success signal explicitly:
  - stable leak
  - arbitrary write
  - controlled return
  - sandbox breakout foothold
- Kernel, sandbox, and blind-fmt branches should only open after ordinary userland branches are ruled out or disproven.

## Read References When
- Read `references/decision-tree.md` when bug class or exploit direction is unclear.
- Read `references/overflow-basics.md`, `references/format-string.md`, and `references/rop-and-shellcode.md` for common userland paths.
- Read `references/min-verify.md` when tightening exploit validation.
- Read `references/log-discipline.md` before noisy gdb/trace sessions.
- Read advanced references only after the relevant path is proven:
  - `references/blind-fmt.md`
  - `references/sandbox-escape.md`
  - `references/kernel.md`
  - `references/kernel-techniques.md`
  - `references/kernel-bypass.md`

## Output
- Stable exploit path or minimal primitive PoC.
- Replay steps for local and remote.
- Short note on required assumptions such as libc, kernel, or timing behavior.
