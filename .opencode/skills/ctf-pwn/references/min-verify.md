# Minimal Exploit Verification

Goal: avoid full exploit runs until each primitive is confirmed.

## Stages
1. Crash control
   - Confirm controllable input reaches crash point.
2. Write primitive
   - Show you can overwrite 1 byte or pointer reliably.
3. Leak primitive
   - Leak 1 stable pointer (GOT, stack, libc).
4. Control transfer
   - Prove hijack (hook/ROP/ret2libc) works locally.
5. Remote validation
   - Re-run only after steps 1-4 are stable.

## Rules
- Do not re-run identical commands without a hypothesis change.
- Use `scripts/core/ctf_repeat_guard.sh` for retries.
