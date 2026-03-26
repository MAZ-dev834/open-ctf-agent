# Crypto Templates (精简版)

## RSA 解密
```python
from Crypto.Util.number import long_to_bytes
m = pow(c, d, n)
flag = long_to_bytes(m)
```

## XOR 解密
```python
def xor_decrypt(data, key):
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
```

## 自动解码
```python
# ciphey -i encrypted.txt
```

## Z3 求解
```python
from z3 import *
x = Int('x')
solve(x**2 + 2*x + 1 == 0)
```
