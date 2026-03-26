---
name: ctf-misc
description: Misc workflow and tooling. Use when the core task is chained decoding, file/container extraction, protocol puzzles, jail escapes, esolangs, RF/SDR, or odd game/VM logic that does not cleanly belong to crypto, pwn, rev, or OSINT. Do not use misc as the default bucket when a stronger specialist fit exists.
---

# Misc CTF Workflow

## Use This Skill When
- The challenge is mainly a data pipeline, parser chain, archive/container puzzle, jail, or protocol/game interaction.
- The hard part is building a reproducible transformation chain.
- The task spans several weak signals but no stronger specialist clearly owns it.

## Do Not Use This Skill When
- The core blocker is a binary exploit.
- The main task is reverse engineering a program.
- The central challenge is cryptanalysis.
- The answer depends mainly on public-source OSINT pivots.

## Session Start
1. Classify the challenge into one primary representation:
   - encoding/container
   - jail
   - protocol/game
   - image/audio/media
   - VM/esolang
2. Create exactly 4 todos:
   - `inventory artifact and format signals`
   - `choose one primary representation`
   - `extract the first concrete signal`
   - `build a reproducible transformation pipeline`
3. Do not open multiple representation branches before the first concrete signal appears.
4. If the challenge includes images or media, use local tooling first; OCR is only a helper, not the default main path.

## Todo Policy
- Good todo examples:
  - `map nested archive and embedded file types`
  - `decode stage-1 wrapper into raw bytes`
  - `render HID strokes for each button state`
  - `build minimal protocol replay loop`
- Do not create vague todos such as `try more transforms` or `keep decoding`.
- Keep at most 3 active todos at once.
- If one representation stalls, close its todo before opening the next.

## Primary Representation Rule
- Work one main representation at a time.
- Allowed switches:
  - bytes -> container structure
  - structure -> protocol behavior
  - protocol -> search/constraint model
  - image -> diff/crop/enhance
- If the challenge clearly becomes crypto/rev/pwn/osint, misc should become auxiliary rather than staying primary.

## Branch Control
- If the same representation yields no new signal after 3 iterations, switch representation and open a new todo with an explicit success signal.
- For image-heavy tasks:
  - OCR cannot be the only main branch.
  - Prefer visible structure, diff, crop, threshold, and local transforms before repeated OCR tuning.
- For interactive puzzles:
  - build the minimal I/O loop first
  - then solve the logic
  - then automate verification

## Read References When
- Read `references/decision-tree.md` when the primary representation is unclear.
- Read `references/encodings.md` for wrappers, classic transforms, and byte-level pipelines.
- Read `references/interactive-game-protocols.md` for stateful services and puzzle protocols.
- Read `references/pyjails.md` or `references/bashjails.md` for jail challenges.
- Read `references/rf-sdr.md` for signal/radio tasks.
- Read `references/checklist.md` only when stuck.

## Output
- Reproducible pipeline or interaction script.
- Minimal command list showing each transformation stage.
- The strongest concrete signal or final flag candidate.
