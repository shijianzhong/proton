# Proton Agent Platform - 项目文档

## 项目概述

Proton 是一个基于 Microsoft Agent Framework 构建的**树形 Agent 编排平台**，用于构建多 Agent 协作系统。

### 核心特性

- **树形 Agent 架构**: 支持主 Agent 下挂多层子 Agent，形成层级结构
- **多平台集成**: 支持 Native、Coze、Dify、豆包、AutoGen 等多种 Agent 类型
- **插件系统**: 支持 MCP (Model Context Protocol)、Skill、RAG 等插件挂载
- **智能路由**: 支持顺序、并行、条件、交接、协调者等多种路由策略
- **深层嵌套保护**: 循环检测、深度限制、上下文压缩
- **REST API**: 完整的 FastAPI 服务支持
- **可视化编排**: Web UI 支持 Agent 关系编排（开发中）

---

## 项目结构

```
proton/
├── src/
│   ├── core/               # 核心模块
│   │   ├── models.py       # 数据模型定义 (Pydantic)
│   │   ├── agent_node.py   # Agent 节点和树结构
│   │   ├── context.py      # 执行上下文管理
│   │   └── tree_executor.py # 树形执行引擎
│   │
│   ├── adapters/           # Agent 适配器层
│   │   ├── base.py         # 适配器基类和工厂
│   │   ├── native.py       # 原生 Agent (OpenAI/Azure/Anthropic/Ollama)
│   │   ├── coze.py         # Coze 平台适配器
│   │   ├── dify.py         # Dify 平台适配器
│   │   ├── doubao.py       # 豆包平台适配器
│   │   └── autogen.py      # AutoGen 框架适配器
│   │
│   ├── plugins/            # 插件系统
│   │   ├── registry.py     # 插件注册中心
│   │   ├── mcp_plugin.py   # MCP 协议插件
│   │   ├── skill_plugin.py # Skill 技能插件
│   │   └── rag_plugin.py   # RAG 检索增强插件
│   │
│   ├── orchestration/      # 编排引擎
│   │   ├── router.py       # 路由策略实现
│   │   ├── aggregator.py   # 结果聚合器
│   │   └── workflow.py     # 工作流管理
│   │
│   └── api/                # REST API
│       └── main.py         # FastAPI 应用入口
│
├── config/
│   └── default.yaml        # 默认配置文件
│
├── examples/
│   └── basic_workflow.py   # 基础工作流示例
│
├── ui/                     # Web UI (Vite + TypeScript)
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── docs/
│   └── TECHNICAL_DESIGN.md # 技术设计文档
│
└── venv/                   # Python 虚拟环境
```

---

## 核心架构

### 1. 数据模型 (`src/core/models.py`)

#### Agent 类型 (`AgentType`)
```python
NATIVE = "native"      # 原生 agent-framework Agent
BUILTIN = "builtin"    # 内置可视化编辑 Agent
COZE = "coze"          # Coze 平台
DIFY = "dify"          # Dify 平台
DOUBAO = "doubao"      # 豆包平台
AUTOGEN = "autogen"    # AutoGen 框架
CUSTOM = "custom"      # 自定义适配器
```

#### 路由策略 (`RoutingStrategy`)
```python
SEQUENTIAL = "sequential"      # 顺序执行子 Agent
PARALLEL = "parallel"          # 并行执行所有子 Agent
CONDITIONAL = "conditional"    # 根据条件路由到特定子 Agent
HANDOFF = "handoff"            # 专家交接模式
HIERARCHICAL = "hierarchical"  # 任务分解模式
COORDINATOR = "coordinator"    # 协调者模式：父→子→父整合
ROUND_ROBIN = "round_robin"    # 轮询分发
LOAD_BALANCED = "load_balanced" # 负载均衡
```

#### 关键模型
- `ChatMessage`: 对话消息
- `AgentResponse`: Agent 响应
- `AgentConfig`: Agent 配置（含各平台配置）
- `WorkflowConfig`: 工作流配置
- `ExecutionEvent`: 执行事件（用于实时可视化）

### 2. Agent 节点 (`src/core/agent_node.py`)

#### `AgentNode` - 树形结构节点
```python
@dataclass
class AgentNode:
    id: str                          # 唯一标识
    name: str                        # 显示名称
    type: AgentType                  # Agent 类型
    config: AgentConfig              # 配置信息
    parent_id: Optional[str]         # 父节点 ID
    children: List[str]              # 子节点 ID 列表
    routing_strategy: RoutingStrategy # 子 Agent 调用策略
    routing_conditions: Dict[str, str] # 条件路由规则
    plugins: List[PluginConfig]      # 挂载的插件
    max_depth: int                   # 最大递归深度
    timeout: float                   # 执行超时
```

#### `AgentTree` - 树结构管理
- `add_node()` / `remove_node()`: 节点增删
- `get_children()` / `get_parent()`: 遍历
- `get_ancestors()` / `get_descendants()`: 祖先/后代查询
- `validate()`: 结构验证（检测孤立节点、无效引用）

### 3. 执行上下文 (`src/core/context.py`)

#### `CallChain` - 调用链追踪
```python
@dataclass
class CallChain:
    chain: List[str]       # 调用路径 [root_id, child_id, ...]
    depth: int             # 当前深度
    start_time: float      # 开始时间
    context_tokens: int    # 上下文 token 估算

    def check_cycle(agent_id) -> bool    # 循环检测
    def check_depth(max_depth) -> bool   # 深度检测
```

#### `ExecutionContext` - 执行上下文
- 上下文传递与压缩
- 超时管理
- 错误追踪
- Agent 输出存储

#### 自定义异常
- `CycleDetectedError`: 检测到循环调用
- `MaxDepthExceededError`: 超过最大深度
- `AgentExecutionError`: Agent 执行错误
- `WorkflowExecutionError`: 工作流执行错误

### 4. 树形执行器 (`src/core/tree_executor.py`)

#### `TreeExecutor` - 核心编排引擎
```python
class TreeExecutor:
    async def run(input_message, context) -> AgentResponse
    async def run_stream(input_message) -> AsyncIterator[AgentResponseUpdate]
    async def run_stream_with_events(...) -> AsyncIterator[ExecutionEvent]
```

执行流程:
1. 创建子上下文 (检查循环/深度)
2. 调用当前 Agent
3. 根据路由策略分发到子 Agent
4. 聚合结果返回

#### 路由策略实现
- `_route_sequential()`: 顺序执行，上下文传递
- `_route_parallel()`: 并行执行 `asyncio.gather()`
- `_route_conditional()`: 条件匹配路由
- `_route_coordinator()`: 协调者模式（子执行后父再次整合）

### 路由策略详细说明与使用场景

#### 1. Sequential (顺序执行)
```
Parent → Child1 → Child2 → Child3 → 结果
```
- **工作方式**: 子 Agent 按顺序逐个执行，前一个的输出会加入到后一个的上下文中
- **适用场景**:
  - 流水线处理（翻译→润色→校对）
  - 步骤依赖任务（分析→总结→格式化）
  - 信息逐步丰富

#### 2. Parallel (并行执行)
```
Parent → [Child1, Child2, Child3] → 聚合结果
```
- **工作方式**: 所有子 Agent 同时执行，执行完成后收集所有结果
- **适用场景**:
  - 独立子任务（多语言翻译）
  - 多角度分析（技术分析 + 市场分析 + 风险分析）
  - 提高效率的批量处理

#### 3. Conditional (条件路由)
```
Parent → [根据条件选择] → Child1 或 Child2 或 Child3
```
- **工作方式**: 根据父 Agent 输出内容匹配 `routing_conditions`，选择执行特定子 Agent
- **配置方式**: 在 `routing_conditions` 中设置 `"keyword == '技术'": "tech_agent_id"`
- **适用场景**:
  - 意图分类路由
  - 根据输入类型分发到专家

#### 4. Handoff (交接模式)
```
Parent → 选择专家 → Specialist Agent
```
- **工作方式**: 类似 Conditional，但更强调能力委托
- **适用场景**:
  - 复杂问题委托给专家
  - 多轮对话中的专家切换

#### 5. Coordinator (协调者模式)
```
Parent → [Child1, Child2] → Parent 整合 → 最终结果
```
- **工作方式**: 父 Agent 先发送任务给子 Agent，子 Agent 执行后返回，父 Agent 再次处理整合所有结果
- **适用场景**:
  - 多专家协作
  - 需要综合多方意见
  - 共识构建

#### 6. Hierarchical (层级分解)
```
Parent [分解任务] → [子任务1, 子任务2] → [聚合结果]
```
- **工作方式**: 父 Agent 将复杂任务分解为子任务，分发给子 Agent，最后聚合
- **适用场景**:
  - 复杂任务分解
  - 分治策略

### 在 UI 中配置路由策略

1. **创建 Agent 关系**: 在 Workflow Editor 中用连线将父 Agent 连接到子 Agent
2. **设置路由策略**: 双击父 Agent → Settings 标签 → 选择 Routing Mode
3. **保存配置**: 点击 Save 按钮

### 通过 API 配置路由策略

```python
# 创建带路由策略的 Agent
response = requests.post(
    f"http://localhost:8000/api/workflows/{workflow_id}/agents",
    json={
        "name": "Router Agent",
        "type": "builtin",
        "routing_strategy": "conditional",  # 设置路由策略
        "parent_id": parent_agent_id,
    }
)
```

---

## 适配器系统 (`src/adapters/`)

### 基类 `AgentAdapter`
```python
class AgentAdapter(ABC):
    async def initialize() -> None
    async def run(messages, context) -> AgentResponse
    async def run_stream(messages, context) -> AsyncIterator[AgentResponseUpdate]
    def get_capabilities() -> AgentCapabilities
    async def cleanup() -> None
```

### `AdapterFactory` - 适配器工厂
```python
AdapterFactory.register(AgentType.COZE, CozeAgentAdapter)
adapter = AdapterFactory.create(node)
```

### 已实现适配器

| 适配器 | 文件 | 说明 |
|--------|------|------|
| NativeAgentAdapter | `native.py` | OpenAI/Azure/Anthropic/Ollama |
| CozeAgentAdapter | `coze.py` | Coze 平台 (ByteDance) |
| DifyAgentAdapter | `dify.py` | Dify 平台 (chat/completion/workflow 模式) |
| DoubaoAgentAdapter | `doubao.py` | 豆包平台 |
| AutoGenAgentAdapter | `autogen.py` | AutoGen 框架 |

---

## 插件系统 (`src/plugins/`)

### `PluginRegistry` - 插件注册中心
```python
registry = get_plugin_registry()
await registry.register_mcp(mcp_config, agent_id)
await registry.register_skill(skill_config, agent_id)
await registry.register_rag(rag_config, agent_id)

tools = registry.get_tools_for_agent(agent_id)
```

### 插件类型

#### 1. MCP Plugin (`mcp_plugin.py`)
- 支持 stdio 和 HTTP 传输
- 自动发现 MCP 服务器工具
- 工具调用代理

#### 2. Skill Plugin (`skill_plugin.py`)
- Python 函数注册为工具
- 支持审批流程

#### 3. RAG Plugin (`rag_plugin.py`)
- 支持向量数据库: ChromaDB, Pinecone, Qdrant
- 支持文件源和 API 源
- 语义搜索工具

---

## 编排引擎 (`src/orchestration/`)

### Router (`router.py`)
路由条件类型:
- `KEYWORD`: 关键词匹配
- `REGEX`: 正则表达式
- `INTENT`: 意图分类
- `CUSTOM`: 自定义函数

### Aggregator (`aggregator.py`)
聚合策略:
- `CONCAT`: 拼接所有响应
- `MERGE`: 合并为单一响应
- `VOTE`: 投票选择
- `BEST`: 选择最佳响应
- `SUMMARIZE`: LLM 总结

### Workflow (`workflow.py`)
```python
manager = get_workflow_manager()
workflow = await manager.create_workflow("My Workflow", "Description", root_agent)
workflow.add_agent(child_agent, parent_id)
await workflow.initialize()
result = await workflow.run("Hello!")
```

---

## 配置文件 (`config/default.yaml`)

```yaml
server:
  host: "0.0.0.0"
  port: 8000

execution:
  max_depth: 10
  total_timeout: 300  # seconds
  layer_timeout: 60
  error_strategy: "fail_fast"

agent:
  model: "gpt-4"
  temperature: 0.7
  max_tokens: 4096
  provider: "openai"

plugins:
  mcp:
    enabled: true
    timeout: 30
  skill:
    enabled: true
  rag:
    enabled: true
    default_top_k: 5
```

---

## API 使用示例

### 创建客户支持工作流
```python
from src.core.models import AgentType, AgentConfig, NativeAgentConfig, RoutingStrategy
from src.core.agent_node import AgentNode
from src.orchestration.workflow import get_workflow_manager

# 创建分诊 Agent (根节点)
triage_agent = AgentNode(
    name="triage_agent",
    description="路由客户咨询到专家",
    type=AgentType.NATIVE,
    config=AgentConfig(
        native_config=NativeAgentConfig(
            instructions="分析客户问题并路由到合适的专家...",
            model="gpt-4",
        )
    ),
    routing_strategy=RoutingStrategy.CONDITIONAL,
)

# 创建专家 Agent (子节点)
refund_specialist = AgentNode(
    name="refund_specialist",
    description="处理退款请求",
    type=AgentType.NATIVE,
    parent_id=triage_agent.id,
    ...
)

# 设置路由条件
triage_agent.set_routing_condition("refund", refund_specialist.id)

# 创建工作流
manager = get_workflow_manager()
workflow = await manager.create_workflow("Customer Support", root_agent=triage_agent)
workflow.add_agent(refund_specialist, triage_agent.id)

# 执行
await workflow.initialize()
result = await workflow.run("我想退货")
```

### 混合平台工作流
```python
# Native 协调者
coordinator = AgentNode(
    name="coordinator",
    type=AgentType.NATIVE,
    routing_strategy=RoutingStrategy.PARALLEL,
    ...
)

# Coze 专家
coze_agent = AgentNode(
    name="coze_specialist",
    type=AgentType.COZE,
    config=AgentConfig(
        coze_config=CozeConfig(bot_id="xxx", api_key="xxx")
    ),
    parent_id=coordinator.id,
)

# Dify 工作流
dify_agent = AgentNode(
    name="dify_workflow",
    type=AgentType.DIFY,
    config=AgentConfig(
        dify_config=DifyConfig(app_id="xxx", api_key="xxx", mode="workflow")
    ),
    parent_id=coordinator.id,
)
```

---

## 环境变量

```env
# OpenAI
OPENAI_API_KEY=your_api_key

# Azure OpenAI (可选)
AZURE_OPENAI_ENDPOINT=https://xxx.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key

# Coze (可选)
COZE_BOT_ID=your_bot_id
COZE_API_KEY=your_api_key

# Dify (可选)
DIFY_APP_ID=your_app_id
DIFY_API_KEY=your_api_key

# 豆包 (可选)
DOUBAO_API_KEY=your_api_key
```

---

## 快速启动

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行示例
python examples/basic_workflow.py

# 启动 API 服务
python -m src.api.main
```

---

## 开发状态

- [x] 核心框架实现
- [x] 多平台适配器 (Native/Coze/Dify/豆包/AutoGen)
- [x] 插件系统 (MCP/Skill/RAG)
- [x] 路由策略 (Sequential/Parallel/Conditional/Coordinator)
- [x] REST API
- [x] 执行事件流（用于可视化）
- [ ] Web UI 编排界面
- [ ] 持久化存储
- [ ] 监控和可观测性

---

## 关键文件速查

| 功能 | 文件路径 |
|------|----------|
| 数据模型定义 | `src/core/models.py` |
| Agent 节点/树 | `src/core/agent_node.py` |
| 执行上下文 | `src/core/context.py` |
| 树形执行器 | `src/core/tree_executor.py` |
| 适配器基类 | `src/adapters/base.py` |
| 插件注册 | `src/plugins/registry.py` |
| 工作流管理 | `src/orchestration/workflow.py` |
| 路由器 | `src/orchestration/router.py` |
| 结果聚合 | `src/orchestration/aggregator.py` |
| 配置文件 | `config/default.yaml` |
| 使用示例 | `examples/basic_workflow.py` |
| 技术设计 | `docs/TECHNICAL_DESIGN.md` |

---

## 技术栈

- **Python 3.11+**
- **Pydantic**: 数据验证和序列化
- **FastAPI**: REST API 框架
- **aiohttp**: 异步 HTTP 客户端
- **asyncio**: 异步执行
- **Vite + TypeScript**: Web UI (开发中)
