# Open-CTF-Agent 项目规则

适用范围：本仓库内所有会话与自动化脚本执行。

## 目录与数据规范
- 代码与规则：`scripts/`、`prompts/`、`docs/`、`shared/`。
- 运行产物：`workspace/`、`events/`、`runtime/`、`ctf-work/`（仅本地使用，不入库）。
- 新布局为准：题目数据在 `events/<event>/...`，工作区在 `workspace/active|study|archive`。

## 解题流程约束（核心）
- Crypto：默认先跑 `scripts/core/crypto_quick_scan.py`，但**可跳过**（题面已明确算法与参数、交互/时间敏感、或已有可靠分析结果）。
- Misc：默认先跑 `scripts/core/misc_quick_scan.py`，但**可跳过**（题面明确且样本单一、或快速路径已确定）。
- Web：默认先跑 `scripts/core/web_quick_probe.py`，但**可跳过**（已明确目标与漏洞路径、或仅需复现/利用）。
- 交互题优先稳定连接与节流，再做大规模采样。
## 写作与产出
- Writeup 必须中文，包含 **概述 / 分析 / 解题过程 / 试错与迭代 / 要点总结**。
- 解题产物固定落 `./workspace/active/<challenge>/`。
- 所有对用户的自然语言回复必须使用中文（代码/数学符号/路径/命令不做语言要求）。

## 版本管理
- 只跟踪可复用逻辑：`scripts/ prompts/ docs/ shared/ tests/`。
- 不提交运行期数据与自动索引（见 `.gitignore`）。

## 工具与约束
- 命令行只使用已存在脚本与 `--help` 验证过的参数。
- 避免重复大输出，使用 `scripts/core/ctf_throttle.sh` 归档日志。
- 网页搜索优先用内置 `websearch`；检索 DuckDuckGo 时不要加 `r.jina.ai/` 前缀。
- 需要抓取具体页面时用 `webfetch`；仅在页面难以直读时再用 `r.jina.ai/` 做静态化获取。
- 允许内联脚本（`python3 - <<'PY'`、`bash -c '...'`）；可复用或 >20 行逻辑优先写具名文件，内联须记录原因。
- 超过 ~50 行的工具输出必须通过 `ctf_throttle.sh` 重定向到 logs/ 而非打印到 stdout。
