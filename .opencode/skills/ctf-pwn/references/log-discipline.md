# Pwn Token Discipline

## Goal
Keep context small and avoid flooding the model with low-value logs.

## Rules
- Do not dump full `strace` outputs into context.
- If `strace` is needed, use filters and bounded output.
- Prefer targeted commands with `head`, `tail`, `sed -n`, `rg -n -m`.
- Use `scripts/core/ctf_throttle.sh` for any verbose command output.
- Use `scripts/core/ctf_repeat_guard.sh --note "<reason>" -- <cmd...>` when re-running the same command.

## Recommended patterns
- `strace -e trace=read,write,openat -s 80 -o trace.log <cmd>`
- `tail -n 120 trace.log`
- `rg -n -m 40 "read\(|write\(|openat\(" trace.log`
- `objdump ... | sed -n '/<main>:/,/<.*>:/p' | head -n 160`
- `scripts/core/ctf_throttle.sh --save ./workspace/active/<challenge>/logs/run.log -- <cmd...>`

## GDB first for behavior
Use non-interactive bounded gdb before heavy tracing:
- `gdb -q <bin> -ex 'set pagination off' -ex 'b main' -ex 'run' -ex 'bt' -ex 'info registers' -ex 'quit'`

## Do-not list
- `cat trace.log` on large logs.
- unconstrained `strings`/`objdump` output.
- repeated identical exploit runs without hypothesis update.
- `LOG=debug <cmd>` without `ctf_throttle.sh`.
