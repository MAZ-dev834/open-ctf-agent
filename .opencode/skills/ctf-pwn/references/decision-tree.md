# Pwn Decision Tree

## Step 1: Binary profile
Run `pwn_profile.py`. Key outputs:
- Protections: NX / PIE / canary / RELRO / FORTIFY
- Architecture: x86-64 / ARM / MIPS / 32-bit
- Linked: static / dynamic (libc version)
- Interaction: local binary / network service / docker

## Step 2: First primitive direction

```
stdin/stdout controlled? ─── YES ─── format string? ─── YES ── fmt exploit path
                                    │
                                    └── buffer overflow? ─── YES ─── overflow size
                                        │                              > 8 bytes? ── ROP
                                        │                              exactly ret? ── ret2win
                                        └── heap operations? ─── YES ── heap path (see below)

network / protocol service? ─── state machine / auth ── protocol-state path
```

## Step 3: Stack path
1. Find offset: cyclic pattern or manual calc
2. Canary? → leak canary first (fmt string, partial overwrite, side-channel)
3. PIE? → leak text base (puts/printf leak, fmt %p)
4. NX on? → ROP chain; NX off → shellcode
5. ROP: ret2libc (puts→system), one_gadget, SROP, sigreturn

## Step 4: Heap path
1. Identify allocator: ptmalloc2 / tcmalloc / jemalloc / custom
2. Primitive: UAF / double-free / off-by-one / off-by-null / type confusion
3. Target: tcache poison → arbitrary alloc → GOT/hook overwrite
4. Glibc ≥2.32: safe-linking bypass needed for tcache

## Step 5: Format string path
1. Offset to format string on stack: `%p %p ...` or `pwn.fmtstr_offset`
2. Leak: canary / libc base / stack addr
3. Write: `%n` to GOT entry (x86) or stack ret addr (x64 positional)

## Step 6: Protocol-state path
1. Map state machine: what inputs trigger each transition
2. Find inconsistency: TOCTOU, length confusion, parser differential
3. Primitive: usually memory corruption or auth bypass

## Libc policy
- Provided → align immediately
- Not provided → use DynELF or libc.rip from leaked offsets
- Remote → run `pwn_remote_libc_check.sh` before final exploit

## Escalation order
local crash → offset → leak → control rip → shell → remote stabilize
