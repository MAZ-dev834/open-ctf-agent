# CTF 跨技能协作协议

## 1. 主技能选择规则

每道题只能有一个主技能。按**主 blocker**选择，而不是按题目标签选择。

| 主 blocker | 主技能 |
|---|---|
| HTTP 服务、认证、对象权限、浏览器/服务端信任边界 | `ctf-web` |
| 内存破坏、沙箱逃逸、利用原语、二进制利用 | `ctf-pwn` |
| 程序逻辑恢复、校验重建、常量提取、逆向求解 | `ctf-rev` |
| 密码学攻击、参数恢复、oracle 推断、代数建模 | `ctf-crypto` |
| 公网线索搜索、归因、地理定位、社媒/DNS/归档 | `ctf-osint` |
| 磁盘/内存/PCAP/日志/隐写/媒体取证 | `ctf-forensics` |
| 恶意样本、混淆脚本、C2、行为链复盘 | `ctf-malware` |
| 解码、容器、协议谜题、jail、游戏/VM、杂项流水线 | `ctf-misc` |

## 2. 辅助技能介入规则

- 辅助技能只能解决局部 blocker，不能接管整题。
- 主技能负责维护当前阶段、todo、证据和最终收束。
- 常见切换/协作模式：
  - `ctf-web -> ctf-crypto`: 已定位漏洞，但核心卡在 token/cipher/math。
  - `ctf-rev -> ctf-pwn`: 已提取到 exploit-relevant primitive 或明确利用面。
  - `ctf-misc -> ctf-crypto`: 已确认主问题是密码学攻击，而不是解码流水线。
  - `ctf-forensics -> ctf-osint`: 本地证据已提取，后续必须公网验证。
  - `ctf-osint -> ctf-forensics`: 公开线索已指向本地文件/媒体分析。

## 3. Todo 所有权规则

- 只有主技能维护 todo。
- 辅助技能只输出：
  - 新证据
  - 局部结论
  - 建议新增/关闭的 todo
- 切换主技能时必须同时完成三件事：
  1. 关闭旧主技能已失效的分支 todo。
  2. 重写新的 3-5 条 todo。
  3. 明确写出切换原因：`旧 blocker -> 新 blocker`。

## 4. 切换时机

- 同一分支连续 3 次无新信号，不要继续让同技能微调，先判断是否该切技能或切表示层。
- 如果题目标签和主 blocker 冲突，以主 blocker 为准。
- 没有明确切换依据时，不要切主技能，只允许辅助技能给局部建议。
