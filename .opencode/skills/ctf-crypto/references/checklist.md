# Crypto CTF 检查清单

> Quick start: `python3 .opencode/skills/ctf-crypto/scripts/rsa_solver.py --n ... --e ... --c ...`

## 初始分析
- [ ] 识别密码学原语（RSA、AES、ECC、哈希等）
- [ ] 记录所有参数（n, e, d, p, q, 密钥长度, 模式等）
- [ ] 检查提供的文件（公钥、密文、代码、脚本）
- [ ] 分析攻击者能力（已知明文、选择密文、Oracle 访问等）
- [ ] 若为交互题，先看 `references/interactive-anti-ai.md`

## 反AI交互题（Noisy/限流/状态机）
- [ ] 是否存在带噪 oracle（返回会被随机翻转/偏置）
- [ ] 是否有 PoW / 分层解锁 / 冷却锁定 / 会话衰减
- [ ] 是否先实现节流、退避、重连与预算上限
- [ ] 是否使用序贯判别 + 候选淘汰（而非简单多数票）
- [ ] 是否记录失败特征（限流、超时、锁定）并据此调参

## RSA 检查点
- [ ] 小公钥指数（e=3）
- [ ] 共模攻击（相同 n，不同 e）
- [ ] 低解密指数（Wiener 攻击、Boneh-Durfee）
- [ ] 因数分解（Pollard's p-1, p+1, ECM, Fermat）
- [ ] 部分密钥泄露（已知 p、q 的一部分）
- [ ] 多素数 RSA
- [ ] RSA 签名伪造（盲签名、同态性）
- [ ] PKCS 填充 Oracle（Bleichenbacher）
- [ ] LSB Oracle
- [ ] 广播攻击（Hastad）

## 对称加密检查点
- [ ] ECB 模式模式识别
- [ ] CBC 模式 IV/填充 Oracle
- [ ] CTR 模式 nonce 重用
- [ ] 已知密钥推导（密钥派生函数弱点）
- [ ] 弱密钥（DES、RC4）
- [ ] 位翻转攻击

## 哈希检查点
- [ ] 长度扩展攻击（MD5, SHA1, SHA256）
- [ ] 哈希碰撞（相同的哈希值）
- [ ] 弱随机性（可预测的 nonce）

## 椭圆曲线 (ECC)
- [ ] 曲线参数验证（弱曲线、异常曲线）
- [ ] ECDLP 攻击（Pohlig-Hellman, Baby-step Giant-step）
- [ ] 签名 nonce 重用（ECDSA）
- [ ] Smart 攻击（异常曲线）
- [ ] MOV 攻击（嵌入度小的曲线）

## 格基密码学 (Lattice)
- [ ] LCG（线性同余生成器）
- [ ] 背包密码（Merkle-Hellman）
- [ ] 隐式多项式（Hidden Number Problem）
- [ ] Coppersmith 方法（小根求解）

## 其他
- [ ] PRNG 状态恢复（MT19937、xorshift）
- [ ] OTP（一次性密码本）重用
- [ ] XOR 分析（频率分析、已知明文）
- [ ] Base 编码混淆（多层编码）

## 验证
- [ ] 恢复明文/密钥
- [ ] 检查 flag 格式
- [ ] 脚本可重复运行
