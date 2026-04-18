# Proton 自主进化能力迭代需求

> **目标**：从"学习记录"升级为"学习成长"，让 Proton 不仅能知道"发生了什么"，还能做到"下次做得更好"。
> **对标**：Hermes-Agent 的自主 Skill 创建 + Atropos RL 训练 + Honcho 辩证建模
> **现状**：ArtifactFactory 已有 L1/L2/L3 Learning Loop + 轨迹聚类 + LLM 生成 Skill 代码，但仅在人工审批后触发

---

## 需求总览

| 需求 | 优先级 | 周期 | 依赖 | 状态 |
|------|--------|------|------|------|
| R1 自主 Skill 创建 | P0 | 1-2 周 | 现有 ArtifactFactory | 待开发 |
| R2 Skill 自改进闭环 | P0 | 1-2 周 | R1 | 待开发 |
| R3 执行后价值评估 | P0 | 1 周 | 现有 ArtifactFactory | 待开发 |
| R4 简化版 A/B 优化 | P1 | 2-3 周 | R1, R2 | 待开发 |
| R5 批量轨迹压缩导出 | P1 | 1 周 | 现有 ArtifactFactory | 待开发 |
| R6 记忆驱动行为改变 | P2 | 3-4 周 | R1, R3 | 待开发 |
| R7 跨 Portal 知识迁移 | P2 | 3-4 周 | R1, R6 | 待开发 |

---

## R1: 自主 Skill 创建

### 问题

当前流程：
```
执行轨迹 → 聚类发现 → 创建候选（仅统计指标）→ 人工审批 → LLM生成代码 → 安装Skill
                                                              ^^^ 人工卡点
```

Hermes 流程：
```
复杂任务完成 → 自主判断有价值 → 自动创建Skill → 下次直接使用
```

### 方案

在 `ArtifactFactoryService` 中新增**自主创建通道**，与现有的人工审批通道并存：

```
执行轨迹 → 价值评估 → 满足阈值 → 自动生成Skill → 灰度发布 → 监控指标
                         ↓
                   不满足阈值 → 继续走现有候选通道
```

### 具体改动

#### 1. 新增 `ValueAssessor` 价值评估器

**文件**：`src/artifacts/assessor.py`（新建）

```python
@dataclass
class AssessmentResult:
    should_auto_create: bool          # 是否自动创建
    confidence: float                  # 置信度 0-1
    reasons: list[str]                 # 决策理由
    suggested_skill_name: str          # 建议的 Skill 名称
    estimated_value_score: float       # 预估价值分数

class ValueAssessor:
    """基于执行轨迹评估是否值得自主创建 Skill"""

    async def assess(self, trajectory: list[dict], signals: dict) -> AssessmentResult:
        """
        评估逻辑：
        1. 检查重复执行次数（repeat_count >= 3）
        2. 检查成功率（success_rate >= 0.85）
        3. 检查工具调用复杂度（tool_call_count >= 4）
        4. 检查执行时长（avg_duration >= 2s，说明非 trivial）
        5. 检查是否有用户显式保存意图（L3 触发关键词）
        6. 综合打分
        """
```

**评估规则**：

| 条件 | 权重 | 说明 |
|------|------|------|
| `repeat_count >= 3` | 30% | 至少重复执行 3 次 |
| `success_rate >= 0.85` | 25% | 成功率高于 85% |
| `tool_call_count >= 4` | 15% | 涉及至少 4 个工具调用 |
| `avg_duration >= 2s` | 10% | 执行时长非瞬时 |
| `user_explicit_save == True` | 20% | 用户显式触发 L3 保存 |

综合分数 >= 0.7 时自动创建，否则继续走候选通道。

#### 2. 增强 `_generate_skill_code_via_llm`

**文件**：`src/artifacts/service.py`（修改现有方法）

现有实现仅生成基础代码，需要增强：

- 添加**参数类型推断**：从轨迹中推断输入参数的实际类型和约束
- 添加**错误处理模板**：生成的代码包含 try/except + 重试逻辑
- 添加**工具依赖声明**：自动声明需要哪些 MCP/Skill/RAG 依赖
- 添加**单元测试骨架**：生成至少 2 个测试用例

**改进前的 prompt**：
```
Generate a Python script for: {task_summary}
```

**改进后的 prompt**：
```
You are an expert Python developer creating a Proton Skill.

Task: {task_summary}
Observed tool calls from execution history:
{tool_call_trace}

Generate a complete Skill with:
1. Proper type hints for all parameters (infer from observed values)
2. Error handling with retry logic
3. Declare MCP/Skill dependencies
4. At least 2 unit test cases
5. Follow Proton's ExecutableTool interface

Parameters schema: {parameters_schema}
Expected output format: {output_schema}
```

#### 3. 新增 `auto_create_skill` 方法

**文件**：`src/artifacts/service.py`

```python
async def auto_create_skill(
    self,
    trajectory: list[dict],
    signals: dict,
    assessment: AssessmentResult,
) -> Optional[str]:
    """自主创建 Skill 的主流程

    步骤：
    1. 调用 _generate_skill_code_via_llm 生成代码
    2. 执行静态安全检查（禁止 os.system, eval, exec 等）
    3. 创建 Skill 包（zip + SKILL.md）
    4. 安装到 SkillRegistry
    5. 注册到 ArtifactCandidate（status='AUTO_CREATED'）
    6. 发送通知事件到执行上下文
    """
```

#### 4. 集成到现有学习循环

**文件**：`src/artifacts/service.py`（修改 `run_periodic_learning_cycle`）

```python
async def run_periodic_learning_cycle(self):
    """周期性学习循环，新增自主创建通道"""
    # 1. 聚类相似轨迹
    clusters = await self.discover_candidates_by_trajectory_clustering()

    for cluster in clusters:
        # 2. 价值评估
        assessment = await self.assessor.assess(
            trajectory=cluster.trajectory,
            signals=cluster.signals,
        )

        if assessment.should_auto_create:
            # 3. 自主创建
            skill_id = await self.auto_create_skill(
                trajectory=cluster.trajectory,
                signals=cluster.signals,
                assessment=assessment,
            )
            logger.info(f"[AutoSkill] Created skill '{skill_id}' autonomously")
        else:
            # 4. 走现有候选通道
            await self.decide_and_create_candidate(...)
```

#### 5. 前端：自主创建 Skill 通知

**文件**：`ui/src/components/PortalChat.tsx`

当收到 `AUTO_SKILL_CREATED` 事件时，显示通知卡片：

```
🤖 自动创建了新 Skill: "数据报表生成器"
   基于 5 次相似执行轨迹，成功率 92%
   [查看详情] [禁用] [编辑]
```

### 验收标准

1. 当相同模式执行 >= 3 次且成功率 >= 85% 时，自动创建 Skill
2. 创建的 Skill 可被后续工作流直接调用
3. 前端显示自主创建通知
4. 安全扫描拦截危险代码
5. 不满足阈值的模式继续走候选通道（不影响现有流程）

---

## R2: Skill 自改进闭环

### 问题

Hermes 能在 Skill 执行失败时自动优化版本。Proton 的 ArtifactFactory 有 `auto_trigger_revisions` 方法，但仅基于统计指标退化触发，不监听实时执行错误。

### 方案

新增**执行错误驱动的即时修订**通道：

```
Skill 执行 → 失败 → 错误分析 → 触发修订 → LLM 修复 → 灰度替换
```

### 具体改动

#### 1. 新增 `SkillErrorAnalyzer`

**文件**：`src/artifacts/error_analyzer.py`（新建）

```python
@dataclass
class ErrorAnalysis:
    error_type: str                  # 错误类型
    is_fixable_by_llm: bool          # 是否可被 LLM 修复
    context_for_fix: str             # 修复所需的上下文
    suggested_fix_prompt: str        # 修复建议（给人看的）

class SkillErrorAnalyzer:
    """分析 Skill 执行错误，判断是否可自动修复"""

    def analyze(self, execution_result: dict, skill_code: str) -> ErrorAnalysis:
        """
        分类错误：
        - TypeError/ValueError → 可修复（参数类型不匹配）
        - TimeoutError → 可修复（需要优化性能）
        - APIError/NetworkError → 不可修复（外部依赖问题）
        - SyntaxError → 可修复（LLM 生成代码的语法错误）
        """
```

#### 2. 新增 `auto_fix_skill` 方法

**文件**：`src/artifacts/service.py`

```python
async def auto_fix_skill(
    self,
    skill_id: str,
    error_context: dict,
    analysis: ErrorAnalysis,
) -> Optional[str]:
    """自动修复 Skill

    步骤：
    1. 构建修复 prompt（原代码 + 错误信息 + 修复建议）
    2. 调用 LLM 生成修复版本
    3. 执行静态验证（语法检查 + 安全检查）
    4. 如通过，创建新版本并灰度替换
    5. 记录修复历史到 ArtifactCandidate.revision_history
    """
```

#### 3. 集成到 ToolExecutor

**文件**：`src/execution/tool_executor.py`

在 `ToolExecutor.execute()` 方法中，当 Skill 执行失败时：

```python
result = await tool.handler(**args)

# 新增：失败时触发自动修复
if result.status == "error" and tool.source == "auto_created_skill":
    analysis = self.error_analyzer.analyze(result, tool.code)
    if analysis.is_fixable_by_llm:
        await self.artifact_factory.auto_fix_skill(
            skill_id=tool.skill_id,
            error_context=result.error_context,
            analysis=analysis,
        )
```

#### 4. 修订历史追踪

**文件**：`src/artifacts/service.py`（修改 `ArtifactCandidate`）

新增 `revision_history` 字段：

```python
@dataclass
class ArtifactCandidate:
    # ... 现有字段 ...
    revision_history: list[dict] = field(default_factory=list)
    # 每次修订记录：
    # {"version": 2, "trigger": "auto_fix", "error": "TypeError: ...", "fix_summary": "Added type check"}
```

### 验收标准

1. Skill 执行失败时自动分析错误类型
2. 可修复的错误自动触发 LLM 修复
3. 修复后创建新版本并灰度替换
4. 修订历史可追溯
5. 外部依赖错误不触发自动修复（避免无效重试）

---

## R3: 执行后价值评估

### 问题

当前的 `decide_and_create_candidate` 基于简单阈值判断，缺乏多维度价值评估。无法区分"值得自动创建的模式"和"仅需要记录的模式"。

### 方案

将 R1 中的 `ValueAssessor` 独立为一个通用组件，既用于自主创建，也用于候选决策优化。

### 具体改动

#### 1. 复用 `ValueAssessor`

R1 已实现，此处无需额外开发。仅在 `decide_and_create_candidate` 中调用：

```python
async def decide_and_create_candidate(self, ...):
    assessment = await self.assessor.assess(trajectory, signals)

    if assessment.should_auto_create:
        return await self.auto_create_skill(trajectory, signals, assessment)
    elif assessment.confidence > 0.4:
        # 走现有候选通道，但带有更丰富的评估信息
        return await self._create_candidate_with_assessment(assessment)
    else:
        # 仅记录，不创建候选
        return None
```

### 验收标准

1. `ValueAssessor` 被自主创建和候选决策两处共用
2. 评估规则可配置（通过 YAML 或环境变量）
3. 评估结果写入日志用于后续分析

---

## R4: 简化版 A/B 优化

### 问题

Hermes 有 Atropos RL 训练环境进行批量优化。Proton 没有 RL 微调能力，但已有 A/B 路由框架（`grayscale_release.py`）。可以在 A/B 基础上增加**指标驱动的自动优化**。

### 方案

利用现有灰度发布 + A/B 路由能力，新增：

```
新版本 Skill → 灰度发布（10% 流量） → 对比指标 → 自动全量 / 自动回滚
```

### 具体改动

#### 1. 增强灰度发布自动决策

**文件**：`src/artifacts/service.py`（修改灰度相关方法）

```python
async def evaluate_grayscale_release(self, candidate_id: str) -> dict:
    """评估灰度发布的效果，自动决定全量或回滚"""
    metrics = await self.get_candidate_metrics(candidate_id)
    control_metrics = await self.get_control_metrics(candidate_id)

    comparison = {
        "success_rate_delta": metrics.success_rate - control_metrics.success_rate,
        "latency_delta": metrics.p95_latency - control_metrics.p95_latency,
        "quality_score_delta": metrics.quality_score - control_metrics.quality_score,
    }

    # 自动决策规则
    if (comparison["success_rate_delta"] >= 0.05 and
        comparison["latency_delta"] <= 0.1 and
        metrics.sample_count >= 50):
        return {"decision": "FULL_RELEASE", "reason": "..."}
    elif comparison["success_rate_delta"] < -0.1:
        return {"decision": "ROLLBACK", "reason": "..."}
    else:
        return {"decision": "CONTINUE", "reason": "样本不足或差异不显著"}
```

#### 2. 自动执行决策

```python
async def auto_execute_grayscale_decision(self, candidate_id: str):
    """自动执行灰度决策"""
    decision = await self.evaluate_grayscale_release(candidate_id)

    if decision["decision"] == "FULL_RELEASE":
        await self.full_release(candidate_id)
        logger.info(f"[Grayscale] Auto full-released {candidate_id}")
    elif decision["decision"] == "ROLLBACK":
        await self.rollback(candidate_id)
        logger.warning(f"[Grayscale] Auto rolled-back {candidate_id}")
```

#### 3. 定时检查

在 `run_periodic_learning_cycle` 中增加灰度检查：

```python
# 检查所有灰度中的候选
for candidate in await self.list_grayscale_candidates():
    await self.auto_execute_grayscale_decision(candidate.id)
```

### 验收标准

1. 灰度发布后自动收集新版本与旧版本的指标对比
2. 样本 >= 50 且成功率提升 >= 5% 时自动全量
3. 成功率下降 >= 10% 时自动回滚
4. 决策记录写入日志

---

## R5: 批量轨迹压缩导出

### 问题

Hermes 支持批量轨迹生成 ShareGPT 格式数据，用于模型微调。Proton 有完整的轨迹记录但无导出能力。

### 方案

新增导出工具，将执行轨迹转换为 ShareGPT 格式：

```json
[
  {
    "messages": [
      {"role": "user", "content": "用户输入..."},
      {"role": "assistant", "content": "Agent 响应..."},
      {"role": "tool", "content": "工具调用..."}
    ]
  }
]
```

### 具体改动

#### 1. 新增导出方法

**文件**：`src/artifacts/service.py`

```python
async def export_trajectories_as_sharegpt(
    self,
    filters: dict = None,
    min_quality_score: float = 0.7,
    limit: int = 1000,
) -> str:
    """导出执行轨迹为 ShareGPT 格式

    参数：
    - filters: 过滤条件（workflow_id, portal_id, date_range）
    - min_quality_score: 最低质量分数
    - limit: 最大导出条数

    返回：
    - ShareGPT JSON 文件路径
    """
```

#### 2. 新增 API 端点

**文件**：`src/api/main.py`

```python
@app.post("/api/artifacts/export/sharegpt")
async def export_sharegpt(request: ExportRequest):
    """导出轨迹为 ShareGPT 格式"""
    factory = get_artifact_factory()
    file_path = await factory.export_trajectories_as_sharegpt(
        filters=request.filters,
        min_quality_score=request.min_quality_score,
        limit=request.limit,
    )
    return FileResponse(file_path, filename="trajectories_sharegpt.json")
```

### 验收标准

1. 导出的 JSON 符合 ShareGPT 格式规范
2. 支持按工作流/Portal/时间范围过滤
3. 仅导出高质量轨迹（默认质量分 >= 0.7）
4. API 端点可下载文件

---

## R6: 记忆驱动行为改变

### 问题

Hermes 的 Honcho 辩证建模能基于用户历史主动改变行为（"你偏好简洁输出"）。Proton 的 MemPalace 仅用于被动检索，不主动驱动决策。

### 方案

新增**记忆分析引擎**，从 MemPalace 中提取用户偏好，主动推荐和改变行为：

```
MemPalace 记忆 → 偏好分析 → 行为推荐 → 自动应用 / 用户确认
```

### 具体改动

#### 1. 新增 `MemoryBehaviorEngine`

**文件**：`src/portal/behavior_engine.py`（新建）

```python
@dataclass
class BehaviorInsight:
    type: str                          # 洞察类型
    description: str                   # 描述
    confidence: float                  # 置信度
    suggested_action: dict             # 建议的行动
    auto_apply: bool                   # 是否自动应用

class MemoryBehaviorEngine:
    """基于记忆分析用户偏好，主动改变行为"""

    async def analyze(self, portal_id: str) -> list[BehaviorInsight]:
        """
        分析逻辑：
        1. 从 MemPalace 查询该 Portal 的历史对话
        2. 分析输出长度偏好（用户是否总说"简洁一点"）
        3. 分析工具调用偏好（用户是否经常手动触发某工具）
        4. 分析路由策略效果（某策略是否总导致用户不满意）
        5. 生成洞察和建议
        """
```

#### 2. 洞察类型

| 洞察类型 | 示例 | 自动应用 |
|---------|------|---------|
| 输出长度 | "用户 80% 的反馈要求简洁" | 是 |
| 语言偏好 | "用户主要使用中文" | 是 |
| 工具偏好 | "用户经常手动调用搜索工具" | 否（推荐创建 Skill） |
| 路由效果 | "Conditional 路由成功率仅 40%" | 否（推荐切换策略） |
| 时间模式 | "用户每天 9AM 集中使用" | 否 |

#### 3. 集成到 Portal 对话

**文件**：`src/portal/service.py`

在 Portal 对话开始前：

```python
async def _apply_behavior_insights(self, portal_id: str):
    """应用行为洞察到当前对话"""
    insights = await self.behavior_engine.analyze(portal_id)

    for insight in insights:
        if insight.auto_apply:
            # 自动应用：如调整输出长度、语言
            self._apply_insight(insight)
        else:
            # 推荐给用户：如创建 Skill、切换路由
            self._queue_recommendation(insight)
```

#### 4. 前端：行为推荐卡片

**文件**：`ui/src/components/PortalChat.tsx`

当有推荐时显示：

```
💡 基于你的使用模式，建议：
- "数据分析"路由策略成功率较低，建议切换到 Coordinator 模式
- 你经常调用搜索工具，是否需要创建"深度搜索"Skill？
   [应用] [忽略]
```

### 验收标准

1. 周期性分析用户记忆并生成行为洞察
2. 安全的偏好（输出长度、语言）自动应用
3. 复杂建议（创建 Skill、切换策略）推送前端通知
4. 用户可一键应用或忽略建议

---

## R7: 跨 Portal 知识迁移

### 问题

Hermes 的知识是全局的。Proton 的 MemPalace 支持跨 Portal 共享记忆，但 ArtifactFactory 的 Skill 是 Portal 级别的，没有跨 Portal 推荐能力。

### 方案

```
Portal A 学会 Skill → 评估通用性 → 推荐给 Portal B/C → 确认或自动安装
```

### 具体改动

#### 1. 新增 `SkillTransferEngine`

**文件**：`src/artifacts/transfer_engine.py`（新建）

```python
@dataclass
class TransferRecommendation:
    skill_id: str                    # 源 Skill
    source_portal_id: str            # 来源 Portal
    target_portal_ids: list[str]     # 推荐的目标 Portal
    relevance_score: float           # 相关度
    reason: str                      # 推荐理由

class SkillTransferEngine:
    """跨 Portal Skill 迁移推荐"""

    async def discover_transfer_candidates(
        self,
        source_portal_id: str = None,  # None = 检查所有
    ) -> list[TransferRecommendation]:
        """
        发现可迁移的 Skill：
        1. 查找高频使用的 Skill（usage_count >= 10）
        2. 查找高成功率的 Skill（success_rate >= 0.9）
        3. 匹配目标 Portal 的工作流类型
        4. 计算相关度分数
        5. 生成推荐理由
        """
```

#### 2. 匹配逻辑

```python
def _calculate_relevance(
    self,
    skill: ArtifactCandidate,
    target_portal: PortalConfig,
) -> float:
    """计算 Skill 对目标 Portal 的相关度

    因素：
    - 工作流类型匹配度
    - 工具依赖可用性（目标 Portal 是否有所需 MCP/Skill）
    - 场景相似度（通过 MemPalace 向量检索）
    """
```

#### 3. 集成到学习循环

在 `run_periodic_learning_cycle` 中增加迁移检查：

```python
# 跨 Portal 迁移推荐
transfers = await self.transfer_engine.discover_transfer_candidates()
for rec in transfers:
    await self._notify_portal_transfer(rec)
```

#### 4. 前端：迁移通知

**文件**：`ui/src/components/PortalChat.tsx`

```
🔄 知识迁移建议：
"客服分诊"Skill 在 Portal A 中成功率 95%，
检测到 Portal B 有相似场景，是否安装？
   [安装到 Portal B] [忽略] [查看 Skill 详情]
```

### 验收标准

1. 自动识别高频高成功率的 Skill 作为迁移候选
2. 基于场景相似度推荐目标 Portal
3. 前端显示迁移建议，用户可一键安装
4. 安装后 Skill 在目标 Portal 可正常执行

---

## 实施路线图

```
Week 1-2:  R1 自主Skill创建 + R3 价值评估
           └─ 核心能力：让Proton自己创造新Skill

Week 2-3:  R2 Skill自改进闭环
           └─ 核心能力：失败时自动修复

Week 3-4:  R4 简化版A/B优化 + R5 轨迹导出
           └─ 核心能力：指标驱动优化 + 微调准备

Month 2:   R6 记忆驱动行为改变
           └─ 核心能力：从被动记忆到主动行为改变

Month 3:   R7 跨Portal知识迁移
           └─ 核心能力：全局知识共享
```

---

## 预期效果

实施后的能力跃迁：

| 维度 | 当前（学习记录） | 实施后（学习成长） |
|------|-----------------|-------------------|
| 新能力创建 | 人工创建 | 自主创建（R1） |
| 错误处理 | 记录失败 | 自动修复（R2） |
| 版本优化 | 人工判断 | 指标驱动（R4） |
| 记忆作用 | 被动参考 | 主动驱动（R6） |
| 知识范围 | Portal 级别 | 跨 Portal 共享（R7） |
| 微调能力 | 无 | 可导出轨迹（R5） |

**一句话总结**：
> 当前 Proton 的 Learning Loop 知道"发生了什么"，实施后将做到"下次自动做得更好"。
