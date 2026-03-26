#!/usr/bin/env python3
"""
RSA helper for common CTF attack paths.

Examples:
  python3 rsa_solver.py --n 0x... --e 65537 --c 0x...
  python3 rsa_solver.py --n 123 --e 65537 --c 456 --p 11 --q 13
  python3 rsa_solver.py --n N --e E1 --c C1 --c2 C2 --e2 E2
"""

from __future__ import annotations

import argparse
import math
import random
import re
from typing import Iterable, Optional, Tuple


def parse_int(value: str) -> int:
    return int(value, 0)


def int_to_bytes(n: int) -> bytes:
    if n == 0:
        return b"\x00"
    size = (n.bit_length() + 7) // 8
    return n.to_bytes(size, "big")


def egcd(a: int, b: int) -> Tuple[int, int, int]:
    if b == 0:
        return (a, 1, 0)
    g, x1, y1 = egcd(b, a % b)
    return (g, y1, x1 - (a // b) * y1)


def invmod(a: int, n: int) -> int:
    g, x, _ = egcd(a, n)
    if g != 1:
        raise ValueError("inverse does not exist")
    return x % n


def decrypt_with_factors(n: int, e: int, c: int, p: int, q: int) -> Optional[int]:
    if p * q != n:
        return None
    phi = (p - 1) * (q - 1)
    try:
        d = invmod(e, phi)
    except ValueError:
        return None
    return pow(c, d, n)


def fermat_factor(n: int, max_steps: int = 200000) -> Optional[Tuple[int, int]]:
    if n % 2 == 0:
        return (2, n // 2)
    a = math.isqrt(n)
    if a * a < n:
        a += 1
    for _ in range(max_steps):
        b2 = a * a - n
        b = math.isqrt(b2)
        if b * b == b2:
            p = a - b
            q = a + b
            if p > 1 and q > 1 and p * q == n:
                return (p, q)
        a += 1
    return None


def pollard_rho(n: int, max_rounds: int = 40, max_iter: int = 200000) -> Optional[int]:
    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3

    for _ in range(max_rounds):
        x = random.randrange(2, n - 1)
        y = x
        c = random.randrange(1, n - 1)
        d = 1

        for _ in range(max_iter):
            x = (pow(x, 2, n) + c) % n
            y = (pow(y, 2, n) + c) % n
            y = (pow(y, 2, n) + c) % n
            d = math.gcd(abs(x - y), n)
            if d == 1:
                continue
            if d == n:
                break
            return d
    return None


def common_modulus_attack(c1: int, c2: int, e1: int, e2: int, n: int) -> Optional[int]:
    g, s1, s2 = egcd(e1, e2)
    if g != 1:
        return None

    if s1 < 0:
        c1 = invmod(c1, n)
        s1 = -s1
    if s2 < 0:
        c2 = invmod(c2, n)
        s2 = -s2

    return (pow(c1, s1, n) * pow(c2, s2, n)) % n


def continued_fraction(num: int, den: int) -> Iterable[int]:
    while den:
        q = num // den
        yield q
        num, den = den, num - q * den


def convergents(cf: Iterable[int]) -> Iterable[Tuple[int, int]]:
    p0, q0 = 0, 1
    p1, q1 = 1, 0
    for a in cf:
        p = a * p1 + p0
        q = a * q1 + q0
        yield p, q
        p0, q0, p1, q1 = p1, q1, p, q


def wiener_attack(e: int, n: int) -> Optional[int]:
    for k, d in convergents(continued_fraction(e, n)):
        if k == 0:
            continue
        if (e * d - 1) % k != 0:
            continue
        phi = (e * d - 1) // k
        s = n - phi + 1
        disc = s * s - 4 * n
        if disc < 0:
            continue
        t = math.isqrt(disc)
        if t * t != disc:
            continue
        p = (s + t) // 2
        q = (s - t) // 2
        if p * q == n:
            return d
    return None


def describe_plaintext(m: int, flag_regex: Optional[re.Pattern[str]]) -> str:
    raw = int_to_bytes(m)
    text = raw.decode("utf-8", errors="ignore")
    lines = [f"m (int): {m}", f"m (hex): {hex(m)}", f"utf8: {text!r}"]
    if flag_regex is not None:
        matches = flag_regex.findall(text)
        if matches:
            lines.append(f"flag_match: {matches[0]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="RSA CTF solver")
    parser.add_argument("--n", type=parse_int, required=True)
    parser.add_argument("--e", type=parse_int, required=True)
    parser.add_argument("--c", type=parse_int, required=True)
    parser.add_argument("--p", type=parse_int)
    parser.add_argument("--q", type=parse_int)
    parser.add_argument("--d", type=parse_int)
    parser.add_argument("--c2", type=parse_int)
    parser.add_argument("--e2", type=parse_int)
    parser.add_argument("--fermat-steps", type=int, default=200000)
    parser.add_argument("--pollard-rounds", type=int, default=40)
    parser.add_argument("--flag-regex", default="")
    args = parser.parse_args()

    flag_regex = re.compile(args.flag_regex) if args.flag_regex else None

    # 1) direct decrypt with provided d
    if args.d is not None:
        m = pow(args.c, args.d, args.n)
        print("[+] Decrypted with provided d")
        print(describe_plaintext(m, flag_regex))
        return 0

    # 2) decrypt with provided factors
    if args.p is not None and args.q is not None:
        m = decrypt_with_factors(args.n, args.e, args.c, args.p, args.q)
        if m is not None:
            print("[+] Decrypted with provided p/q")
            print(describe_plaintext(m, flag_regex))
            return 0

    # 3) common modulus attack
    if args.c2 is not None and args.e2 is not None:
        m = common_modulus_attack(args.c, args.c2, args.e, args.e2, args.n)
        if m is not None:
            print("[+] Decrypted via common modulus attack")
            print(describe_plaintext(m, flag_regex))
            return 0

    # 4) wiener
    d = wiener_attack(args.e, args.n)
    if d is not None:
        m = pow(args.c, d, args.n)
        print("[+] Decrypted via Wiener attack")
        print(describe_plaintext(m, flag_regex))
        return 0

    # 5) fermat
    factors = fermat_factor(args.n, max_steps=args.fermat_steps)
    if factors is not None:
        p, q = factors
        m = decrypt_with_factors(args.n, args.e, args.c, p, q)
        if m is not None:
            print("[+] Decrypted via Fermat factoring")
            print(f"p={p}")
            print(f"q={q}")
            print(describe_plaintext(m, flag_regex))
            return 0

    # 6) pollard rho
    f = pollard_rho(args.n, max_rounds=args.pollard_rounds)
    if f is not None and f not in (1, args.n):
        p, q = f, args.n // f
        m = decrypt_with_factors(args.n, args.e, args.c, p, q)
        if m is not None:
            print("[+] Decrypted via Pollard rho")
            print(f"p={p}")
            print(f"q={q}")
            print(describe_plaintext(m, flag_regex))
            return 0

    print("[-] No successful attack path")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
