# Pwn CTF 工具清单

## 核心工具

### Python 库
```bash
pip install pwntools ropchain keystone-engine capstone
```

### 系统工具
```bash
# Ubuntu/Debian
sudo apt-get install gdb gdb-multiarch gef pwndbg ropper

# 检查保护
checksec --version=2

# 64位支持
sudo apt-get install gcc-multilib
```

### 常用工具
- **pwntools**: Exploit 开发框架
- **gef/pwndbg**: GDB 增强插件
- **ropper**: ROP gadget 搜索
- **one_gadget**: One Gadget RCE 查找
- **patchelf**: 修复 ELF 动态链接
- **angr**: 二进制分析框架
- **uncompyle6**: Python 反编译

## 检查工具版本
```bash
python3 -c "import pwn; print('pwntools:', pwn.__version__)"
gdb --version | head -1
ropper --version
one_gadget --version
```
