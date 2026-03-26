# open-ctf-agent

`open-ctf-agent` 是一个面向 CTF 的研究型 agent 仓库。它保留了比赛主 pipeline、specialist prompts、learn/memory 框架和 MCP 接入口，但不包含任何真实赛事数据、个人工作区或作者本地运行环境。

## 仓库定位

- 这是研究仓库，不是即开即用的托管平台。
- 主路径围绕 `fetch -> pipeline -> submit gate` 组织。
- `scripts/learn/` 和 `.opencode/skills/` 保留为轻量研究层；默认不依赖历史记忆库数据。
- 完整跑主 pipeline 需要你本地预先安装 `opencode` CLI。
- MCP、VLM、外部工具安装都属于可选能力，不是最小运行前提。

## 公开版保留的目录

- `scripts/`: 主流程、工具脚本、learn/MCP/ops 入口
- `prompts/`: 主 agent prompt 与 pipeline prompt 片段
- `docs/`: 开源版主文档
- `shared/`: 通用 helper、模板、精简后的 memory 模板
- `tests/`: 纯单元测试
- `examples/`: 最小脱敏样例
- `.opencode/`: 最小样例配置和 skill 文档

这些目录默认不入库，需由使用者本地自行生成：

- `events/`
- `workspace/`
- `runtime/`
- `ctf-work/`
- `external/`

## 安装

先确认你本地已经安装 `opencode` CLI。这个仓库不会自动安装它。

```bash
./scripts/ops/setup_env.sh
```

如果你要使用 attach 模式或本地服务模式，再启动：

```bash
opencode serve
```

如果只想先看脚本和样例，不需要先准备真实比赛数据。

## Quick Start

查看 CLI：

```bash
python3 scripts/ctfd/fetch_ctfd.py --help
python3 scripts/ctfd/ctfd_pipeline.py --help
python3 scripts/submit/ctf_pipeline_submit_gate.py --help
./scripts/ops/ctf_preflight.sh --help
```

查看最小脱敏样例：

```bash
find examples/demo-event -maxdepth 3 -type f | sort
```

对本地环境做一次基础检查：

```bash
./scripts/ops/ctf_preflight.sh --require-auth 0 --check-mcp 0
```

## 第三方模型 API

公开版支持 OpenAI-compatible API。最小配置直接写到 `.env.local`：

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_MODEL=gpt-4.1-mini
```

如果你使用本地或自建 VLM，也可以单独配置：

```bash
CTF_VLM_BASE_URL=http://127.0.0.1:1234/v1
CTF_VLM_MODEL=qwen3.5-2b
CTF_VLM_API_KEY=EMPTY
```

比赛主 pipeline 默认读取根目录 `.env.local/.env` 中的 `CTF_MODEL`，一血模式读取 `CTF_FIRST_BLOOD_MODEL`。
`.opencode/opencode.json` 在公开版里主要提供 agent / command / MCP 样例；实际 provider、认证和模型路由请按你的本地 `opencode` 环境调整。

## 默认工作流

1. 使用 `scripts/ctfd/fetch_ctfd.py` 从 CTFd 拉题到你本地的 `events/<event>/`
2. 使用 `scripts/ctfd/ctfd_pipeline.py` 选择题目、路由 specialist、生成上下文并运行 session
3. 使用 `scripts/submit/ctf_pipeline_submit_gate.py` 对候选 flag 做节流、去重和提交门禁
4. 使用 `scripts/core/ctf_evidence_log.py`、`scripts/core/ctf_checkpoint.py`、`scripts/core/ctf_artifact_index.py` 维护题目证据链

## 开源版说明

- 仓库中不包含真实比赛目录、历史 writeup、flag、个人记忆索引或绝对路径样本。
- `shared/skill-memory/` 现在只保留方法模板，不再携带历史题目数据。
- `.opencode/opencode.json` 是最小公开样例；实际 provider、model、MCP 命令请按你的本地环境调整。

更多说明见 [docs/README.md](docs/README.md)。
