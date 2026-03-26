---
name: ctf-osint
description: OSINT workflow for CTF challenges involving public sources, social media, geolocation, DNS, archives, and reverse image search. Use when the core blocker is identifying, locating, or attributing people, places, objects, accounts, domains, or events from public evidence. Do not use when the task is mostly local file decoding, binary reversing, or generic stego without a public-source pivot.
---

# OSINT CTF Workflow

## Use This Skill When
- The answer must come from public web sources, maps, archives, registries, or social platforms.
- Reverse image search, geolocation, metadata correlation, or identity attribution is the main blocker.
- The challenge includes screenshots, photos, handles, domains, usernames, or timeline clues.

## Do Not Use This Skill When
- The task is mainly local file carving, binary reversing, crypto solving, or exploit development.
- The challenge only looks like OSINT but the actual solve path is a local media/stego pipeline.
- A public-source pivot is optional rather than required.

## Session Start
1. Extract the target, question, platform, time window, region, and expected flag format.
2. Normalize explicit clues into a short scratch list: names, handles, domains, landmarks, timestamps, file metadata, visible text.
3. Before broad search, create exactly 4 todos:
   - `normalize clues into searchable pivots`
   - `write query plan with primary and fallback searches`
   - `collect candidate sources with timestamps`
   - `build evidence chain for the strongest candidate`
4. Do not run wide web searches before the query-plan todo is complete.
5. Prefer clue/entity/platform queries over challenge-title or event-title queries. Title/event queries are only for official hints, mirrors, or series context.

## Todo Policy
- Todos must be executable and closeable. Good examples:
  - `reverse-search the cropped skyline image`
  - `search handle variants on Bluesky and X`
  - `confirm domain ownership via WHOIS and archive snapshots`
  - `build evidence chain for candidate location`
- Do not create vague todos such as `continue OSINT` or `search more`.
- Keep at most 3 active todos at once.
- Do not create `final answer` until the evidence-chain todo is complete.

## Evidence Chain
- Every candidate conclusion must record:
  - source URL
  - observed timestamp or archive date
  - key fact extracted from that source
  - which challenge clue it explains
- Require either:
  - two independent sources, or
  - one primary source plus one strong corroborating source
- If sources conflict, open a new todo to resolve the conflict instead of forcing an answer.

## Branch Control
- If one search path yields no new entity, source, or narrowing signal after 3 iterations, close that branch todo and switch representation:
  - text -> image
  - image -> map
  - map -> archive
  - archive -> social
- If the path clearly becomes a local artifact-analysis task, keep OSINT as the main skill only if the public-source pivot is still required. Otherwise hand the local analysis to `ctf-forensics` or `ctf-misc`.
- When a candidate becomes clearly strongest, close weaker branch todos and focus on verification.

## Read References When
- Read `references/social-media.md` for platform-specific pivots, handle enumeration, and timeline checks.
- Read `references/geolocation-and-media.md` for reverse image search, geolocation, and media verification.
- Read `references/web-and-dns.md` for DNS, Wayback, WHOIS, certificate, and domain pivots.

## Output
- Final answer or flag candidate.
- Minimal evidence chain with source URLs and timestamps.
- Short replayable query summary for writeup use.
