# Claude Code Delegate

> 让你的 AI 编排器（Codex、Cursor、Claude Code）将实现任务委派给 Claude Code —— 以 DeepSeek V4 作为低成本模型后端。

编排器负责规划和审查。本工具处理中间所有环节：分类任务、包装 prompt 模板、调用 Claude Code、压缩输出、返回结构化结果。wrapper 和 pipeline 均不批准变更 —— 这是编排器的职责。

## 这是什么 / 不是什么

| 本项目是... | 本项目不是... |
|---|---|
| AI-to-AI 编码工作流的委派层 | 全自主编码 agent |
| 标准化分类、调用和输出压缩的流水线 | 编排器规划和审查角色的替代品 |
| 传输无关：MCP server + shell wrapper，共享同一 pipeline | 「连接 DeepSeek 的 Claude Code」——模型后端可替换 |

## 编排器如何调用

### MCP 传输（推荐）

在项目的 `.mcp.json` 中添加：

```json
{
  "mcpServers": {
    "claude-code-delegate": {
      "command": "python3",
      "args": ["scripts/mcp_server.py"]
    }
  }
}
```

编排器通过 `tools/list` 发现四个工具，一次类型化调用即可委派：

```
delegate_task(prompt="修复 src/cli.py 中的类型错误")
// → { classification, result, usage, cost_usd, terminal_reason }
```

还提供：`classify_task`、`aggregate_profile`、`format_jira_text`。需要 `pip install mcp`。

### Shell wrapper（后备）

同一流水线，通过 CLI 调用：

```bash
./scripts/run-claude-code.sh "修复 src/cli.py 中的类型错误"
```

wrapper 解析标志，调用 `scripts/run-pipeline.py`，输出简洁报告。不需要 `mcp` 包。完整 CLI 参考见 [docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md)。

两个传输共享 `scripts/pipeline.py` —— 相同的 classify → envelope → invoke → compact → profile 逻辑。

## 委派循环

1. **Plan** —— 编排器读取项目上下文，生成包含所有权边界和验证命令的具体计划。
2. **Delegate** —— pipeline 分类任务、包装 prompt 模板、解析 model/effort/permission 设置、调用 Claude Code、压缩输出。
3. **Execute** —— Claude Code 使用配置的模型后端（默认 DeepSeek V4）执行计划。
4. **Compact** —— pipeline 将 Claude Code 的 JSON 输出解析为简洁报告：结果文本、token 用量、成本、终止状态。
5. **Review** —— 编排器检查 `git diff`、测试输出和报告，决定接受、拒绝或要求修正。
6. **Report** —— 编排器给出最终摘要：变更内容、测试结果、剩余风险。

修正循环重复步骤 2–5，直到 diff 正确。

## 为什么不直接 `claude -p`？

```bash
claude -p "修复类型错误" --model deepseek-v4-flash[1m]
```

直接调用适合单个命令。委派层在以下场景增值：

- **任务分类** —— 根据 prompt 内容自动选择模型层级和 effort（flash 用于编辑，pro 用于调试/架构）。
- **Prompt 模板** —— 将编排器的计划包装在任务封套中，包含编码规范和所有权边界。
- **输出压缩** —— 原始 JSON 流变为编排器可程序化解析的结构化报告。
- **安全默认值** —— 禁用 subagent，心跳确认执行器仍在运行，记录画像元数据。
- **一致调用** —— 每次委派的 model、effort、permissions、MCP config 完全一致。

快速回答用 `claude -p`。需要一致、可审查的 AI-to-AI 执行时用委派层。

## 安装

### 一行命令

```bash
curl -fsSL https://raw.githubusercontent.com/DongL/claude-code-delegate/main/install.sh | bash
```

### 手动安装

```bash
git clone https://github.com/DongL/claude-code-delegate.git ~/.claude-code-delegate
mkdir -p ~/.agents/skills
ln -sfn ~/.claude-code-delegate ~/.agents/skills/claude-code-delegate
bash ~/.claude-code-delegate/tests/run_tests.sh
pip3 install mcp  # 可选，用于 MCP server
```

### 作为 Codex skill

创建符号链接到 skill 目录，让 Codex 发现 `SKILL.md`：

```bash
mkdir -p ~/.agents/skills
ln -sfn "$PWD" ~/.agents/skills/claude-code-delegate
```

`SKILL.md` 中的解析器按以下路径查找 wrapper：

1. `$CLAUDE_DELEGATE_DIR` —— 显式覆盖
2. `$HOME/.agents/skills/claude-code-delegate` —— 当前 Codex 路径
3. `$HOME/.codex/skills/claude-code-delegate` —— 旧版 Codex 路径

## Provider 设置

本项目默认使用 DeepSeek V4 模型，通过环境变量配置：

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<你的 DeepSeek API key>
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_EFFORT_LEVEL=max
```

在 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 获取 API key。验证：

```bash
claude -p "hello" --model deepseek-v4-flash[1m]
```

或者使用 [cc-switch](https://github.com/farion1231/cc-switch) 进行 GUI 方式的 provider 管理，内置 50+ 预设。

覆盖单次委派的模型：

```bash
CLAUDE_DELEGATE_MODEL=claude-sonnet-4-6 ./scripts/run-claude-code.sh "你的 prompt"
```

## CLI 参考

| 标志 | 效果 |
|------|------|
| *(无)* | Pro 模型，quiet 输出，bypass 权限（默认） |
| `--pro` / `--flash` | 模型层级选择 |
| `--effort low\|medium\|high\|max` | 推理预算覆盖 |
| `--interactive` | 自动接受编辑，工具命令需确认（安全首次运行） |
| `--bypass` | 完全非交互（默认的显式别名） |
| `--stream` | 原始 stream-json 输出（调试用） |
| `--mcp all\|none\|jira\|linear\|sequential-thinking` | MCP server 加载 |
| `--full-context` | 跳过 prompt 模板包装 |
| `--allow-subagents` | 允许 Claude Code 生成 subagent |

环境变量等价项和完整细节：[docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md)。权限模式和安全：[SECURITY.md](SECURITY.md)。

## 组件

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 编排器契约 —— 委派循环、解析器、职责 |
| `scripts/pipeline.py` | 委派流水线 —— 两个传输共享 |
| `scripts/run-pipeline.py` | CLI 入口 —— 供 shell wrapper 调用 |
| `scripts/run-claude-code.sh` | Shell wrapper —— 仅做标志解析 |
| `scripts/mcp_server.py` | MCP server —— 基于 stdio 的类型化 JSON-RPC 工具 |
| `scripts/compact-claude-stream.py` | 输出解析器 —— JSON 流 → 结构化报告 |
| `scripts/profile_logger.py` | 画像记录构建和 JSONL 追加 |
| `scripts/aggregate-profile-log.py` | 画像日志聚合和摘要 |
| `scripts/jira-safe-text.py` | Markdown → Jira 安全纯文本转换器 |
| `tests/run_tests.sh` | 测试运行器 —— pipeline、调用和压缩 |
| `docs/shell-wrapper-reference.md` | 完整 CLI 标志/环境变量参考 |
| `docs/jira-workflow.md` | Jira 委派约定 |

## 画像分析

委派时设置 `CLAUDE_DELEGATE_PROFILE_LOG` 记录每次调用：

```
delegate_task(prompt="修复拼写错误")
// profiling 自动追加到 CLAUDE_DELEGATE_PROFILE_LOG
```

通过 MCP 读取聚合结果：

```
aggregate_profile(profile_log_path="logs/profile.jsonl", format="text")
// → "Records: 12  Success: 10  Error: 2 ..."
```

Shell 后备方式：

```bash
export CLAUDE_DELEGATE_PROFILE_LOG=logs/profile.jsonl
./scripts/run-claude-code.sh "你的 prompt"
python3 scripts/aggregate-profile-log.py logs/profile.jsonl
```

每条记录包含：model、effort、任务类型、token 用量、缓存命中率、成本、prompt 字符数。

## 依赖

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- `python3`（仅标准库；`pip install mcp` 可选，用于 MCP server）
- 可访问的 Claude Code 兼容模型

## 许可证

MIT
