# Pwn CTF 检查清单

> Quick start: `bash .opencode/skills/ctf-pwn/scripts/pwn_preflight.sh` (or `bash .opencode/skills/ctf-pwn/scripts/pwn_preflight.sh --require-mcp`)

## 初始分析
- [ ] 运行 `file` 确认文件类型和架构
- [ ] 运行 `checksec` 检查保护机制
- [ ] 记录二进制的基本信息（入口点、加载地址等）
- [ ] 检查是否提供了 libc/ld 文件

## 保护机制检查
- [ ] **NX**: Non-executable stack
- [ ] **PIE**: Position Independent Executable
- [ ] **RELRO**: Full/Partial RELRO
- [ ] **Canary**: Stack canary
- [ ] **FORTIFY**: FORTIFY_SOURCE

## 漏洞类型识别
- [ ] **Buffer Overflow**: 栈溢出、堆溢出
- [ ] **Format String**: 格式化字符串漏洞
- [ ] **Use-After-Free**: 释放后重用
- [ ] **Double Free**: 双重释放
- [ ] **Out-of-Bounds**: 越界读写
- [ ] **Integer Overflow**: 整数溢出
- [ ] **Race Condition**: 竞态条件

## Exploit 开发步骤
1. [ ] 本地调试，确认漏洞可触发
2. [ ] 优先使用 gdb batch + 有限输出，不先读大日志
3. [ ] 绕过保护（如果可能）
4. [ ] 构造 payload
5. [ ] 测试远程 exploit
6. [ ] 确保稳定性（leak、循环等）

## 常见利用技术
- [ ] Ret2libc / ROP
- [ ] Stack Pivoting
- [ ] SROP (Sigreturn-Oriented Programming)
- [ ] JOP (Jump-Oriented Programming)
- [ ] House of Spirit / Lore / Einherjar 等

## 验证
- [ ] Flag 格式正确
- [ ] Exploit 可重复运行
- [ ] 本地和远程测试一致
- [ ] 未把大段 `strace`/`objdump` 全文塞入上下文
