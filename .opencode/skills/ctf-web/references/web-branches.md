# Web Exploit Branches

Use this when the vuln class is identified to avoid random fuzzing.

## Auth / Session
- Check auth boundary: unauth endpoints, role escalation, IDOR.
- Test cookie/header assumptions (e.g., `X-Forwarded-For`, `X-Original-URL`).
- Replay with minimal requests; automate once confirmed.

## Command Injection / RCE
- Look for shell-like parameters and dangerous concatenation in source.
- Try minimal probes (`;id`, `|id`, `&&id`) and confirm by side effects.

## SSRF
- Probe internal metadata endpoints.
- Try URL schemes: `http`, `gopher`, `file` (if allowed).
- Verify DNS rebinding or whitelist bypass patterns.

## SSTI
- Identify template engine by error messages or syntax.
- Use safe probes (`{{7*7}}`, `${7*7}`), then pivot to read secrets.

## XXE
- Check XML parsers and `DOCTYPE` handling.
- Use out-of-band entity or local file read as confirmation.

## Deserialization
- Look for base64/serialized blobs in cookies/params.
- Verify gadget chain in provided source before exploitation.

## File Upload
- Confirm server-side validation.
- Check double extensions and content-type mismatch.
- Search for upload path disclosure; try LFI to read uploads.

## Path Traversal / LFI
- Canonicalize paths: `..`, encoded `..%2f`, double-encode.
- Verify include/require behavior in source if present.

## SQLi
- Identify parameter sinks and DB error traces.
- Prefer minimal boolean/time-based proof before automation.

## CSRF
- Check state-changing endpoints lacking CSRF tokens or SameSite protections.
- Validate with cross-origin form or fetch proof.

## CORS
- Test `Access-Control-Allow-Origin` reflection with credentials.
- Confirm data exfil is possible, not just header misconfig.

## JWT / OAuth
- Inspect alg/claims validation and audience/issuer checks.
- Test weak secrets only when evidence exists.

## Cache Poisoning / Host Header
- Look for cache key variations and unkeyed headers.
- Test `Host`, `X-Forwarded-Host`, `X-Original-Host` impact.

## Request Smuggling / Desync
- Only attempt with proxy/back-end mismatch evidence.
- Use minimal CL/TE desync probes to confirm.

## Prototype Pollution (JS)
- Look for deep merge or unsafe object assignment in JS.
- Confirm by polluting `__proto__` and observing behavior.

## GraphQL
- Check for `/graphql` endpoint and introspection.
- Test for auth bypass via query selection or nested fields.

## WebSocket / Socket.IO
- Inspect upgrade endpoints and message schemas.
- Test auth enforcement on subscribe/send actions.

## Open Redirect / CRLF
- Identify redirect parameters and validate URL validation.
- Test CRLF only when response headers are reflected.

## Race / Logic / TOCTOU
- Identify multi-step flows with non-atomic checks.
- Use parallel requests to confirm race conditions.
