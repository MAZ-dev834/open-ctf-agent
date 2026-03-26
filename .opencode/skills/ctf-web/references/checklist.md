# Web CTF Checklist

## Fast Recon
- Run `scripts/core/web_preflight.sh` first and fix missing required tools.
- Confirm base URL, auth, and any provided creds.
- Capture `robots.txt`, `sitemap.xml`, and common well-known paths.
- Check response headers for stack hints.

## Endpoint Discovery
- Use `ffuf` or `dirsearch` to discover routes and files.
- Enumerate parameters and methods (`GET`, `POST`, `PUT`, `DELETE`).
- Look for hidden API versions (`/api/v1`, `/v2`).

## Common Vuln Passes
- **Auth**: session fixation, JWT tamper, weak password reset, IDOR.
- **Injection**: SQL/NoSQL, command injection, SSTI, LDAP.
- **File**: upload bypass, LFI/RFI, path traversal, file inclusion.
- **SSRF**: metadata IPs, internal admin endpoints.
- **XSS**: stored/reflected, CSP bypass, DOM sinks.
- **Deserialization**: framework-specific gadgets.
- **XXE**: XML parsers, external entity expansion, OOB confirmation.
- **CSRF**: missing/weak CSRF tokens, SameSite/Origin checks.
- **CORS**: permissive origins with credentials.
- **JWT/OAuth**: alg confusion, claim validation, weak client secrets.
- **Cache/Host**: host header injection, cache poisoning.
- **Desync**: request smuggling (CL/TE mismatch).
- **Prototype Pollution**: unsafe deep merge in JS.
- **GraphQL**: introspection, auth bypass via field selection.
- **WebSocket**: auth enforcement on subscribe/send.
- **Race/Logic**: TOCTOU, multi-step workflow gaps.

## Source Review
- Grep for secrets, JWT keys, debug routes, admin toggles.
- Trace auth/authorization checks for IDOR.
- Map request handlers to filesystem paths.

## Exploit Hygiene
- Reproduce with a minimal script.
- Keep a clean PoC and a reliable exploit.
- Validate flag format by replay.

## Abstract Tactics
- Define the shortest win path first and prioritize actions that change target state.
- Convert narrative hints into testable hypotheses instead of treating them as flavor text.
- Test state mutation even when there is no direct reflection in the response.
- Treat every input boundary as potential interpretation (template/render/eval/deserialize/map).
- Stabilize brittle payloads first (wrap, simplify, split steps) before changing exploit direction.
- Timebox dead-end branches and switch attack surface when no new evidence appears.
- Exploit first, explain later; secure the flag path before full root-cause deep dive.
