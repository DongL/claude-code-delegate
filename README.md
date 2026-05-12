# Claude Code Delegate

> Let your AI orchestrator (Codex, Cursor, etc.) delegate implementation tasks to Claude Code — with DeepSeek V4 as the low-cost model backend.

<details open>
<summary><b>English</b></summary>

An orchestrator owns planning and review. This toolkit handles everything in between: classify the task, wrap it in a prompt template, invoke Claude Code, compact the output, and return a structured result. Neither the wrapper nor the pipeline approves changes — that's the orchestrator's job.

<p align="center">
  <img src="docs/assets/claude-code-delegate-architecture.svg" alt="Architecture" width="640">
</p>

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
pip3 install mcp  # optional: Python SDK dependency for scripts/mcp_server.py
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

**Cost efficiency.** The orchestrator handles planning and review — tasks that benefit from strong reasoning models. The executor handles code edits, test runs, and file operations — tasks that work well with cheaper models. You pay premium rates only for the steps that need them. A typical delegation costs ~$0.28 on DeepSeek V4. The same workload on premium-tier models (Claude Opus 4, GPT-5) would cost $3–$5 — a 10–20× difference.

**Structural enforcement.** The delegation loop enforces a clean separation: plan before you code, review before you merge. Every task gets classified automatically (flash for edits, pro for architecture), wrapped in a prompt template with coding guidelines and ownership boundaries, and returned as a structured compact report — not raw JSON. The orchestrator cannot skip the plan; the executor cannot skip review.

**Auditability.** Every delegation produces a diff, a compact report with token usage and cost, and an append-only profile log. Nothing is accepted silently. Correction passes show exactly what changed between iterations.

**Model specialization.** Planning calls for broad context and high-level reasoning. Execution calls for precision and speed. No single model is best at both. Delegation lets you pair a strong planning model (Codex, Opus) with a fast execution model (DeepSeek V4 Flash, Haiku) — $0.28/delegation vs. $3–$5 on premium-tier models.

**Safety boundary.** The execution plan defines which files may be touched and which commands may run. Subagents are disabled by default. A heartbeat confirms the executor is still alive during long tasks. The executor cannot silently refactor the codebase or revert unrelated changes.

**Consistent invocation.** Model, effort, permissions, and MCP config are identical across every delegation — no flag drift between tasks. Profile metadata accumulates for trend analysis over time.

**Progressive trust.** Start with `--interactive` to review every tool command. Graduate to `--bypass` once you trust the output quality. Same pipeline — only the permission mode changes.

Use `claude -p` for quick one-off answers. Use the delegation layer when you want consistent, reviewable, AI-to-AI execution with a paper trail.

## Cost & Context Efficiency

The delegation pipeline converts Claude Code's raw JSON stream into a compact report — the orchestrator sees a structured summary (classification, result text, token usage, cost), not megabytes of execution logs. This saves context window in every delegation.

Prompt caching amplifies the savings. Repeated delegation cycles reuse cached system prompts, instruction templates, and prior context across invocations. In one optimization run of two passes:

| Metric | Value |
|--------|-------|
| Fresh input tokens | ~150,000 |
| Cache-read tokens | ~1,890,000 |
| Output tokens | ~22,000 |
| Reused context served from cache | ~92% |

Dollar savings vary by provider cache pricing, model tier, task size, and cache hit behavior. The 92% reuse figure reflects a specific workload on a specific provider — not a guarantee.

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

## Quality Gates

CI/CD quality gates enforce merge and release confidence. The policy is defined in ADR 0003 (`docs/adr/0003-ci-cd-quality-gates.md`).

### Gate Tiers

| Tier | Trigger | Scope | External Services |
|------|---------|-------|-------------------|
| **Default CI** | Every PR and push to main | `bash scripts/quality-gate.sh` via `.github/workflows/quality-gate.yml` | None — fake claude, mock MCP |
| **Smoke** | Manual, pre-release | Human-supervised checks against live Jira, GitHub, Claude provider | Real tokens required |
| **Release** | Before tagging a release | `bash scripts/release-gate-report.sh` — aggregates default CI + smoke results | None for report; smoke results are inputs |

### Local Parity

Run the same command CI runs:

```bash
bash scripts/quality-gate.sh
```

This invokes `bash tests/run_tests.sh` by default. Override the test command for experimentation:

```bash
CLAUDE_DELEGATE_QUALITY_GATE_TEST_COMMAND="bash my-tests.sh" bash scripts/quality-gate.sh
```

CI runs the identical command — no divergence between developer machine and CI environment.

### CI Behavior

- **Trigger:** every PR against `main` and every push to `main`
- **Workflow:** `.github/workflows/quality-gate.yml`
- **Runner:** `ubuntu-latest` with only `actions/checkout@v4`
- **Heartbeat:** disabled (`CLAUDE_DELEGATE_HEARTBEAT_SECONDS=0`) for clean CI output
- **Result:** non-zero exit = gate failure = merge blocked

### Release Confidence Reporting

Generate a structured report before cutting a release:

```bash
bash scripts/release-gate-report.sh
```

The report records: gate status (PASS/FAIL), commit hash, tag, tests run, and residual risk. A failed gate prints `RELEASE BLOCKED` and exits non-zero.

### Sandbox and Isolation Assumptions

- **No real tokens.** Default CI requires no `ANTHROPIC_API_KEY`, `JIRA_API_TOKEN`, or `GITHUB_TOKEN`.
- **Fake claude on PATH.** The test suite prepends a fake `claude` script that records invocation arguments and returns valid JSON.
- **Mock MCP servers.** MCP integration tests use mock servers, not live Jira/Linear/GitHub.
- **Isolated Claude runtime.** The pipeline writes a minimal `settings.json` to `.claude-delegate/runtime/claude-config/` and sets `CLAUDE_CONFIG_DIR` to point there. No `~/.claude` coupling, no enabled plugins, no hooks.
- **No subagents in CI.** Subagents are disabled by default (`--disallowedTools Task Agent`).

### External-System Caveats

Real external-system integration is **out of default CI**:

- **Claude provider:** real model invocation is not tested in CI. The fake `claude` script validates the invocation path (args, env vars, flags) but not the provider response.
- **Jira:** issue transitions and comments are not performed in CI. Jira MCP operations use the `--mcp jira` mode with mock servers for CI tests.
- **GitHub release publishing:** not tested in CI. Release reports are local artifacts.

Smoke tests against live external systems are reserved for manual pre-release checks. A future secret-backed CI environment for live smoke tests requires a separate decision (see ADR 0003).

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

<p align="center">
  <img src="docs/assets/claude-code-delegate-architecture.svg" alt="架构图" width="640">
</p>

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
pip3 install mcp  # 可选：scripts/mcp_server.py 的 Python SDK 依赖
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

**成本效率。** 编排器处理规划和审查——这些任务受益于强推理模型。执行器处理代码编辑、测试运行和文件操作——这些任务用便宜模型即可胜任。你只需为需要的步骤支付 premium 费率。一次典型委派在 DeepSeek V4 上约 $0.28。同样的工作量在 premium 级模型（Claude Opus 4、GPT-5）上需 $3–$5——10–20 倍的差距。

**结构性强制。** 委派循环强制清晰的关注点分离：先计划再编码，先审查再合并。每个任务自动分类（flash 用于编辑，pro 用于架构），包装在包含编码规范和所有权边界的 prompt 模板中，返回结构化简洁报告——而非原始 JSON。编排器不能跳过计划；执行器不能跳过审查。

**可审计性。** 每次委派生成 diff、token 用量和成本的简洁报告，以及追加式画像日志。没有任何东西被静默接受。修正过程显示每次迭代之间的确切变更。

**模型专业化。** 规划需要广泛上下文和高层次推理。执行需要精确和速度。没有哪个模型两者都擅长。委派让你将强规划模型（Codex、Opus）与快速执行模型（DeepSeek V4 Flash、Haiku）配对——每次委派约 $0.28，而 premium 级模型需 $3–$5。

**安全边界。** 执行计划定义哪些文件可以接触，哪些命令可以运行。subagent 默认禁用。心跳确认执行器在长任务期间仍在运行。执行器不能静默重构代码库或还原无关变更。

**一致调用。** model、effort、permissions 和 MCP config 在每次委派中完全一致——不会出现任务间标志漂移。画像元数据随时间积累，用于趋势分析。

**渐进式信任。** 从 `--interactive` 开始，审查每个工具命令。一旦信任输出质量，过渡到 `--bypass`。同一流水线——只有权限模式改变。

快速回答用 `claude -p`。需要一致、可审查、有纸质记录的 AI-to-AI 执行时用委派层。

## 成本与上下文效率

委派流水线将 Claude Code 的原始 JSON 流转换为简洁报告——编排器看到的是结构化摘要（分类、结果文本、token 用量、成本），而非兆字节的执行日志。这节省了每次委派的上下文窗口。

提示缓存放大了这一节约效果。重复的委派循环复用缓存的系统提示、指令模板和先前上下文。一次优化运行（两轮）的数据：

| 指标 | 数值 |
|------|------|
| 新鲜输入 token | ~150,000 |
| 缓存读取 token | ~1,890,000 |
| 输出 token | ~22,000 |
| 从缓存提供的复用上下文 | ~92% |

节省的金额因 provider 缓存定价、模型层级、任务大小和缓存命中行为而异。92% 的复用率反映了特定工作负载在特定 provider 上的表现——并非保证值。

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
