---
name: ctf-crypto
description: Cryptography challenge workflow and tooling. Use when the core blocker is identifying a primitive, recovering parameters, exploiting an oracle, or solving algebraic/number-theoretic structure. Do not use when the task is mainly generic decoding, binary reversing, or exploit development.
---

# Crypto CTF Workflow

## Use This Skill When
- The challenge centers on encryption, signatures, hashes, PRNGs, modular arithmetic, lattices, or protocol leakage.
- The main blocker is turning observed behavior into equations, capabilities, or attackable structure.
- A solver depends on algebraic modeling, parameter recovery, or query strategy.

## Do Not Use This Skill When
- The hard part is only parsing, decoding, or extracting files.
- The task is mainly recovering program logic from a binary.
- The service is primarily a web or pwn bug, with crypto only incidental.

## Session Start
1. Identify the likely primitive, parameters, attacker capability, and expected flag/output form.
2. Write down the observation model before choosing an attack:
   - what is known
   - what is controllable
   - what is leaked
   - what is rate-limited or noisy
3. Create exactly 4 todos:
   - `identify primitive and parameter surface`
   - `write capability model and unknown variables`
   - `recover one concrete equation, leak, or distinguisher`
   - `build a verified solver for the strongest attack path`
4. Do not start parameter grinding before the capability-model todo is complete.
5. If the challenge is interactive, stabilize protocol behavior before serious inference.

## Todo Policy
- Todos must name a concrete attack stage. Good examples:
  - `factor modulus relation from shared prime signal`
  - `derive LCG equations from three outputs`
  - `measure oracle noise and acceptance threshold`
  - `verify AES mode hypothesis on known plaintext block`
- Do not create vague todos such as `try crypto attacks` or `bruteforce more`.
- Keep at most 3 active todos at once.
- Do not create `final flag recovery` until one independent equation, leak, or distinguisher is confirmed.

## Modeling Rule
- Prefer this order:
  - primitive identification
  - capability model
  - one independent equation/leak/distinguisher
  - reduced unknown space
  - final recovery
- If repeated attack tuning changes only bounds, seeds, or thresholds without adding independent information, close that branch todo.
- For interactive/noisy tasks, prefer:
  - stabilize client behavior
  - estimate budget/noise
  - sequential candidate pruning
  - final algebraic recovery

## Branch Control
- If one attack family yields no new equation, leakage class, or search-space reduction after 3 iterations, close that branch todo and switch representation:
  - primitive guess -> capability model
  - direct solve -> modular relation/invariant search
  - exact algebra -> statistical/distinguisher path
  - full-space attack -> staged pruning
- If the core blocker becomes code recovery rather than math, hand that branch to `ctf-rev` and keep crypto auxiliary unless the algebra still dominates.

## Verification Rule
- Any reimplemented primitive, oracle wrapper, or solver step must be checked against original behavior on the same sample input/output pair before downstream use.
- Keep one main solver path in the challenge workspace; extend it instead of creating parallel versions.
- Use standard helper solvers only to narrow the branch, not to replace reasoning about fit.

## Read References When
- Read `references/decision-tree.md` when the primitive or attack family is unclear.
- Read `references/checklist.md` after the primitive family is narrowed.
- Read `references/rsa-attacks.md`, `references/ecc-attacks.md`, `references/prng.md`, `references/modern-ciphers.md`, or `references/classic-ciphers.md` only after the primitive family is identified.
- Read `references/lattice-lll.md` when partial leaks or small-root patterns appear.
- Read `references/interactive-anti-ai.md` when the oracle is noisy, gated, rate-limited, or staged.
- Read advanced references only after there is evidence they match the challenge structure.

## Output
- Minimal verified solver.
- Short note describing the capability model, key equation/leak, and why the chosen attack works.
- Final flag candidate and replay steps.
