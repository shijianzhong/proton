# Proton Agent Platform

基于 Microsoft Agent Framework 的树形 Agent 编排平台。

## 特性

- **树形 Agent 架构与意图路由**: 支持主 Agent 下挂多层子 Agent，提供顺序、并行、条件、交接等多种路由策略。特别是**基于 LLM 的 Intent 路由**，能动态理解意图、重写子查询并并发分发给子 Agent，最后综合结果。
- **Super Portal (统一超级入口)**: 提供支持多轮对话的超级入口，具备长期记忆（强依赖 [MemPalace](https://github.com/MemPalace/mempalace)，支持按用户/全局的冷热记忆与快照）、多意图并发路由，并支持子 Portal 级联（Hierarchical Portals）路由分发。
- **自主进化与学习闭环 (Artifact Factory)**: 基于执行轨迹（Trajectory）自动聚类发现高频任务，通过 LLM 自动编写、沙箱校验并沉淀出可复用的 Python 技能（Skill）或工作流（Workflow），支持指标监控、灰度发布（A/B Test）及错误驱动的自动修复（Auto Revision）。
- **安全沙箱与策略治理 (Governance)**: 提供基于 Docker / Local 的 Python 代码执行沙箱，杜绝危险工具逃逸。内置多维度的 `PolicyEngine` 支持指令/URL/路径的黑白名单拦截，并支持 Human-in-the-loop (HITL) 审批机制与生成前安全扫描。
- **多平台集成与 IM 接入**: 适配 Native、Builtin、Coze、Dify、豆包、AutoGen 等多种 Agent 引擎，并通过 `IntegrationsGateway` 无缝对接微信、飞书、钉钉、Telegram 等主流 IM 渠道。
- **自然语言编排 (Copilot)**: 内置 Copilot 服务，支持通过自然语言对话动态生成、修改和评估 Agent 工作流，并广泛支持各种主流 LLM 模型（OpenAI, DeepSeek, Qwen, Zhipu, Anthropic 等）。
- **插件与技能系统**: 支持 MCP (Model Context Protocol)、Skill（可由 LLM 自动生成）、RAG 等插件挂载，生态扩展性强。
- **并发状态安全**: 针对深层嵌套与并行路由，提供严格的上下文快照隔离与深度限制，解决并发读写与死循环问题。

## 快速开始

### 安装

```bash
# 克隆项目
cd proton

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件:

```env
# OpenAI
OPENAI_API_KEY=your_api_key

# Azure OpenAI (可选)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key

# Coze (可选)
COZE_BOT_ID=your_bot_id
COZE_API_KEY=your_api_key

# Dify (可选)
DIFY_APP_ID=your_app_id
DIFY_API_KEY=your_api_key

# 豆包 (可选)
DOUBAO_API_KEY=your_api_key

# Hermes Agent (可选，作为外部 Agent 引擎接入)
# 1) 先在 hermes-agent 侧启用 API Server（见下方“外部引擎接入”）
# 2) Proton 侧可直接使用 Hermes 默认端口 8642（不需要额外配置）
#    如需自定义：
HERMES_AGENT_API_BASE=http://localhost:8642
# 可复用 Hermes 的 API_SERVER_KEY（也可用 HERMES_AGENT_API_KEY）
HERMES_AGENT_API_KEY=change-me-local-dev
HERMES_AGENT_MODEL=hermes-agent

# OpenClaw (可选，作为外部 Agent 引擎接入)
# 1) 先在 openclaw 侧开启 OpenAI compatible 端点（默认关闭）
# 2) Proton 侧默认使用 http://localhost:18789
OPENCLAW_API_BASE=http://localhost:18789
# 可复用 OpenClaw 的 OPENCLAW_GATEWAY_TOKEN / OPENCLAW_GATEWAY_PASSWORD
OPENCLAW_API_KEY=your_gateway_token_or_password
OPENCLAW_MODEL=openclaw/default
```

### 运行示例

```bash
# 运行基础示例
python examples/basic_workflow.py

# 启动 API 服务器
python -m src.api.main
```

## 外部引擎接入（Hermes-Agent / OpenClaw）

Proton 通过 Adapter 层支持将 **Hermes-Agent** 与 **OpenClaw** 作为“外部 Agent 引擎”接入，方式是调用它们的 **OpenAI-compatible HTTP API**。

### Hermes-Agent 接入

Hermes-Agent 官方提供 OpenAI-compatible API Server（默认端口 `8642`）。

1) 在 Hermes 侧启用 API Server（示例）

```bash
# hermes-agent 环境变量（在 hermes-agent 的 .env 或启动环境中设置）
export API_SERVER_ENABLED=true
export API_SERVER_KEY=change-me-local-dev

# 启动 gateway（会同时启动 API server）
hermes gateway

# 验证
curl http://localhost:8642/health
curl http://localhost:8642/v1/models
```

2) 在 Proton 侧使用

- 在 Web UI 里创建/编辑 Workflow 节点时，`Agent Type` 选择 `Hermes-Agent` 即可
- Proton 默认会连接 `http://localhost:8642/v1/chat/completions`（无需额外配置）
- 如需自定义，设置：
  - `HERMES_AGENT_API_BASE`（不带 `/v1`）
  - `HERMES_AGENT_API_KEY`（也可复用 `API_SERVER_KEY`）
  - `HERMES_AGENT_MODEL`（默认 `hermes-agent`）

### OpenClaw 接入

OpenClaw Gateway 同样提供 OpenAI-compatible HTTP API，但 **默认关闭**，需要先在 OpenClaw 侧开启。

1) 在 OpenClaw 侧开启 `/v1/chat/completions`

- 在 OpenClaw 配置中设置：
  - `gateway.http.endpoints.chatCompletions.enabled: true`
- 启动 gateway（默认端口 `18789`）：

```bash
openclaw gateway --port 18789

# 验证
curl http://localhost:18789/health
curl http://localhost:18789/v1/models
```

2) 在 Proton 侧使用

- 在 Web UI 里创建/编辑 Workflow 节点时，`Agent Type` 选择 `OpenClaw`
- Proton 默认会连接 `http://localhost:18789/v1/chat/completions`（无需额外配置）
- 如需自定义，设置：
  - `OPENCLAW_API_BASE`（不带 `/v1`；也可从 `OPENCLAW_GATEWAY_URL=ws://...` 自动推导）
  - `OPENCLAW_API_KEY`（也可复用 `OPENCLAW_GATEWAY_TOKEN` / `OPENCLAW_GATEWAY_PASSWORD`）
  - `OPENCLAW_MODEL`（默认 `openclaw/default`）

安全提示：OpenClaw 的 OpenAI-compatible HTTP 端点在 shared-secret 模式下是 **operator 级别能力**，请不要暴露到公网，并妥善管理 token/password。

### MemPalace MCP 自检

Proton 的长期记忆系统强依赖于开源项目 [MemPalace](https://github.com/MemPalace/mempalace)。如果你启用了 Portal 长期记忆（默认启用），建议在当前 Python 环境中确认 MemPalace 的安装与可用性并执行一次自检：

```bash
# 请确保已安装 mempalace
pip install mempalace

# 执行自检脚本
python scripts/check_mempalace_mcp.py
```

通过标准：
- 能 `import mempalace.mcp_server`
- 能执行 `python -m mempalace.mcp_server --help`
- `MemPalaceClient.ensure_ready()` 返回 ready 且发现工具列表

说明：生产/分发环境请保持 `mempalace_command=python`、`mempalace_args=["-m","mempalace.mcp_server"]`，并确保 Proton 与 MemPalace 安装在同一环境中。

### 飞书接入与配对

以下流程用于将 `Root Portal` 连接到飞书机器人（长连接模式）。

1. 飞书开放平台配置（企业自建应用）
- 事件接收方式：`长连接（WebSocket）`
- 订阅事件：`im.message.receive_v1`
- 应用发布：权限和事件配置完成后，务必“发布版本”

2. 飞书权限（建议最小可用集合）
- `contact:user.base:readonly`
- `im:chat`
- `im:message`
- `im:message.group_at_msg:readonly`
- `im:message.group_msg`
- `im:message.p2p_msg:readonly`

3. 在 Proton 里绑定飞书渠道
- 通过 Web UI 的 Portal 渠道设置填写 `app_id`、`app_secret` 并启用 `feishu`
- 或调用接口：

```bash
curl -X PUT http://127.0.0.1:8000/api/portals/{portal_id}/channels/feishu \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "config": {
      "app_id": "cli_xxx",
      "app_secret": "xxx"
    }
  }'
```

4. 生成配对码并在飞书私聊发送
- 配对码获取位置：
  - 在 Web UI 的飞书渠道面板点击“生成配对码”
  - 或调用接口，返回体里的 `pairing_code` 就是要发送给机器人的码

```bash
curl -X POST http://127.0.0.1:8000/api/portals/{portal_id}/channels/feishu/pairing \
  -H "Content-Type: application/json" \
  -d '{"ttl_seconds": 1800}'
```

- 用户在飞书里给机器人发送该码，成功后会收到“已配对成功，可以开始对话”
- 可通过接口查看当前绑定用户（`allowed_users`）：

```bash
curl http://127.0.0.1:8000/api/portals/{portal_id}/channels/feishu/allowlist
```

5. 关于重启与重新配对
- 服务重启后通常不需要重新配对
- 原因：成功配对后用户 `open_id` 会落到 `allowed_users` 并持久化
- 只有删除渠道绑定、清空存储或切换到新 portal 时，才需要重新配对

### API 使用

```bash
# 创建工作流
curl -X POST http://localhost:8000/api/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Workflow",
    "description": "A simple workflow",
    "root_agent": {
      "name": "coordinator",
      "description": "Main coordinator agent",
      "type": "native"
    }
  }'

# 添加子 Agent
curl -X POST http://localhost:8000/api/workflows/{workflow_id}/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "specialist",
    "description": "Specialist agent",
    "type": "native",
    "parent_id": "{root_agent_id}"
  }'

# 运行工作流
curl -X POST http://localhost:8000/api/workflows/{workflow_id}/run \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello, I need help!"
  }'
```

## 架构概览

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      Web UI / API / IM Connectors                       │
│           (Feishu, DingTalk, WeChat, Telegram, REST API, UI)            │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Super Portal                                  │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │
│ │ Intent Router│ │ MemoryEngine │ │ Copilot (NL) │ │ Trajectory Extr. │ │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Orchestration Engine (Tree-based)                   │
│         Sequential | Parallel | Conditional | Coordinator | Intent      │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
        ┌─────────┐           ┌─────────┐           ┌─────────┐
        │ Agent 1 │           │ Agent 2 │           │ Agent N │
        │ (Root)  │           │ (Child) │           │ (Child) │
        └─────────┘           └─────────┘           └─────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Adapter & Plugin Layer                          │
│    Native | Coze | Dify | Doubao | AutoGen | MCP Tools | RAG | Skills   │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             Execution & Governance (Sandbox & Policy Engine)            │
│   Docker/Local Backends | Approval/Deny Policies | Auto-Revision (HITL) │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│         Artifact Factory (Autonomous Evolution & Learning Loop)         │
│     Clustering -> Code Generation -> Verification -> A/B Rollout        │
└─────────────────────────────────────────────────────────────────────────┘
```

## 核心优势 (对比 OpenClaw & Hermes Agent)

基于本项目源码实现（非愿景规划），Proton 在工程架构上展现出区别于 OpenClaw 与 Hermes Agent 的独特优势。

**1. 复杂拓扑编排与并发状态隔离**  
区别于 OpenClaw / Hermes 偏向线性 Chat-Loop 或简单的 Sub-agent 派生，Proton 在底层实现了真正的 `Tree-based Executor`（见 `src/core/tree_executor.py`）。它原生支持 Sequential、Parallel、Conditional 和动态的 Intent 路由。更为关键的是，在进行并行任务分发时，Proton 通过深度拷贝机制实现了严格的 `Context Isolation`（上下文并发隔离），彻底解决了多智能体并行操作同一上下文时的竞态与污染问题。

**2. 生产级的自动化技能演进 (CI/CD for Skills)**  
虽然 Hermes Agent 也具备技能学习闭环，但 Proton 在 `src/artifacts/service.py` 中实现了一套极其完整的类似于 CI/CD 的工业级流水线。它不仅能通过轨迹聚类（Trajectory Clustering）自动使用 LLM 编写 Python 技能并在沙箱校验，还直接内置了**灰度发布（A/B Test Rollout）**与**错误驱动的自动修复（Auto Revision）**，这使得其在长期无人值守运行中的稳定性远超单纯的 prompt 记忆系统。

**3. 显式化的人机协作与策略治理引擎**  
OpenClaw 主要依赖工作区文件约束安全边界，而 Proton 在 `src/governance/policy_engine.py` 中抽象出了一套细粒度的企业级治理平面（Governance Plane）。其不仅支持正则级别的黑白名单（指令/URL/路径），还原生引入了明确的 **Human-in-the-loop (HITL)** 机制——当 Agent 试图执行高风险动作时，系统会自动挂起并触发审批流，这在当前强调安全的生产环境部署中是一项必不可少的底座能力。

**4. 零代码自然语言编排 (Copilot)**  
Proton 内置的 `copilot/service.py` 允许用户完全通过自然语言对话来生成、修改和调度底层的 Tree Workflow，极大降低了构建复杂多智能体协同链路的门槛。

**5. 原生全渠道连接网关**  
相比 OpenClaw 偏向本地网关的定位，Proton 的 `src/integrations/gateway.py` 已经是面向生产的云端多通道中心，它原生实现了对飞书、钉钉、微信、Telegram 的 WebSocket/Webhook 长短连接适配，做到了一次编排、全渠道就绪。

## 路由策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| Sequential | 顺序执行子 Agent，结果传递 | 流水线处理 |
| Parallel | 并行执行子 Agent，上下文状态隔离防竞态 | 独立子任务/批量搜集 |
| Conditional | 根据条件匹配路由 | 分类任务 |
| Handoff | 转移控制权/专家交接 | 多专家协作转移 |
| Coordinator | 汇总多 Agent 结果后再综合 | 综合汇报 |
| Intent | **LLM 意图识别 + 子查询重写 + 并发优先级路由** | 复杂任务动态分发（Super Portal 核心） |

## 项目结构

```text
proton/
├── src/
│   ├── core/           # 核心抽象 (Agent 节点、树形执行器、并发隔离上下文)
│   ├── execution/      # 执行平面与沙箱 (Local / Docker 后端、工具执行器)
│   ├── adapters/       # Agent 引擎适配器 (Native, Builtin, Coze, Dify, Doubao, AutoGen)
│   ├── plugins/        # 插件系统 (MCP 协议, Skill 挂载, RAG)
│   ├── portal/         # Super Portal (多轮对话, 长期记忆, 意图分发, Trajectory 采集)
│   ├── artifacts/      # 学习闭环与资产工厂 (自动代码生成, A/B 灰度发布, 错误驱动修复)
│   ├── copilot/        # 自然语言编排服务 (支持多模型、基于会话生成/修改 Workflow)
│   ├── integrations/   # 渠道接入网关 (飞书、钉钉、微信、Telegram)
│   ├── governance/     # 治理与策略平面 (Policy Engine 黑白名单拦截, HITL 人工审批机制)
│   ├── orchestration/  # 工作流调度与路由管理
│   ├── storage/        # 持久化存储层
│   └── api/            # FastAPI 接口
```

## 演进方向 (Code Plan)

Proton 正在向“长期运行的自主 Agent 平台 (Always-on & Autonomous)”演进，近期核心里程碑已达成：
- [x] **执行平面分层与治理**：落地 Docker / Local 隔离后端，支持基于 `PolicyEngine` 的黑白名单机制与 HitL (Human-in-the-loop) 审批拦截。
- [x] **上下文并发安全**：通过深度拷贝实现了 Parallel / Intent 并发状态隔离，防止状态竞态与污染。
- [x] **自我改进与学习闭环 (Artifact Factory)**：打通了从 Trajectory 聚类发现，到 LLM 生成真实 Skill 代码并沙箱校验，最后进行 A/B 灰度测试与指标追踪的完整闭环。并支持根据错误日志自动生成修订候选版。
- [x] **记忆与上下文治理 (Super Portal)**：引入 MemPalace 记忆层（冷热记忆、冲突合并、全局快照），支持多级 Portal 级联（Hierarchical Portals）。
- [x] **全渠道集成与 Copilot**：支持对接主流大模型，支持微信、飞书、钉钉、Telegram 多端无缝接入，支持自然语言编排 Agent Workflow。
- [ ] **回放与评测 (Replay & Benchmark)**：落地离线回归测试。

## 运行期产物说明

- `data/skills/*` 属于运行时生成产物（例如自动生成 skill 包、安装缓存等），不应纳入代码版本管理。
- 仓库已默认忽略该目录下内容，仅保留 `data/skills/registry.json` 作为可选登记文件。
- 若需要备份运行时产物，建议通过对象存储或制品库单独归档，而不是直接提交到 Git。

## License

MIT License
