# Reverse CTF 检查清单

> Quick start: `python3 .opencode/skills/ctf-rev/scripts/solve.py strings --input <binary>`

## 初始分析
- [ ] `file` 确认文件类型 (ELF/PE/Mach-O)
- [ ] `checksec` 检查保护
- [ ] `strings` 查找有意义字符串
- [ ] 运行程序观察行为

## 静态分析
- [ ] 导入表/导出表分析
- [ ] 字符串搜索（flag、password、key）
- [ ] 识别混淆（upx、vmprotect）
- [ ] 函数识别（main、check、decrypt）

## 动态分析
- [ ] GDB 调试关键函数
- [ ] 断点设置在 check 函数
- [ ] 观察寄存器/内存变化
- [ ] 追踪函数调用

## 常见题型
- [ ] 简单加密（XOR、base64）
- [ ] 自定义算法
- [ ] 虚拟机/字节码
- [ ] 花指令混淆
- [ ] 打包程序（UPX）

## 验证
- [ ] Flag 格式正确 (flag{...})
- [ ] 程序验证通过
- [ ] 可编写脚本复现
