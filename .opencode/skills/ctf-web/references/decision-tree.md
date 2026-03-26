# Web Exploit Decision Tree

## 1) Start From Observables
- If auth exists and role differences are visible: run auth/IDOR branch first.
- If user input is reflected or rendered: run XSS/SSTI branch.
- If server fetches URLs or files: run SSRF/LFI/path traversal branch.
- If upload exists: run upload branch.
- If DB-like error patterns appear: run SQL/NoSQL branch.
- If XML is accepted: run XXE branch.
- If CORS headers look permissive: run CORS branch.
- If redirect params appear: run open-redirect/CRLF branch.

## 2) Auth and Access Control
- Test IDOR by incrementing resource IDs.
- Reuse low-priv session on admin endpoints.
- Tamper JWT algorithm/header only when signature validation behavior is unclear.
- Validate by accessing data from another user/account.

## 3) Injection
- SQLi smoke test: `'` then time/error-based payloads.
- Command injection smoke test: `;id` or `|id` in shell-facing params.
- SSTI smoke test: `{{7*7}}`, `${7*7}` depending on template engine clues.
- Reject false positives by requiring side effects or deterministic response deltas.

## 4) File and Path
- Upload bypass checks: extension polyglot, MIME spoof, content validation gaps.
- Traversal checks: `../` variants and URL-encoded traversal.
- LFI checks: app config/log/session paths.
- Verify with file content leakage, not just status code changes.

## 5) SSRF
- Try loopback and private ranges only if challenge scope allows.
- Confirm SSRF with response body timing/status/metadata fingerprint.
- Escalate to internal service discovery only after positive SSRF signal.

## 6) JSON / JS
- If complex JSON is accepted, check for prototype pollution.
- If `/graphql` exists, test introspection and auth on nested fields.
- If WebSocket upgrades exist, validate auth on subscribe/send.

## 6) Exploit Selection Rule
- Pick branch with strongest evidence first.
- Keep one deterministic exploit script per confirmed vuln.
- Stop broad fuzzing once a working exploit path exists.

## 7) Flag Validation
- Match exact flag format.
- Replay exploit from clean session.
- Save requests and script under `./workspace/active/<challenge>/`.
