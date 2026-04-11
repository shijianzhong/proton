# Proton Agent Platform

基于 Microsoft Agent Framework 的树形 Agent 编排平台。

## 特性

- **树形 Agent 架构**: 支持主 Agent 下挂多层子 Agent
- **多平台集成**: 支持 Native、Coze、Dify、豆包、AutoGen 等多种 Agent
- **插件系统**: 支持 MCP、Skill、RAG 等插件挂载
- **智能路由**: 支持顺序、并行、条件、交接等多种路由策略
- **深层嵌套保护**: 循环检测、深度限制、上下文压缩
- **REST API**: 完整的 API 支持，方便集成
- **可视化编排**: Web UI 支持 Agent 关系编排（开发中）

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
```

### 运行示例

```bash
# 运行基础示例
python examples/basic_workflow.py

# 启动 API 服务器
python -m src.api.main
```

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

```
┌─────────────────────────────────────────────────────────┐
│                      Web UI / API                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Orchestration Engine                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │           Tree-based Agent Executor              │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
      ┌─────────┐     ┌─────────┐     ┌─────────┐
      │ Agent 1 │     │ Agent 2 │     │ Agent N │
      │ (Root)  │     │ (Child) │     │ (Child) │
      └─────────┘     └─────────┘     └─────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│                    Adapter Layer                         │
│  Native | Coze | Dify | Doubao | AutoGen | Custom       │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│                    Plugin System                         │
│         MCP Tools | Skills | RAG Context                │
└─────────────────────────────────────────────────────────┘
```

## 路由策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| Sequential | 顺序执行子 Agent | 流水线处理 |
| Parallel | 并行执行所有子 Agent | 独立任务 |
| Conditional | 根据条件路由 | 分类任务 |
| Handoff | 专家交接 | 多专家协作 |
| Hierarchical | 任务分解 | 复杂任务 |

## 项目结构

```
proton/
├── src/
│   ├── core/           # 核心模块
│   │   ├── models.py   # 数据模型
│   │   ├── agent_node.py   # Agent 节点
│   │   ├── context.py  # 执行上下文
│   │   └── tree_executor.py  # 树形执行器
│   │
│   ├── adapters/       # Agent 适配器
│   │   ├── native.py   # 原生 Agent
│   │   ├── coze.py     # Coze 适配器
│   │   ├── dify.py     # Dify 适配器
│   │   ├── doubao.py   # 豆包适配器
│   │   └── autogen.py  # AutoGen 适配器
│   │
│   ├── plugins/        # 插件系统
│   │   ├── mcp_plugin.py   # MCP 插件
│   │   ├── skill_plugin.py # Skill 插件
│   │   └── rag_plugin.py   # RAG 插件
│   │
│   ├── orchestration/  # 编排引擎
│   │   ├── router.py   # 路由器
│   │   ├── aggregator.py   # 聚合器
│   │   └── workflow.py # 工作流管理
│   │
│   └── api/            # REST API
│       └── main.py     # FastAPI 应用
│
├── examples/           # 示例代码
├── config/             # 配置文件
├── tests/              # 测试
└── docs/               # 文档
```

## 开发计划

- [x] 核心框架实现
- [x] 多平台适配器
- [x] 插件系统
- [x] REST API
- [ ] Web UI 编排界面
- [ ] 持久化存储
- [ ] 监控和可观测性
- [ ] 更多适配器支持

## 运行期产物说明

- `data/skills/*` 属于运行时生成产物（例如自动生成 skill 包、安装缓存等），不应纳入代码版本管理。
- 仓库已默认忽略该目录下内容，仅保留 `data/skills/registry.json` 作为可选登记文件。
- 若需要备份运行时产物，建议通过对象存储或制品库单独归档，而不是直接提交到 Git。

## License

MIT License
