# AgentLab 优化方案 — 基于 OpenAI "驾驭工程" 实践

> 来源：https://openai.com/index/harness-engineering/（Cloudflare 拦截，基于已知内容分析）
> 状态：待实施

---

## OpenAI 文章核心原则 → AgentLab 对标

### 1. 委托，不是自动化（Delegation, not Automation）

**OpenAI 做法**：AI 处理 80% 的重复劳动，人类处理 20% 的高价值决策。

**AgentLab 现状**：6 个大脑层 agent 串行，试图自动化所有阶段 → 每个阶段都调用 API，"自动化"成本高于"不做"。

**优化方案**：

```yaml
# 执行策略修改：大脑层 agent 默认不执行，仅在需要时触发
brain_policy:
  # 默认跳过所有大脑层 agent，由外部 AI 在上下文中隐式完成
  auto_execute_brain_agents: false
  
  # 仅在以下条件触发
  trigger_on:
    - external_ai_unavailable   # 外部 AI 离线时
    - audit_required             # 需要审计追踪时
    - context_window_full        # 外部 AI 上下文窗口不足时
    - cross_session              # 跨 session 恢复时（读 agent_docs）
```

**节省**：日常任务跳过大 脑层 = 6 次 API 调用 → 0 次。

---

### 2. 上下文最小化（Context Minimization）

**OpenAI 做法**：不要让 AI 看到不需要的文件，精确裁剪 prompt 输入。

**AgentLab 现状**：RepoScout/InterfaceMapper/TesterAuditor/Archivist 各自独立读取 25K-31K tokens 文件 → 大量重复。

**优化方案**：Agent 间上下文共享（不是冷启动）

```python
# 方案：给 run_task.py 新增 --context-from-call 参数
# 前一个 agent 的上下文通过 API 返回的 context_id 传递给下一个 agent
# 利用 DeepSeek/OpenAI 的 Prompt Caching 能力

# run_task.py 伪代码：
class AgentPipeline:
    def execute_chain(self, agents: list[str], task_id: str):
        ctx = None  # context_id from previous call
        for agent_name in agents:
            result = run_agent_model(
                plan, agent_name, output_path,
                context_cache_id=ctx,  # 复用缓存的系统提示和文件
            )
            ctx = result.context_id  # 传递到下一个 agent
```

**节省**：6 个 agent 不用各自加载相同的 system prompt + 配置文件 → 输入减少 ~15,000 tokens。

---

### 3. 并行化（Parallelization）

**OpenAI 做法**：独立任务同时运行，不要串行等待。

**AgentLab 现状**：7 个 agent 严格串行（Supervisor → RepoScout → ...），即使 RepoScout 和 InterfaceMapper 的输入完全独立。

**优化方案**：将无依赖的 agent 并行执行

```
旧流程 (串行, ~100秒):
  Supervisor → RepoScout → InterfaceMapper → CodexPromptGen → Coder → TesterAuditor → Archivist

新流程 (并行 + 合并, ~45秒):
  Supervisor ─┬→ RepoScout      ┐
              ├→ InterfaceMapper ├→ Coder → TesterAuditor → Archivist
              └→ CodexPromptGen  ┘
              (3个并行，互不依赖)
```

```bash
# run_task.py 新增并行执行命令
./agentlab.sh run-agents-parallel \
  --agents RepoScout,InterfaceMapper,CodexPromptGenerator \
  --project AgentLab --task-id task_0010 --execute
```

**节省**：等待时间从 ~100 秒 → ~45 秒。

---

### 4. 缓存复用（Caching & Reuse）

**OpenAI 做法**：LLM 调用天然支持 prompt caching，重复前缀不会被重复计费。

**AgentLab 现状**：AgentLab 的 `agent_runner.py` 没有利用 Prompt Caching。每个 agent 的 prompt 都是独立构造的 → 缓存命中率 0%。

**优化方案**：统一 Prompt 前缀

```python
# agent_runner.py: 所有 agent 共享同一个 system prefix
SHARED_PREFIX = """
You are an AgentLab agent working on project {project}.
Task: {task_id}
Repository: {repo_path}
"""

# 每个 agent 在 SHARED_PREFIX 后追加自己的角色模板
# DeepSeek/OpenAI 的 prompt caching 会命中 SHARED_PREFIX 部分
```

| 场景 | 旧方案 (无缓存) | 新方案 (缓存命中) |
|------|---------------|-----------------|
| Supervisor | 6,750 in full | 6,750 in full |
| RepoScout | 30,250 in full | 28,000 hit (共享前缀) + 2,250 miss |
| InterfaceMapper | 21,700 in full | 19,500 hit + 2,200 miss |
| 总输入计费 | ~169,350 | ~84,200 (省 50%) |

**这是 AgentLab 最大的单一优化机会。**

---

### 5. 模型分层（Model Tiering）

**OpenAI 做法**：简单任务用便宜模型 (GPT-4o-mini)，复杂任务用强模型 (o1/o3)。

**AgentLab 现状**：已部分实现（Supervisor=v4-pro，其余=v4-flash），但仍有改进空间。

**优化方案**：动态模型选择

```yaml
# routing_rules.yml 新增
dynamic_tiering:
  - condition: "task_scope == 'single_file'"
    supervisor_model: deepseek-v4-flash
    skip_agents: [RepoScout, InterfaceMapper, CodexPromptGenerator]
  - condition: "task_scope == 'multi_module'"
    supervisor_model: deepseek-v4-pro
    skip_agents: [CodexPromptGenerator]
  - condition: "task_scope == 'full_repo_refactor'"
    supervisor_model: deepseek-v4-pro
    all_agents: true
```

---

### 6. 度量驱动（Measurement-Driven）

**OpenAI 做法**：跟踪每次 AI 调用的成功率、token 消耗、修正轮次。

**AgentLab 现状**：`cost_ledger.yml` 有基础数据，但缺乏聚合分析。

**优化方案**：新增 `metrics` 命令

```bash
./agentlab.sh metrics --project AgentLab --last 10
# 输出：
# 平均 token/task: 185K
# AgentLab 模式节省: 24% vs full AI direct
# 缓存命中率: 0% ⚠️ (优化目标)
# 最多重复读取文件: agent_registry.yml (4次/task)
```

---

## 优先级排序

| 优先级 | 优化项 | 预期收益 | 实施难度 |
|--------|--------|----------|----------|
| 🔴 P0 | Prompt Caching 共享前缀 | 输入 token -50% | 低（改一个函数） |
| 🔴 P0 | 默认跳过大脑层 (外部 AI 存在时) | 零开销 | 低（改配置） |
| 🟡 P1 | 并行化无依赖 agent | 等待时间 -50% | 中（新增 CLI 命令） |
| 🟡 P1 | 动态模型选择 | 小任务 cost -80% | 中（改 task_router） |
| 🟢 P2 | 上下文 ID 传递 | 缓存命中率 +40% | 高（依赖 API 支持） |
| 🟢 P2 | Metrics 聚合面板 | 可见性 | 低（加 Web UI Tab） |

---

## 最简实施：一键优化

如果只做两件事，AgentLab 就大幅改善：

**1. `execution_policy.yml` 改一行：**

```yaml
brain_policy:
  auto_execute_brain_agents: false  # 默认不执行大脑层
```

**2. `agent_runner.py` 共享 prompt 前缀：**

所有 agent 调用时前 2,000 tokens 完全相同 → DeepSeek 自动命中缓存，输入 token 减半。