# Claude Code Delegate

> Let your AI orchestrator (Codex, Cursor, etc.) delegate implementation tasks to Claude Code — with DeepSeek V4 as the low-cost model backend.

<details open>
<summary><b>English</b></summary>

An orchestrator owns planning and review. This toolkit handles everything in between: classify the task, wrap it in a prompt template, invoke Claude Code, compact the output, and return a structured result. Neither the wrapper nor the pipeline approves changes — that's the orchestrator's job.

## What This Is / Is Not

| This project is... | This project is not... |
|---|---|
| A delegation layer for AI-to-AI coding workflows | A fully autonomous coding agent |
| A pipeline that standardizes classification, invocation, and output compaction | A replacement for the orchestrator's planning and review role |
| Transport-agnostic: MCP server + shell wrapper, same pipeline | "Claude Code connected to DeepSeek" — the model backend is replaceable |

## Installation

### One-command

```bash
curl -fsSL https://raw.githubusercontent.com/DongL/claude-code-delegate/main/install.sh | bash
```

### Manual

```bash
git clone https://github.com/DongL/claude-code-delegate.git ~/.claude-code-delegate
mkdir -p ~/.agents/skills
ln -sfn ~/.claude-code-delegate ~/.agents/skills/claude-code-delegate
bash ~/.claude-code-delegate/tests/run_tests.sh
pip3 install mcp  # optional, for MCP server
```

### As a Codex skill

Symlink into the skill directory so Codex discovers `SKILL.md`:

```bash
mkdir -p ~/.agents/skills
ln -sfn "$PWD" ~/.agents/skills/claude-code-delegate
```

The resolver in `SKILL.md` finds the wrapper across these paths:

1. `$CLAUDE_DELEGATE_DIR` — explicit override
2. `$HOME/.agents/skills/claude-code-delegate` — current Codex path
3. `$HOME/.codex/skills/claude-code-delegate` — legacy Codex path

### Verify

```bash
./scripts/run-claude-code.sh --flash 'hello from delegate'
```

If the setup is correct, you will see a compact report with model, usage, and cost.

## Provider Setup (DeepSeek V4)

This project defaults to DeepSeek V4 models for low-cost delegation. If you use vanilla Claude Code with Anthropic models, skip this section and override the model per-invocation: CLAUDE_DELEGATE_MODEL=claude-sonnet-4-6 ./scripts/run-claude-code.sh "your prompt"

```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<your DeepSeek API key>
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash[1m]
export CLAUDE_CODE_EFFORT_LEVEL=max
```

Get your API key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys). Verify:

```bash
claude -p "hello" --model deepseek-v4-flash[1m]
```

Or use [cc-switch](https://github.com/farion1231/cc-switch) for GUI-based provider management with 50+ presets.

## How Your Orchestrator Calls It

### MCP transport (preferred)

Add to your project's `.mcp.json`:

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

Your orchestrator discovers four tools via `tools/list` and delegates with one typed call:

```
delegate_task(prompt="fix the type error in src/cli.py")
// → { classification, result, usage, cost_usd, terminal_reason }
```

Also available: `classify_task`, `aggregate_profile`, `format_jira_text`. Requires `pip install mcp`.

### Shell wrapper (fallback)

Same pipeline, invoked through a CLI:

```bash
./scripts/run-claude-code.sh "fix the type error in src/cli.py"
```

The wrapper parses flags, calls `scripts/run-pipeline.py`, and prints a compact report. No `mcp` package needed. Full CLI reference in [docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md).

Both transports share `scripts/pipeline.py` — the same classify → envelope → invoke → compact → profile logic.

## The Delegation Loop

1. **Plan** — The orchestrator reads project context and produces a concrete plan with ownership boundaries and verification commands.
2. **Delegate** — The pipeline classifies the task, wraps it in a prompt template, resolves model/effort/permission settings, invokes Claude Code, and compacts the output.
3. **Execute** — Claude Code implements the plan using the configured model backend (DeepSeek V4 by default).
4. **Compact** — The pipeline parses Claude Code's JSON output into a concise report: result text, token usage, cost, and terminal status.
5. **Review** — The orchestrator inspects `git diff`, test output, and the compact report, then decides to accept, reject, or request a correction pass.
6. **Report** — The orchestrator gives a final summary: what changed, which tests ran, residual risk.

Correction iterations repeat steps 2–5 until the diff is correct.

## Why This Architecture

**Cost efficiency.** The orchestrator handles planning and review — tasks that benefit from strong reasoning models. The executor handles code edits, test runs, and file operations — tasks that work well with cheaper models. You pay premium rates only for the steps that need them. A typical delegation costs $0.28 on DeepSeek V4 vs. $3+ on Anthropic direct.

**Structural enforcement.** The delegation loop forces a clean separation: plan before you code, review before you merge. The orchestrator cannot skip the plan — it must articulate ownership boundaries and verification commands. The executor cannot skip review — every diff goes back to the orchestrator. This prevents "just write something and hope it works."

**Auditability.** Every delegation produces a diff, a compact report, a token-usage summary, and a cost record. The orchestrator reviews each change. Nothing is accepted silently. If a correction pass is needed, you see exactly what changed between passes.

**Model specialization.** Planning calls for broad context and high-level reasoning. Execution calls for precision, speed, and surgical edits. No single model is best at both. Delegation lets you pair a strong planning model (Codex, Opus) with a fast execution model (DeepSeek V4 Flash, Haiku) — each doing what it's best at.

**Safety boundary.** The execution plan defines ownership boundaries: which files may be touched, what commands may run. The executor cannot silently refactor the codebase or revert unrelated changes. Subagents are disabled by default to prevent recursive delegation.

**Progressive trust.** Start with `--interactive` to review every tool command before execution. Graduate to `--bypass` once you trust the executor's output quality. The same pipeline works for both — only the permission mode changes.

## Why Not `claude -p` Directly?

```bash
claude -p "fix the type error" --model deepseek-v4-flash[1m]
```

Direct invocation works for single commands. The delegation layer adds value when:

- **Task classification** — automatically selects model tier and effort based on prompt content (flash for edits, pro for debugging/architecture).
- **Prompt templates** — wraps the orchestrator's plan in a task envelope with coding guidelines and ownership boundaries.
- **Output compaction** — raw JSON stream becomes a structured report the orchestrator can parse programmatically.
- **Safety defaults** — subagents disabled, heartbeat confirms the executor is still alive, profile metadata recorded.
- **Consistent invocation** — model, effort, permissions, MCP config identical across every delegation.

Use `claude -p` for quick answers. Use the delegation layer when you want consistent, reviewable, AI-to-AI execution.

## CLI Reference

| Flag | Env Var | Effect |
|------|---------|--------|
| *(default)* | | Pro model, quiet output, bypass permissions |
| --pro / --flash | CLAUDE_DELEGATE_MODEL | Model tier selection |
| --effort low\|medium\|high\|max | CLAUDE_DELEGATE_EFFORT | Reasoning budget override |
| --quiet / --stream | CLAUDE_DELEGATE_OUTPUT_MODE | Output format (quiet: compact report, stream: raw JSON) |
| --interactive | CLAUDE_DELEGATE_PERMISSION_MODE | Auto-accept edits, prompt on tool commands |
| --bypass | CLAUDE_DELEGATE_PERMISSION_MODE | Fully non-interactive (default) |
| --mcp all\|none\|jira\|linear\|sequential-thinking | CLAUDE_DELEGATE_MCP_MODE | MCP server loading |
| --full-context | CLAUDE_DELEGATE_CONTEXT_MODE | Skip prompt template wrapping |
| --allow-subagents | CLAUDE_DELEGATE_SUBAGENTS | Allow Claude Code to spawn subagents |

Env var equivalents and full details: [docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md). Permission modes and security: [SECURITY.md](SECURITY.md).

## Components

| File | Purpose |
|------|---------|
| `SKILL.md` | Orchestrator contract — delegation loop, resolver, responsibilities |
| `CONTEXT.md` | Domain glossary — Orchestrator, Executor, Pro vs Flash, MCP terminology |
| `scripts/pipeline.py` | Delegation pipeline — shared by both transports |
| `scripts/run-pipeline.py` | CLI entry point for shell wrapper consumers |
| `scripts/run-claude-code.sh` | Shell wrapper — flag parsing only |
| `scripts/mcp_server.py` | MCP server — typed JSON-RPC tools over stdio |
| `scripts/compact-claude-stream.py` | Output parser — JSON stream → structured report |
| `scripts/profile_logger.py` | Profile record construction and JSONL append |
| `scripts/aggregate-profile-log.py` | Profile log aggregation and summarization |
| `scripts/jira-safe-text.py` | Markdown → Jira-safe plain text converter |
| `tests/run_tests.sh` | Test runner — pipeline, invocation, and compaction |
| `docs/shell-wrapper-reference.md` | Full CLI flag/env-var reference |
| `docs/jira-workflow.md` | Jira-specific delegation conventions |

## Profiling

**Prerequisite**: set `CLAUDE_DELEGATE_PROFILE_LOG` to enable recording. Each delegation appends one JSONL record:

```bash
export CLAUDE_DELEGATE_PROFILE_LOG=logs/profile.jsonl
```

**In conversation — just ask:**

> "generate profiling analysis"

The MCP tool returns a text summary: record count, success/error rate, model distribution, token usage, cache hit ratio, and cost.

**Programmatic access** via MCP:

```
// Text summary
aggregate_profile(profile_log_path="logs/profile.jsonl", format="text")
// → Records: 12  Success: 10  Error: 2
//   Cache hit ratio: 71.43%
//   Total cost: $2.20

// Machine-readable (for orchestrator consumption)
aggregate_profile(profile_log_path="logs/profile.jsonl", format="json")
// → { total_records: 12, success_count: 10, tokens: {...}, cost: {...} }
```

Shell fallback for the same operations:

```bash
export CLAUDE_DELEGATE_PROFILE_LOG=logs/profile.jsonl
./scripts/run-claude-code.sh "your prompt"
python3 scripts/aggregate-profile-log.py logs/profile.jsonl
```

Each record: model, effort, task type, token usage, cache hit ratio, cost, prompt character counts.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- `python3` (standard library only; `pip install mcp` optional for MCP server)
- Access to a Claude Code-compatible model

## License

MIT

</details>

<details>
<summary><b>中文</b></summary>

编排器负责规划和审查。本工具处理中间所有环节：分类任务、包装 prompt 模板、调用 Claude Code、压缩输出、返回结构化结果。wrapper 和 pipeline 均不批准变更 —— 这是编排器的职责。

## 这是什么 / 不是什么

| 本项目是... | 本项目不是... |
|---|---|
| AI-to-AI 编码工作流的委派层 | 全自主编码 agent |
| 标准化分类、调用和输出压缩的流水线 | 编排器规划和审查角色的替代品 |
| 传输无关：MCP server + shell wrapper，共享同一 pipeline | 「连接 DeepSeek 的 Claude Code」——模型后端可替换 |

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

### 验证

```bash
./scripts/run-claude-code.sh --flash 'hello from delegate'
```

配置正确的话，会看到一个包含 model、usage 和 cost 的简洁报告。

## Provider 设置（DeepSeek V4）

本项目默认使用 DeepSeek V4 模型以降低委派成本。如果你使用原生 Claude Code + Anthropic 模型，跳过本节，在每次调用时覆盖模型即可：`CLAUDE_DELEGATE_MODEL=claude-sonnet-4-6 ./scripts/run-claude-code.sh "你的 prompt"`

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

## 为什么选择这种架构

**成本效率。** 编排器处理规划和审查——这些任务受益于强推理模型。执行器处理代码编辑、测试运行和文件操作——这些任务用便宜模型即可胜任。你只需为需要的步骤支付 premium 费率。一次典型委派在 DeepSeek V4 上约 $0.28，而在 Anthropic 直接调用上约 $3+。

**结构性强制。** 委派循环强制清晰的关注点分离：先计划再编码，先审查再合并。编排器不能跳过计划——必须明确所有权边界和验证命令。执行器不能跳过审查——每个 diff 都回到编排器。这防止了"随便写写看行不行"的反模式。

**可审计性。** 每次委派生成 diff、简洁报告、token 用量摘要和成本记录。编排器审查每项变更。没有任何东西被静默接受。如果需要修正，你能看到每次修正之间的确切变更。

**模型专业化。** 规划需要广泛上下文和高层次推理。执行需要精确、快速、外科手术式编辑。没有哪个模型两者都擅长。委派让你将强规划模型（Codex、Opus）与快速执行模型（DeepSeek V4 Flash、Haiku）配对——各自做各自擅长的。

**安全边界。** 执行计划定义所有权边界：哪些文件可以接触，哪些命令可以运行。执行器不能静默重构代码库或还原无关变更。subagent 默认禁用以防止递归委派。

**渐进式信任。** 从 `--interactive` 开始，在执行前审查每个工具命令。一旦信任执行器输出质量，过渡到 `--bypass`。同一流水线适用于两者——只有权限模式改变。

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

## CLI 参考

| 标志 | 环境变量 | 效果 |
|------|----------|------|
| *(默认)* | | Pro 模型，quiet 输出，bypass 权限 |
| --pro / --flash | CLAUDE_DELEGATE_MODEL | 模型层级选择 |
| --effort low\|medium\|high\|max | CLAUDE_DELEGATE_EFFORT | 推理预算覆盖 |
| --quiet / --stream | CLAUDE_DELEGATE_OUTPUT_MODE | 输出格式（quiet: 简洁报告，stream: 原始 JSON） |
| --interactive | CLAUDE_DELEGATE_PERMISSION_MODE | 自动接受编辑，工具命令需确认 |
| --bypass | CLAUDE_DELEGATE_PERMISSION_MODE | 完全非交互（默认） |
| --mcp all\|none\|jira\|linear\|sequential-thinking | CLAUDE_DELEGATE_MCP_MODE | MCP server 加载 |
| --full-context | CLAUDE_DELEGATE_CONTEXT_MODE | 跳过 prompt 模板包装 |
| --allow-subagents | CLAUDE_DELEGATE_SUBAGENTS | 允许 Claude Code 生成 subagent |

环境变量等价项和完整细节：[docs/shell-wrapper-reference.md](docs/shell-wrapper-reference.md)。权限模式和安全：[SECURITY.md](SECURITY.md)。

## 组件

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 编排器契约 —— 委派循环、解析器、职责 |
| `CONTEXT.md` | 领域词汇表 —— 编排器、执行器、Pro vs Flash、MCP 术语 |
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

**前置条件**：设置 `CLAUDE_DELEGATE_PROFILE_LOG` 启用记录。每次委派追加一条 JSONL 记录：

```bash
export CLAUDE_DELEGATE_PROFILE_LOG=logs/profile.jsonl
```

**对话中直接问：**

> "生成 profiling analysis"

MCP 工具自动调用并返回文本摘要：记录数、成功/错误率、模型分布、token 用量、缓存命中率、成本。

**程序化访问**——通过 MCP：

```
// 文本摘要
aggregate_profile(profile_log_path="logs/profile.jsonl", format="text")
// → Records: 12  Success: 10  Error: 2
//   Cache hit ratio: 71.43%
//   Total cost: $2.20

// 机器可读（供编排器消费）
aggregate_profile(profile_log_path="logs/profile.jsonl", format="json")
// → { total_records: 12, success_count: 10, tokens: {...}, cost: {...} }
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

</details>
