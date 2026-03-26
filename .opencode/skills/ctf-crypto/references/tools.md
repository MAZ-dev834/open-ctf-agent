# CTF 工具清单

## 已安装工具

### 系统工具
- gdb, gdb-multiarch (调试)
- binutils, file, strace, ltrace
- steghide, binwalk, foremost, exiftool
- p7zip-full, fcrackzip
- tcpdump, tshark
- radare2

### Python 库
- pwntools (Pwn)
- angr (二进制分析)
- pycryptodome, gmpy2, sympy (密码学)
- z3-solver (约束求解)
- capstone, keystone-engine, unicorn (反汇编)
- ropper, one-gadget (ROP)
- scapy (网络)
- beautifulsoup4 (Web)

### 外部工具
- SQLMap: `~/tools/sqlmap/`
- dirsearch: `~/tools/dirsearch/`
- stegseek: `~/tools/stegseek/`

### 常用在线工具
- factordb.com (因数分解)
- cryptohack.org (密码学练习)
- dcode.fr (密码学工具)
- gchq.github.io/CyberChef/ (编码/加密)

## 安装命令
```bash
# 激活 PATH
source ~/.bashrc

# 运行工具
python ~/tools/sqlmap/sqlmap.py -u "url"
python ~/tools/dirsearch/dirsearch.py -u "http://target/"
python ~/tools/stegseek/stegseek.py image.jpg wordlist.txt

# Python 工具
python3 -c "import pwn; pwn.text年轻人的()"
```
