# Proton 自主进化能力需求（V2）

> 目标：在现有 ArtifactFactory/Portal 学习链路上，落地“可控自治”，避免“一步到位全自动”带来的质量与安全风险。  
> 原则：先增强已有能力，再新增闭环能力；先灰度可控，再全量自动。

---

## 1. 现状基线（代码事实）

当前系统并非“从零开始”，已具备以下基础能力：

- 学习循环与自动触发入口已存在：
  - `PortalService._extract_trajectory_bg()` 已在对话后触发 L2/L3 学习循环。
- Artifact 周期学习链路已存在：
  - `run_periodic_learning_cycle()` 已包含“轨迹聚类发现 + 自动修订触发”。
- 自动修订雏形已存在：
  - `auto_trigger_revisions()` 已支持基于指标退化创建子候选。
- 灰度与回滚框架已存在：
  - `decide_rollout_action()`、`transition_rollout_status()`、`configure_ab_routing()`、`route_candidate_ab_bucket()` 可用。
- 自动生成并安装 Skill 已存在：
  - `_generate_skill_code_via_llm()` + `_materialize_skill()` 已可生成并安装 skill 包。
- 事件流与前端链路已存在：
  - `PortalEventType` 具备 `portal_dispatch_*`、`workflow_execution_event` 等事件。

结论：V2 应聚焦“治理与闭环增强”，而非重造主链路。

---

## 2. V2 总览（修订后优先级）

| 编号 | 主题 | 优先级 | 周期 | 说明 |
|---|---|---|---|---|
| R1 | 受控版自主 Skill 创建 | P0 | 1-2 周 | 自动创建 + 灰度可用 + 安全闸 |
| R3 | 统一价值评估器（ValueAssessor） | P0 | 1 周 | 统一决策逻辑，替换分散阈值 |
| R2 | 失败驱动的即时修订闭环 | P1 | 1-2 周 | 基于执行错误触发受控修复 |
| R4 | 指标驱动自动灰度决策 | P1 | 1 周 | 在已有灰度框架上自动化 |
| R5 | ShareGPT 轨迹导出 | P1 | 1 周 | 为训练与回放评估提供数据出口 |
| R6 | 记忆驱动行为建议（建议优先） | P2 | 2-3 周 | 先建议后自动，避免误改行为 |
| R7 | 跨 Portal 技能迁移建议 | P2 | 2-3 周 | 先推荐再安装，不默认自动装 |

---

## 3. R1 受控版自主 Skill 创建（P0）

### 3.1 目标

不是“创建后不可用”，而是“创建后可控可用”：

- 自动创建并安装 skill。
- 默认灰度可用（例如仅 10%-20% 流量或仅指定 portal 生效）。
- 指标达标后再自动/半自动升级全量。

### 3.2 必做能力

1. 新增 `ValueAssessor`（可配置阈值，不写死常量）。
2. 新增 `auto_create_skill_controlled()`：
   - 生成代码 -> 静态安全扫描 -> 语法校验 -> 安装 -> 标记 rollout 初始状态。
3. 新增自治状态标记（metadata）：
   - `creation_mode = auto_controlled`
   - `rollout_guard = grayscale_only`
4. 新增事件：
   - `AUTO_SKILL_CREATED`（后端 SSE）
   - 前端展示自治创建通知卡片。

### 3.3 验收标准

- 相似模式满足阈值时，能自动创建并进入灰度状态。
- 不满足阈值时，仍走现有 candidate 通道，不破坏现网。
- 任一安全检查失败则阻断上线，产物保留为候选或 rejected。

---

## 4. R3 统一价值评估器（P0）

### 4.1 目标

将“候选决策”“自动创建决策”“后续修订优先级”统一到同一个评估器，减少逻辑漂移。

### 4.2 必做能力

1. `ValueAssessor.assess(signals, trajectory)` 输出统一结构：
   - `score`、`confidence`、`should_auto_create`、`reasons`、`risk_level`。
2. 在以下入口复用：
   - `decide_and_create_candidate()`
   - `run_periodic_learning_cycle()` 的自动创建分支
   - `auto_trigger_revisions()` 的优先级判定（可选）
3. 支持配置化阈值（YAML 或 env）。

### 4.3 验收标准

- 同一输入在三处入口给出一致决策。
- 评估输出可观测（日志 + metadata）。

---

## 5. R2 失败驱动即时修订（P1）

### 5.1 目标

在已有“统计退化触发修订”之外，增加“执行失败触发修订”。

### 5.2 设计约束

- 采用 `ToolExecutor` slice 扩展，不侵入所有 tool handler。
- 仅对白名单错误类型自动修复（如 `TypeError`、`ValueError`、`SyntaxError`）。
- 外部依赖类错误（网络/API）默认不自动修复。

### 5.3 验收标准

- 失败事件能触发分析并形成修订建议。
- 可修复错误能生成新 revision candidate 并进入灰度。
- 具备冷却时间和最大尝试次数，防止修复风暴。

---

## 6. R4 指标驱动灰度自动决策（P1）

### 6.1 目标

基于现有灰度/A-B框架，补齐自动执行器：

- `CONTINUE / FULL_RELEASE / ROLLBACK` 自动决策。
- 与回滚冻结窗口联动，避免频繁震荡。

### 6.2 验收标准

- 样本不足时保持灰度并给出原因。
- 指标显著提升时可自动全量。
- 指标显著劣化时自动回滚并进入冻结窗口。

---

## 7. R5 ShareGPT 导出（P1）

### 7.1 目标

提供轨迹导出能力，支撑离线评估/训练。

### 7.2 必做能力

- 新增导出方法：
  - `export_trajectories_as_sharegpt(filters, min_quality_score, limit)`
- 新增 API：
  - `POST /api/artifacts/export/sharegpt`
- 支持过滤：
  - `portal_id/workflow_id/date_range/user_id`

### 7.3 验收标准

- 导出 JSON 合法可下载。
- 抽样验证可回放基本对话结构。

---

## 8. R6/R7（P2）治理边界

### R6 记忆驱动行为改变

- V2 先做“建议优先”，不默认自动改系统行为。
- 自动应用仅限低风险偏好（如语言、输出长度）。

### R7 跨 Portal 知识迁移

- V2 先做“迁移推荐”，不默认自动安装到目标 portal。
- 安装需显式确认或策略白名单。

---

## 9. 非目标（V2 不做）

- 不做 RL 训练平台级改造。
- 不做无边界自动修复（不限错误类型/不限次数）。
- 不做“全自动创建即全量放开”。

---

## 10. 实施顺序建议

1. Week 1：R3（ValueAssessor）+ R1（受控自动创建主链）  
2. Week 2：R1（前端通知、治理开关）+ R4（自动灰度决策器）  
3. Week 3：R2（失败驱动修订）+ R5（导出）  
4. Week 4+：R6/R7（建议优先）  

---

## 11. 代码依据（关键证据）

- Portal 对话后学习触发：`src/portal/service.py` 的 `_extract_trajectory_bg()`  
- Artifact 周期学习：`src/artifacts/service.py` 的 `run_periodic_learning_cycle()`  
- 自动修订触发：`src/artifacts/service.py` 的 `auto_trigger_revisions()`  
- 灰度与回滚治理：`src/artifacts/service.py` 的 `decide_rollout_action()` / `transition_rollout_status()`  
- A/B 路由：`src/artifacts/service.py` 的 `configure_ab_routing()` / `route_candidate_ab_bucket()`  
- Skill 自动生成与安装：`src/artifacts/service.py` 的 `_generate_skill_code_via_llm()` / `_materialize_skill()`  
- 工具执行扩展点：`src/execution/tool_executor.py` 的 `ToolExecutionSlice` / `execute()`  
- Artifact API：`src/api/main.py` 的 `/api/artifacts/*` 系列端点  
- 前端事件消费基线：`ui/src/components/PortalChat.tsx`（`portal_dispatch_start`、`workflow_execution_event`）

---

## 12. 风险与保护

- 安全风险：自动生成代码必须经过危险调用扫描与沙箱校验。  
- 质量风险：所有自治能力默认灰度，不直接全量。  
- 稳定性风险：自动修复需限频、冷却、可回滚。  
- 可观测性要求：每次自治决策需记录 `why/score/action/outcome`。

