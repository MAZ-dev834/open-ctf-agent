# Interactive Anti-AI Crypto Playbook

## Use This When
- The challenge has noisy oracle outputs, strict query budgets, server lockout/cooldown, PoW gates, or staged protocol unlock.

## 1) Protocol Engineering Before Math
- Build a resilient client first:
  - pacing + jitter
  - retry with bounded backoff
  - reconnect flow with state resync checkpoints
  - hard caps for per-stage and per-session queries
- If the script "randomly breaks", verify timeout/lockout behavior before touching solver logic.

## 2) Sequential Decision Instead of Majority Vote
- Treat each response as probabilistic evidence.
- Keep per-candidate score/posterior and update after every query.
- Use two thresholds:
  - accept: one candidate sufficiently dominates
  - drop: low-probability candidates removed early
- Reduce alphabet aggressively with known format constraints (hex/base64/prefix).

## 3) Budget-Driven Strategy
- Pre-allocate budget for handshake, probing, narrowing, and final verification.
- Abort early if expected remaining cost exceeds remaining budget.
- Prefer high-information probes over symmetric brute-force probing.
- For decaying sessions, prefer controlled short runs over one long unconstrained run.

## 4) Observability and Failure Signatures
- Minimum logs:
  - timestamp, command/action, response class
  - query count, candidate count
  - posterior gap (best vs second-best)
  - disconnect time and reconnect delay
- Classify failures:
  - fixed-interval rejects -> rate limit
  - temporary ban window -> cooldown lockout
  - hard lifetime cutoff -> container/session timeout
  - stable protocol + wrong output -> crypto/model mismatch

## 5) Deliverables for Reuse
- Keep a compact tuning note with:
  - budget table
  - threshold policy
  - pruning timeline
  - known failure modes and mitigations
