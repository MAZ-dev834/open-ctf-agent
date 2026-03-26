---
name: ctf-rev
description: Reverse engineering workflow and tooling. Use when the core blocker is recovering program logic, validation rules, transforms, or hidden constants from binaries, bytecode, firmware, or obfuscated programs. Do not use when the main task is exploit development, pure cryptanalysis, or local artifact extraction without meaningful program analysis.
---

# Reverse Engineering CTF Workflow

## Use This Skill When
- The challenge requires understanding a binary, script VM, bytecode, or validation routine.
- The core blocker is reconstructing input-to-output logic, constraints, or hidden constants.
- A solver must be derived from static analysis or light dynamic confirmation.

## Do Not Use This Skill When
- The real blocker is memory corruption or exploit stabilization.
- The task is mainly a crypto attack rather than program-logic recovery.
- The challenge is only a file extraction or decoding pipeline.

## Session Start
1. Identify target file types, architecture, runtime, and expected flag format.
2. Classify the solve shape before deep reading:
   - verifier
   - decryptor/decoder
   - VM/bytecode
   - state machine
   - environment-dependent logic
3. Create exactly 4 todos:
   - `inventory binaries, format signals, and runtime`
   - `identify the real compare site or verdict path`
   - `recover one concrete transform or constraint`
   - `build a minimal verified reimplementation`
4. Do not start deep decompile wandering before the compare/verdict todo is active.
5. Prefer tracing from compare/check sites back to inputs over reading from `main` downward.

## Todo Policy
- Todos must describe a falsifiable stage. Good examples:
  - `locate strcmp/memcmp argument sources`
  - `recover xor key schedule from validation loop`
  - `confirm VM opcode semantics for branch opcodes`
  - `replay one round function in Python`
- Do not create vague todos such as `reverse binary` or `understand program`.
- Keep at most 3 active todos at once.
- Do not create `final flag solve` until one transform or constraint is reproduced outside the target.

## Constraint-First Rule
- Prefer this order:
  - verdict location
  - data flow into verdict
  - one concrete transform
  - full constraint/model recovery
  - final solver
- If decompile detail increases but constraints do not, switch representation:
  - control flow -> data flow
  - source listing -> compare-site backtrace
  - static reading -> one breakpoint probe
- Use runtime debugging only to resolve uncertainty, not as the default main path.

## Branch Control
- If one branch produces no new constraint, constant, or state transition after 3 iterations, close that todo.
- Allowed branch switches:
  - decompiler view -> strings/constants view
  - strings/constants -> compare-site tracing
  - compare-site tracing -> minimal dynamic probe
  - dynamic probe -> reimplementation/model
- If the challenge clearly becomes crypto-heavy or exploit-heavy, hand that blocker to `ctf-crypto` or `ctf-pwn` and keep `ctf-rev` as the owner only if logic recovery remains primary.

## Reimplementation Rule
- Any emulator, decoder, or solver must be verified against the original target on the same sample input as soon as it exists.
- Do not build downstream solving on an unverified reimplementation.
- Keep one main solver path. Extend the same `solve.py` instead of creating `solve2.py`, `tmp_solve.py`, or parallel variants.

## Read References When
- Read `references/decision-tree.md` when the solve shape is unclear.
- Read `references/checklist.md` for static/dynamic coverage once the primary branch is chosen.
- Read `references/anti-debug.md` only when protections or anti-analysis behavior are suspected.
- Read `references/patterns.md`, `references/patterns-ctf.md`, or `references/patterns-ctf-2.md` after the transform family is narrowed.
- Read `references/languages.md` or `references/lj_tools.md` only when the runtime/language demands it.

## Output
- Minimal verified solver or reimplementation.
- Replay steps showing equivalence between target behavior and recovered logic.
- Final flag candidate plus the key recovered constraint or transform chain.
