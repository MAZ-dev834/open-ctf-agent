# Crypto Decision Tree

## Step 1: Identify primitive
Run `crypto_quick_scan.py`. Key signals:
- RSA: n, e, c (decimal/hex integers)
- AES/block cipher: ciphertext length multiple of 16, IV present?
- Stream cipher / XOR: single key repeated
- Hash: fixed-length output, collision/preimage challenge
- PRNG: sequential outputs, seed recovery
- ECC: curve parameters, point operations
- Custom/unknown: large prime fields, unusual recurrences

## Step 2: Identify attack surface

```
RSA ──── small e (e=3)? → cube root / Håstad broadcast
       │ small d? → Wiener / boneh-durfee
       │ n factorable? → Fermat / Pollard p-1 / small primes
       │ padding oracle? → PKCS#1 v1.5 Bleichenbacher
       └── multiple n sharing factor? → GCD attack

AES ─── ECB? → block swap / chosen plaintext
       │ CBC? → padding oracle / bit-flip
       │ CTR? → keystream reuse (XOR two ciphertexts)
       └── nonce reuse (GCM)? → forbidden attack

PRNG ── LCG? → recover state from 2 outputs
       │ MT19937? → clone state from 624 outputs
       └── truncated? → lattice (LLL/BKZ)

ECC ─── small subgroup? → Pohlig-Hellman
       │ singular curve? → additive/multiplicative group reduction
       └── invalid curve? → fault attack

Hash ── length extension? → SHA1/MD5/SHA256 without HMAC
       └── birthday? → collision with controllable prefix
```

## Step 3: Build attack plan before heavy computation
Record in logs/:
1. Primitive + weakness + evidence
2. Falsifiable prediction (e.g. "if LCG, two outputs satisfy a*x+b≡y mod m")
3. Next verification step

## Step 4: Precondition checks (do before implementing)
- RSA: verify n is product of two primes (not more) before Fermat
- Lattice: verify dimension/noise bounds are within LLL reduction limits
- Oracle: measure distinguishability (>0.6 success rate) before 1000-query attack
- PRNG: confirm output count ≥ state size before clone attempt

## Step 5: Implementation order
1. Verify reimplemented primitives against challenge server with known input
2. Implement attack core in solve.py (named function per stage)
3. Add timeout/retry limit before running (no infinite loops)
4. Verify decrypted output: readable text + flag format

## Escalation order
parameter analysis → algebraic attack → oracle queries → lattice → brute (last resort)
