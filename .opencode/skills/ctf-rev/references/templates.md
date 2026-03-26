# Rev Templates (精简版)

## 字符串搜索
```bash
strings binary | grep -i flag
```

## XOR 解密
```python
def single_byte_xor(data):
    for key in range(256):
        dec = bytes([b ^ key for b in data])
        if b'flag' in dec.lower():
            print(f"Key: {key}, Result: {dec}")
```

## angr 求解
```python
import angr
proj = angr.Project('./binary')
cfg = proj.analyses.CFGFast()
```
