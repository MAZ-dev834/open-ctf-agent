# Blind FMT Playbook

## When to use
Use when stdout is redirected to `/dev/null` (or closed) and only stderr remains on the socket.

## Hard Rules
- Unblind first by writing `stdout->_fileno = 2` (stderr) via `%hhn`.
- Do not brute-force libc base widely. Leak libc/stack to confirm base first.

## Minimal Steps
1. Confirm blind condition: `printf(user)` after stdout redirection.
2. Find format-arg index by pointer differential test (0 vs 0x4141 crash).
3. Unblind: write `_IO_2_1_stdout_->_fileno = 2`.
4. Leak stack pointer(s) with `%p` to locate flag buffer or return address.
5. Use `%s` with computed pointer to print flag.

## Notes
- If remote libc is unknown, look for run scripts/Docker to confirm libc/ld.
- Save verbose outputs using `scripts/core/ctf_throttle.sh --save ./workspace/active/<challenge>/logs/...`.
