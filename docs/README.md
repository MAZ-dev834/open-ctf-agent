# Open-CTF-Agent 开源版主文档

这份文档只描述公开仓库的主路径，不假设你拥有作者本地的赛事目录、工作区或历史记忆库。

完整跑主 pipeline 前，默认要求你本地已经安装 `opencode` CLI。这个仓库只提供配置样例和脚本，不负责安装 `opencode` 本体。

## 1. 项目结构

- `scripts/ctfd/`: 比赛主流程、CTFd 抓取、session/submit 编排
- `scripts/core/`: 通用 runtime、证据、artifact、quick scan 工具
- `scripts/submit/`: 提交门禁与候选提交流程
- `scripts/learn/`: 学习/记忆框架
- `scripts/mcp/`: 可选 MCP 接入脚本
- `prompts/`: specialist 与 pipeline prompt
- `shared/`: helper、模板、精简 memory 模板
- `examples/demo-event/`: 最小脱敏样例

运行时目录由使用者本地创建，不随仓库发布：

- `events/<event>/`
- `workspace/active/`
- `workspace/archive/`
- `runtime/`

## 2. 当前系统形态

这不是单一 prompt agent，而是一套围绕 `ctfd_pipeline.py` 组织的比赛自动化系统。

核心分层：

1. CTFd/事件入口层
2. pipeline 调度层
3. session 与状态记录层
4. specialist prompt/runtime 层
5. 提交门禁与证据闭环

主入口：

- `scripts/ctfd/fetch_ctfd.py`
- `scripts/ctfd/ctfd_pipeline.py`
- `scripts/submit/ctf_pipeline_submit_gate.py`
- `scripts/ctfd/submit_flag.py`

## 3. 最小准备

```bash
./scripts/ops/setup_env.sh
./scripts/ops/ctf_preflight.sh --require-auth 0 --check-mcp 0
```

说明：

- `setup_env.sh` 负责 Python 依赖、目录和本地样例配置。
- `opencode` 需要你提前自行安装。
- 是否运行 `opencode serve` 取决于你是否要用 attach 模式；只使用普通 `opencode run` 时不一定需要常驻服务。

可选能力：

- 本地 `opencode serve`
- 本地 VLM / OCR
- MCP for pwn/re
- 额外系统工具，如 `tesseract`、`ffuf`、`binwalk`

模型 API 最小示例：

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_MODEL=gpt-4.1-mini
```

如果你使用 OpenAI-compatible 第三方平台，通常只需要替换 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`。
如果你希望 pipeline 默认模型也跟着走根目录环境文件，额外设置：

```bash
CTF_MODEL=openai/gpt-4.1-mini
CTF_FIRST_BLOOD_MODEL=openai/gpt-4.1
```

## 4. 使用方式

### 4.1 抓取 CTFd

```bash
python3 scripts/ctfd/fetch_ctfd.py \
  --base https://example.ctfd.io/ \
  --session "<session_cookie>" \
  --out events/<event> \
  --flag-prefix flag
```

### 4.2 跑 pipeline

```bash
python3 scripts/ctfd/ctfd_pipeline.py \
  --out-root events/<event> \
  --competition <event> \
  --auto-run \
  --only-unsolved \
  --auto-submit
```

### 4.3 单题提交

```bash
python3 scripts/ctfd/submit_flag.py \
  --event-dir events/<event> \
  --id <challenge_id> \
  --flag "flag{...}"
```

## 5. 研究能力说明

- `scripts/learn/` 保留，但默认不附带历史索引数据。
- `shared/skill-memory/` 是方法模板，不再是历史题库。
- `scripts/mcp/` 继续存在，但属于可选扩展，不是公开版默认依赖。
- `.opencode/opencode.json` 是公开版最小样例，主要用于 agent / command / MCP 结构示例；不要把它理解成“开箱即用的通用 provider 配置”。

## 6. 最小样例

仓库提供 `examples/demo-event/` 作为目录结构示例，展示：

- challenge 元信息
- 最小 `status.json`
- 题目目录布局
- 如何给 agent 提供可重放上下文

这个样例不是完整赛题，也不会包含真实 flag。
