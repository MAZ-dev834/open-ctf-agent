# Reverse CTF 工具清单

## 反编译工具
```bash
# Ghidra
sudo apt-get install ghidra
# 或下载: https://github.com/NationalSecurityAgency/ghidra/releases

# Radare2
sudo apt-get install radare2

# IDA/Ghidra vs Hopper
# 在线反编译: https://dogbolt.org/
```

## 分析工具
```bash
# 基础
file <binary>
strings <binary>
strace <binary>
ltrace <binary>

# GDB 增强
gef install: https://github.com/hugsy/gef
pwndbg: https://github.com/pwndbg/pwndbg
```

## Python 库
```bash
pip install angr pycryptodome unicorn
```

## 检查版本
```bash
ghidra --version
r2 -v
python3 -c "import angr; print(angr.__version__)"
```
