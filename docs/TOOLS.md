# 工具文档

这里说明公开版默认依赖和可选扩展。

## 1. 最小依赖

默认建议有：

- `python3`
- `bash`
- `opencode`
- `file`
- `strings`
- `sqlite3`

安装 Python 依赖：

```bash
./scripts/ops/setup_env.sh
```

第三方模型 API 可通过 `.env.local` 配置：

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_MODEL=gpt-4.1-mini
```

本地 VLM 可单独配置：

```bash
CTF_VLM_BASE_URL=http://127.0.0.1:1234/v1
CTF_VLM_MODEL=qwen3.5-2b
CTF_VLM_API_KEY=EMPTY
```

## 2. 可选 runner

当前默认 runner 仍是 `opencode`，但公开仓库只提供最小样例配置，不会安装 `opencode` 本体。

相关配置：

- `OPENCODE_ATTACH_URL`
- `OPENCODE_DB`
- `OPENCODE_CONFIG`

如果没有运行 `opencode serve`，主流程会退回普通 `opencode run`。
也就是说：`opencode CLI` 是主路径依赖，`opencode serve` 只是可选运行方式。

## 3. 可选图像能力

这些能力仍然保留在仓库中，但不是最小运行前提：

- `scripts/core/ctf_image_guard.py`
- `scripts/core/ctf_image_watch.py`
- `scripts/core/ocr_pipeline.py`
- `scripts/core/vlm_image_debug.py`

相关环境变量：

- `CTF_VLM_BASE_URL`
- `CTF_VLM_MODEL`
- `CTF_VLM_API_KEY`

## 4. 题型工具

### Web

- `scripts/core/web_quick_probe.py`
- `web_recon.sh`
- `web_js_recon.sh`

### Crypto

- `scripts/core/crypto_quick_scan.py`

### Rev / Pwn

- `scripts/core/rev_quick_scan.py`
- `scripts/core/pwn_profile.py`

### Misc / Forensics

- `scripts/core/misc_quick_scan.py`
- `scripts/core/ctf_artifact_index.py`

## 5. MCP

MCP 在公开版中继续保留，但定位为可选扩展：

- `ctf-radare2`
- `ctf-ghidra`
- `ctf-gdb`

相关脚本：

- `scripts/mcp/install_pwn_re_tools.sh`
- `scripts/mcp/mcp_healthcheck.sh`
- `scripts/mcp/mcp_toggle_pwn_re.sh`
- `scripts/mcp/pwn_remote_libc_check.sh`

如果你没有配置这些环境，主流程仍可运行基础路径。
