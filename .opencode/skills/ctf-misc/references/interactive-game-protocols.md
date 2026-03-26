# Interactive Game/Protocol CTF Checklist

## Spec Discipline
- Treat the server as the spec; if the statement says A but the server enforces B, follow B.
- Log full transcripts for later diffing; parse prompts/tokens explicitly.

## Minimal Closed Loop First
- Implement a “dumb but correct” client: connect, read prompt, send one valid command, repeat.
- Only after the loop is stable: add solving logic, caching, and performance.

## Commit-Reveal Patterns
- Match exact hashing input format (delimiters, ordering, ASCII vs bytes).
- Match exact command syntax (e.g., `COMMIT <hex>`, `REVEAL i k nonce`).
- Respect ordering: don’t pre-send `REVEAL` unless the server accepts it.

## Game-State Legality Guards
- Always validate a move locally before sending:
  - indices in range
  - take within limits and <= pile size
  - rule constraints (e.g., total strictly decreases)
  - caps/clamps (e.g., `MAX_VAL`) applied exactly as the server does

## Noisy/Randomized Rounds
- Assume some rounds can be unwinnable by construction; implement retry/reconnect strategy.
- Prefer strategies that minimize time per attempt; avoid heavy decoding if plaintext state appears.

## Anti-Decoy Heuristic
- If the server eventually prints plaintext `STATE`, use it.
- Treat probe/oracle/cipher layers as decoys until proven necessary.
