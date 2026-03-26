# Anti-Debug / Packer Notes

## Quick Checks
- `file <bin>` and `rabin2 -I <bin>` for format/arch.
- Look for packer strings (`UPX`, `aspack`, `mpress`, `themida`).
- `strings -n 8 <bin> | rg -i "upx|pack|protect|vm"` as a fast signal.

## If UPX
- Try `upx -d <bin>` and re-run static analysis.

## Anti-Debug Flags
- Check for `ptrace`, `syscall`, `prctl`, `seccomp` usage.
- If present, prefer patching checks in a copy and re-run.

## Strategy
- If packed, unpack first.
- If anti-debug, bypass or patch before deep dynamic tracing.
