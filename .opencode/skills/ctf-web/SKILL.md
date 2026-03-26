---
name: ctf-web
description: Web CTF exploitation workflow and tooling. Use when the core task is breaking an HTTP service, web app, API, auth flow, or browser/server trust boundary to obtain the flag. Do not use when the main blocker is cryptanalysis, pure reversing, or local artifact extraction without meaningful web behavior.
---

# Web CTF Workflow

## Use This Skill When
- The target is a website, API, web socket, admin panel, report flow, or browser-mediated workflow.
- The core blocker is identifying and exploiting a web vulnerability or logic flaw.
- Source code, JS bundles, or endpoint behavior are central evidence.

## Do Not Use This Skill When
- The challenge is mostly local decoding, binary reversing, or stego.
- The main blocker is cryptanalysis rather than the web attack surface.
- The HTTP service is only a thin transport and the real task is pwn or rev.

## Session Start
1. Identify base URL, provided source/attachments, auth model, and expected flag format.
2. If source code or a source link is provided, read that before broad probing.
3. Create exactly 4 todos:
   - `map target surface from source, HTML, and JS`
   - `identify the strongest likely vuln class`
   - `collect one concrete exploitable signal`
   - `build a minimal reproducible exploit path`
4. Do not start heavy fuzzing until the first two todos are complete.
5. If no clear vuln signal exists after basic triage, read `references/decision-tree.md`.

## Todo Policy
- Todos must be concrete. Good examples:
  - `decode Flask session and extract object ids`
  - `scan bundled JS for hidden API routes`
  - `test stored trigger in report flow`
  - `verify IDOR on ticket endpoint`
- Do not create todos like `try more payloads` or `continue testing`.
- Keep at most 3 active todos at once.
- Do not open `final exploit` or `final flag retrieval` until there is one concrete signal.

## Branch Control
- If the same vuln branch is adjusted 3 times with no new signal, close that branch todo and switch representation:
  - payload tuning -> state machine
  - single request -> identity/object graph
  - page view -> JS/API asset chain
- Once a minimal PoC confirms the vuln class, close broad recon todos and focus on exploit plus verification.
- If the current branch works but does not reach the flag, write one new todo that names the missing capability before opening another branch.

## High-Value Special Cases
- Admin/report/contact flows: treat as high-priority stored-execution candidates.
- Readable client sessions: decode them early and mine identifiers before guessing IDs.
- JSONP/script-loadable endpoints: test them immediately when callback behavior is visible.
- Same-series challenges: review prior series artifacts before opening new fuzz branches.

## Read References When
- Read `references/decision-tree.md` when no clear vuln signal exists.
- Read `references/server-side.md` or `references/server-side-advanced.md` once the bug is clearly server-side.
- Read `references/client-side.md` for DOM, JS, CSP, postMessage, or browser-side paths.
- Read `references/auth-and-access.md`, `references/auth-jwt.md`, or `references/auth-infra.md` for auth, tenant, and identity flaws.
- Read `references/checklist.md` only when stuck, not as the first step.
- Read `references/web-branches.md` only after the vuln family is narrowed.

## Output
- Minimal reproduction steps.
- Exploit script or replay command sequence.
- Short evidence summary tying the exploit to the flag path.
