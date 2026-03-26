# Rev Decision Tree

## Step 1: File triage
Run `rev_quick_scan.py`. Key outputs:
- Format: ELF / PE / Mach-O / bytecode / script / WASM / custom
- Packer: UPX / custom (entropy > 7.2 = likely packed)
- Language: C / C++ / Go / Rust / Python (PyInstaller) / .NET / Java / Kotlin

## Step 2: Locate verification skeleton

Goal: find `input → transform → compare`. Not full program logic — just the check path.

```
Binary has symbols? ─── YES ── find main/check/verify/validate → trace forward
                     │
                     └── NO ── strings for flag prefix (e.g. "ACSC{") → xref → trace backward
                               └── no strings ── entropy scan → find compare/memcmp/strcmp
```

## Step 3: Choose analysis lane

```
Static decompile readable? ─── YES ─── reconstruct logic in solve.py
                            │
                            └── NO ─── VM / JIT / heavy obfuscation?
                                        │
                                       YES ── dynamic trace (strace/ltrace/qemu) first
                                        │     then symbolic slice
                                        └── NO ── angr/z3 symbolic solving
```

## Step 4: Transform classes (common patterns)
- XOR stream: look for repeating byte XOR with fixed key; key length = GCD of patterns
- Substitution: S-box lookup; reverse the table
- Permutation / shuffle: track index mapping statically or via trace
- Multi-round: unroll rounds in reverse order
- Custom cipher: identify round function; implement inverse
- VM bytecode: disassemble opcode dispatch; build opcode table; lift to Python

## Step 5: Solving strategy per transform
| Transform | Strategy |
|-----------|----------|
| XOR fixed key | brute key from flag prefix |
| AES/DES (known algo) | find key in memory/binary |
| RSA-like math | recover parameters from static constants |
| Constraint check | angr / z3 with unconstrained [0x00-0xFF] |
| Output comparison | z3 / symbolic execution on comparison path |
| Brute-forceable (≤32 bits) | batch brute via PyPy or C extension |

## Step 6: Verification (mandatory)
After implementing any reimplementation:
1. Run original binary with fixed test input → record output
2. Run reimplementation with same input → assert match
If mismatch for deterministic input: stop and fix before proceeding.

## Escalation order
strings/xref → decompile → trace → symbolic → brute
