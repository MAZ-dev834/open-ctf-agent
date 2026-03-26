# 主脚本参数文档

这里只保留公开版主路径会直接用到的脚本参数。

## 1. `ctf_preflight.sh`

用途：检查公开仓库所需的最小运行环境。

```bash
./scripts/ops/ctf_preflight.sh --require-auth 0 --check-mcp 0
```

常用参数：

- `--event-dir <dir>`：若你已经有本地赛事目录，可一起检查
- `--require-auth 0|1`：是否强制检查 CTFd 认证
- `--check-mcp 0|1`：是否检查 MCP 相关命令
- `--check-path-sanity 0|1`：是否检查路径异常

## 1.1 `setup_env.sh`

用途：一键初始化公开仓库的本地环境。

注意：它不会安装 `opencode`，你需要提前自行准备好 `opencode CLI`。

```bash
./scripts/ops/setup_env.sh
```

常用参数：

- `--venv <dir>`：指定虚拟环境目录，默认 `./.venv`
- `--no-venv`：不创建虚拟环境
- `--no-env-copy`：不自动复制 `.env.example`
- `--with-web-tools`：额外安装 Web 工具
- `--with-pwn-re-tools`：额外安装 pwn/re 工具链
- `--with-opencode-plugin`：安装 `.opencode` 插件依赖

## 2. `fetch_ctfd.py`

用途：从 CTFd 拉题并写入本地 `events/<event>/`。

```bash
python3 scripts/ctfd/fetch_ctfd.py \
  --base https://example.ctfd.io/ \
  --session "<session_cookie>" \
  --out events/<event> \
  --flag-prefix flag
```

主参数：

- `--base <url>`
- `--session <cookie>`
- `--token <token>`
- `--out <dir>`
- `--flag-prefix <prefix>`
- `--include-solved`
- `--env-file <path>`

## 3. `ctfd_pipeline.py`

用途：比赛主 pipeline，负责题目选择、session、恢复和自动提交。

```bash
python3 scripts/ctfd/ctfd_pipeline.py \
  --out-root events/<event> \
  --competition <event> \
  --auto-run \
  --only-unsolved \
  --auto-submit
```

主参数分组：

### 基本运行

- `--out-root <dir>`
- `--competition <name>`
- `--mode match|submit-only|maint`
- `--env-file <path>`
- `--only-unsolved`
- `--auto-submit`
- `--submit-only`

### 并发与预算

- `--workers <n>`
- `--rounds <n>`
- `--max-active-remote <n>`
- `--auto-timeout`
- `--per-task-timeout-sec <sec>`
- `--global-time-budget-min <min>`

### 模型与冲榜

- `--model <provider/model>`
- `--first-blood-mode`
- 若未显式传 `--model`，默认读取根目录 `.env.local/.env` 中的 `CTF_MODEL`
- `--first-blood-mode` 优先读取 `CTF_FIRST_BLOOD_MODEL`

### 认证与提交

- `--base <url>`
- `--session <cookie>`
- `--token <token>`
- `--min-interval <sec>`
- `--require-replay on|off`
- `--replay-timeout-sec <sec>`
- `--min-candidate-score <score>`
- `--allow-unscored-submit`
- `--max-incorrect-per-challenge <n>`
- `--submit-cooldown-sec <sec>`

### 会话与恢复

- `--resume-incomplete-sessions on|off`
- `--allow-duplicate-sessions`
- `--opencode-continue`

## 4. `submit_flag.py`

用途：单题手动提交。

```bash
python3 scripts/ctfd/submit_flag.py \
  --event-dir events/<event> \
  --id <challenge_id> \
  --flag "flag{...}"
```

主参数：

- `--event-dir <dir>`
- `--id <challenge_id>`
- `--flag <candidate>`
- `--min-interval <sec>`

## 5. `ctf_pipeline_submit_gate.py`

用途：候选 flag 提交门禁。

```bash
python3 scripts/submit/ctf_pipeline_submit_gate.py \
  --challenge-dir "<challenge_dir>" \
  --id <challenge_id> \
  --flag "flag{...}" \
  --candidate-score 0.82 \
  --min-candidate-score 0.60
```

主参数：

- `--challenge-dir <dir>`
- `--id <challenge_id>`
- `--flag <candidate>`
- `--candidate-score <score>`
- `--min-candidate-score <score>`
- `--base / --session / --token`

## 6. 查看完整参数

```bash
python3 scripts/ctfd/fetch_ctfd.py --help
python3 scripts/ctfd/ctfd_pipeline.py --help
python3 scripts/submit/ctf_pipeline_submit_gate.py --help
```
