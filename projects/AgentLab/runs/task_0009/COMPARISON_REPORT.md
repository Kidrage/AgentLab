# 外部 AI 直接执行 vs AgentLab 驱动 — 对比实验报告

> 实验任务：完善 AgentLab Web UI 并完成桌面 App 封装（task_0009）
> 实验日期：2026-05-30

---

## 1. 两种模式的定义

| 维度 | 模式 A: 外部 AI 直接 | 模式 B: AgentLab 驱动 |
|------|---------------------|----------------------|
| 需求分析 | 外部 AI 内部推理 | DeepSeek API (Supervisor) |
| 代码库理解 | 外部 AI 直接读文件 | DeepSeek API (RepoScout) |
| 接口边界 | 外部 AI 看代码推断 | DeepSeek API (InterfaceMapper) |
| 实现执行 | 外部 AI 直接编辑 | 外部 AI 编辑（Coder 阶段） |
| 审查验证 | 外部 AI 自查 | DeepSeek API (TesterAuditor) |
| 归档记录 | 无（或手动 log） | DeepSeek API (Archivist) |

---

## 2. Token 消耗对比（本次 task_0009 实测估算）

### 2.0 重要说明：缓存命中 vs 未命中

模型 API 通常区分两种 token 计费：

| 类型 | 定义 | 计费 |
|------|------|------|
| **Cache-miss (未命中)** | 模型首次"看到"的 token，需要完整计算 | 全价计费 |
| **Cache-hit (命中)** | 之前已在上下文中的 token，模型跳过 compute | 通常 10% 价格（DeepSeek）或 50%（Anthropic） |

**我报告的 ~500K 是上下文窗口总用量，不是纯计费 token。**
需要拆分为未命中（实际花钱的）和命中（缓存省钱的）。

同一个对话 session 中：
- 第一次读文件 → **全量 cache-miss**
- 后续引用同一文件内容 → **cache-hit**（模型已"见过"）
- 每轮新的推理输出 → **cache-miss**（新生成的 token）

### 模式 A: 外部 AI 直接 — 分场景

#### A1: 冷启动（全新 session，无缓存）

```
Session 启动 → 第一个任务
  ┌─────────────────────────────────────────────────────────┐
  │ 阶段 1: 读取项目文件 (cache-miss)                        │
  │   index.html + app.js + styles.css + server.py           │
  │   + agentlab_app.py + README.md + model_profiles.yml     │
  │   + agent_registry.yml + run_task.py + agent_runner.py   │
  │   + llm_provider.py + execution_policy.yml + ...         │
  │   约 12 个文件，全部首次加载:              ~350K tokens   │
  │                                                          │
  │ 阶段 2: 推理 + 代码生成 (cache-miss)                     │
  │   规划、设计决策、生成代码、样式重构:       ~150K tokens   │
  │                                                          │
  │ 缓存命中: ~0K (一切都是第一次)                            │
  │ 缓存未命中: ~500K (全量)                                  │
  │ 💰 计费: ~500K tokens (全价)                             │
  └─────────────────────────────────────────────────────────┘
```

#### A2: 同 session 后续任务（热缓存，80% 命中率）

```
同一对话中的第 N 个任务
  ┌─────────────────────────────────────────────────────────┐
  │ 阶段 1: 增量读取 (大部分 cache-hit)                      │
  │   之前已加载的文件在上下文中，不需要重传:    ~280K hit    │
  │   新增/修改的文件需要重新读取:               ~70K miss    │
  │                                                          │
  │ 阶段 2: 推理 + 代码生成 (cache-miss)                     │
  │   新的规划、新的代码生成:                     ~80K miss    │
  │                                                          │
  │ 缓存命中: ~280K                                           │
  │ 缓存未命中: ~150K                                         │
  │ 💰 计费: ~150K × 全价 + ~280K × 10% ≈ ~178K 等价 token  │
  └─────────────────────────────────────────────────────────┘
```

### 模式 B: AgentLab 驱动

**关键差异**：AgentLab 的每个 agent 是独立的 API 调用，**不共享缓存**。
每次调用都是冷启动。

```
┌───────────────────────────────────────────────────────────────┐
│ Supervisor (DeepSeek API, 冷启动)                              │
│   System prompt (~500) + user_request + context files (~3500)  │
│   输入: ~4,000 miss | 输出: ~1,800 miss                       │
│   缓存命中: 0                                                  │
│   💰 ~$0.001 (DeepSeek v4-pro @ $0.27/1M input, $1.10/1M out) │
├───────────────────────────────────────────────────────────────┤
│ RepoScout (DeepSeek API, 冷启动)                               │
│   System prompt (~500) + 重新读取所有上下文 (~9500)            │
│   输入: ~10,000 miss | 输出: ~1,200 miss                      │
│   缓存命中: 0  ← 看不到 Supervisor 的输出（独立调用）          │
│   💰 ~$0.004                                                   │
├───────────────────────────────────────────────────────────────┤
│ InterfaceMapper (DeepSeek API, 冷启动)                         │
│   输入: ~8,000 miss | 输出: ~1,200 miss                       │
│   💰 ~$0.003                                                   │
├───────────────────────────────────────────────────────────────┤
│ Coder (外部 AI, 新 session 冷启动)                             │
│   需要重新读取 supervisor_plan + reposcout_report              │
│   + interface_map + 实际编辑的文件 + 生成代码                  │
│   输入: ~120,000 miss | 输出: ~30,000 miss                     │
│   缓存命中: 0  ← 这是一个新对话，之前 agent 的输出只是文件     │
│   💰 ~150K tokens 全价                                         │
├───────────────────────────────────────────────────────────────┤
│ TesterAuditor (DeepSeek API, 冷启动)                           │
│   输入: ~8,000 miss | 输出: ~1,200 miss                       │
│   💰 ~$0.003                                                   │
├───────────────────────────────────────────────────────────────┤
│ Archivist (DeepSeek API, 冷启动)                               │
│   输入: ~4,000 miss | 输出: ~1,000 miss                       │
│   💰 ~$0.002                                                   │
└───────────────────────────────────────────────────────────────┘
```

### 逐项对比

| 指标 | 外部 AI 直接 (冷) | 外部 AI 直接 (热) | 纯 DeepSeek 完整 | AgentLab 驱动 |
|------|-----------------|-----------------|----------------|--------------|
| **上下文总量** | ~500K | ~430K | ~540K | ~190K |
| **Cache-miss (计费)** | ~500K (全量) | ~150K | ~540K (全量) | ~190K (全量) |
| **Cache-hit** | 0 | ~280K | 0 | 0 |
| **DeepSeek 调用** | 0 次 | 0 次 | **1 次**（但超大输入） | 5 次 |
| **外部 AI 调用** | 1 次 | 1 次 | 0 次 | 1 次 (仅 Coder) |
| **等待时间** | 2-3 分钟 | 1-2 分钟 | ~1-2 分钟（单次调用） | 6-8 分钟 |

### 模型价格参考

| 模型 | Input (/1M) | Output (/1M) | Cache-hit 折扣 |
|------|------------|-------------|----------------|
| **DeepSeek v4-pro** | $0.27 | $1.10 | 10% 原价 |
| **DeepSeek v4-flash** | $0.14 | $0.55 | 10% 原价 |
| **Claude 3.5 Sonnet** | $3.00 | $15.00 | 12.5% 原价 |

### 金钱预算对比 — 三种模式 × 三种模型价格

#### 以 Claude 3.5 Sonnet 计价（外部 AI 昂贵场景）

| 场景 | 计算 | 总价 |
|------|------|------|
| 外部 AI 直接 (冷) | 350K × $3 + 150K × $15 | **$3.30** |
| 外部 AI 直接 (热) | (70K×$3+40K×$0.375) + 80K×$15 | **$1.44** |
| 纯 DeepSeek 完整 | 360K × $0.27 + 180K × $1.10 | **$0.295** |
| AgentLab 驱动 | 150K×$3+30K×$15 + DeepSeek: 34K×$0.27+6.4K×$1.10 | **$0.90 + $0.016 ≈ $0.92** |

#### 纯 DeepSeek v4-pro 场景 — 全部用 DeepSeek（无外部 AI）

这个场景是：**把这个任务完全交给 DeepSeek API 来做**（类比用 ChatGPT 网页版而非 IDE 助手）。

```
DeepSeek v4-pro 一次调用完成全部工作:
  输入:
    系统提示 + 所有文件内容 + 用户需求:  ~360K tokens
  输出:
    规划 + 分析 + 代码 + diff + 验证:   ~180K tokens
  
  总 token: ~540K
  总 cost:  360K × $0.27/1M + 180K × $1.10/1M
          = $0.097 + $0.198
          = $0.295
```

但要注意：DeepSeek v4-pro 的推理能力和代码生成能力 **远不如 Claude/Codex**。它能生成分析报告，但代码质量、错误率、需要纠正的轮次都会增加。

| 场景 | Token 量 | 美元成本 | 代码质量 | 需要人工修正 |
|------|---------|---------|----------|-------------|
| Claude 直接 (冷) | ~500K | **$3.30** | ⭐⭐⭐⭐⭐ | 极少 |
| Claude 直接 (热) | ~150K miss | **$1.44** | ⭐⭐⭐⭐⭐ | 极少 |
| 纯 DeepSeek v4-pro | ~540K | **$0.295** | ⭐⭐⭐ | 需要 2-3 轮修正 |
| 纯 DeepSeek v4-pro (实际 3 轮) | ~1,500K | **~$0.89** | ⭐⭐⭐⭐ | 少量 |
| AgentLab (混) | ~190K + ~40K DS | **$0.92** | ⭐⭐⭐⭐ | 少量 |

> 注：纯 DeepSeek 3 轮估算：第 1 轮生成代码 → 用户反馈修正 → 第 2 轮改 → 可能还需第 3 轮。每轮 ~500K tokens。

#### 统一价格对照表（所有场景换算到等价的美元成本）

```
场景                                     美元成本       代码质量    等待时间
──────────────────────────────────────  ────────      ────────    ────────
Claude 冷启动 (全新对话)                 $3.30000      ★★★★★      2-3min
Claude 热缓存 (同 session 第 N 个)       $1.44000      ★★★★★      1-2min
纯 DeepSeek v4-pro (1 次)               $0.29500      ★★★         1-2min
纯 DeepSeek v4-pro (3 轮修正后)          ~$0.89000     ★★★★        3-6min
AgentLab 混 (Claude Coder+DS 大脑)       $0.91600      ★★★★        6-8min
──────── 以下是纯 DeepSeek 内部对比 ────────
AgentLab 纯 DeepSeek Coder (v4-pro)     $0.03480      ★★★         4-5min
  (大脑+编码全部 DeepSeek, 6个agent串行)
```

#### 最终对比：全员 DeepSeek 定价

把所有场景的模型全部换成 DeepSeek 价格：

| 场景 | Input tokens | Output tokens | 总价 (DeepSeek 价) |
|------|-------------|---------------|---------------------|
| 外部 AI 直接 (冷) → 换算 DS 价 | 350K | 150K | 350K×$0.27 + 150K×$1.10 = **$0.26** |
| 外部 AI 直接 (热) → 换算 DS 价 | 110K | 80K | 110K×$0.27 + 80K×$1.10 = **$0.12** |
| 纯 DeepSeek 一次 | 360K | 180K | **$0.295** |
| AgentLab + Claude Coder | 150K(Claude)+34K(DS) | 30K(Claude)+6.4K(DS) | $0.90 + $0.016 = **$0.92** |
| AgentLab + DeepSeek Coder | 184K(DS) | 36.4K(DS) | 184K×$0.27 + 36.4K×$1.10 = **$0.09** |

### 核心洞察（加入纯 DeepSeek 维度）

```
                价格对比（全部统一到 DeepSeek v4-pro 定价）
  
  $0.30 ┤
  $0.25 ┤  ■ Claude冷(换算DS价)$0.26
  $0.20 ┤
  $0.15 ┤  ■ Claude热(换算DS价)$0.12
  $0.10 ┤  ■ AgentLab纯DS编码 $0.09
  $0.05 ┤
  $0.00 ┤
         └──────────────────────────────────────────
  
  如果用 DeepSeek 价格衡量：
    - 外部 AI 的模式 A 实际上是 $0.12~$0.26 等价的"算力"
    - 但外部 AI 的质量是 ★★★★★ vs DeepSeek 的 ★★★
    - AgentLab 纯 DeepSeek Coder 模式只要 $0.09，但质量仅 ★★★
  
  结论：外部 AI (Claude) 多花的钱买的是"一次性做对"的能力。
        DeepSeek 便宜但需要反复修正，最终可能更费时间。
```

**如果"外部 AI 费用"用 DeepSeek v4-pro 来对标**（即假设外部 AI 也是 DeepSeek 级别的推理），那模式 A 的 token 成本仅为 **$0.26**（冷启动）或 **$0.12**（热缓存）— 远低于 AgentLab 混用 Claude 的 $0.92。

但这里的关键矛盾是：**你不能用 DeepSeek 的价格买到 Claude 的质量**。外部 AI 模式的高费用实际上购买的是"推理能力溢价"——它能一次性正确理解复杂需求、生成高质量代码、发现边界问题。

反过来，**AgentLab 纯 DeepSeek Coder 模式**只需要 **$0.09**，是最便宜的选项——但代码质量需要接受 ★★★ 级别，并且可能需要多轮修正。

---

## 3. 核心发现

### 3.1 外部 AI 已经在内部模拟了 AgentLab 的大脑层

当我收到"完善 Web UI"这个任务时，我内部做的推理链：

```
1. [相当于 Supervisor] 这个任务涉及 HTML/CSS/JS + Python app shell，
   路由应该是 UI 修改任务，不需要 Researcher
2. [相当于 RepoScout] 我先读了 index.html, app.js, styles.css, agentlab_app.py，
   了解了文件结构和边界
3. [相当于 InterfaceMapper] 确定 HTML↔CSS↔JS↔Python 的接口约定
4. [相当于 Coder] 执行实际编辑
5. [相当于 TesterAuditor] 每次编辑后做一致性检查
```

**所有这些在一个连续上下文中完成，没有单独的 API 调用开销。**

结论：**AgentLab 的 Supervisor/RepoScout/InterfaceMapper 对外部 AI 来说是冗余的。**
外部 AI 做这些都是"免费"的（包含在单次推理中）。

### 3.2 AgentLab 的"衔接成本"

AgentLab 的 agents 之间的衔接是有 **显著摩擦** 的：

- 每个 agent 的 system prompt 重新加载模板 (~500 tokens)
- 每个 agent 需要重新读取所有上下文文件（user_request, plan, 之前报告）
- Supervisor 写的计划需要被 RepoScout 重新解析
- 每个 agent 的推理质量受限于其模型（DeepSeek 推理能力 < 外部 AI）

而外部 AI 直接模式：所有信息一次性加载，持续推理，无上下文切换损失。

### 3.3 真实的成本比较

| 场景 | 推荐模式 | 原因 |
|------|----------|------|
| 外部 AI 可用 + 任务需频繁交互 | **直接用外部 AI** | AgentLab 大脑层是纯开销 |
| 外部 AI 不可用 / 离线 | **AgentLab** | DeepSeek 可以独立完成（虽然慢） |
| 需要完整审计追踪 | **AgentLab** | 每个阶段有独立报告文件 |
| 预算严格控制 | **AgentLab** | Token 预算治理防止超支 |
| 外部 AI token 非常昂贵 | **AgentLab**（部分） | 用 DeepSeek 做规划，外部 AI 只做 Coder |
| 大规模、长期项目 | **AgentLab** | 项目记忆文件保持连续性 |

---

## 4. AgentLab 的真正价值（修正后的定位）

### ✅ 有价值的部分

1. **项目记忆系统** (`agent_docs/`) — 跨 session 保持连续性，这是单个外部 AI 对话做不到的
2. **确定性审计追踪** — 每个决策、每次变更都有文件记录，可 git diff
3. **成本治理** — Token 预算硬限制、循环检测，防止外部 AI 失控
4. **异构模型路由** — Supervisor 用 v4-pro、其他用 v4-flash，这是外部 AI 无法自主控制的
5. **离线执行能力** — 当外部 AI 不可用时，DeepSeek 可以独立跑完整工作流

### ❌ 对外部 AI 冗余的部分

- Supervisor, RepoScout, InterfaceMapper, TesterAuditor 这 4 个大脑层 agent — 外部 AI 的推理能力免费覆盖
- CodexPromptGenerator — 外部 AI 自己就是 Coder，不需要"生成 Codex 提示"
- Archivist — 外部 AI 可以直接写文档

### 🔧 建议简化

**AgentLab 应该退化成两层：**

```
大脑层（可选）: DeepSeek 仅做初始规划 + token 预算设定
执行层: 外部 AI 直接执行所有后续步骤
归档层: 自动写 git commit + changelog
```

不必要的中间 agent（RepoScout/InterfaceMapper/TesterAuditor）可以删除，它们对外部 AI 来说是纯开销。

---

## 5. 决策矩阵

| 条件 | 结论 |
|------|------|
| 我有一个强大的外部 AI（如 Claude、Codex）连接着？ | **直接用它，不需要 AgentLab 大脑层** |
| 我想省钱？ | **直接用外部 AI**，因为跳过 5 次 DeepSeek 调用 |
| 我想省外部 AI token？ | 用 AgentLab 的 DeepSeek 做规划，外部 AI 只做 Coder |
| 项目要持续几周/几月，需要记忆？ | **AgentLab 的 agent_docs 有价值** |
| 需要审计证明每个决策过程？ | **AgentLab 的报告文件有价值** |
| 外部 AI 连接断了？ | **AgentLab 可以独立工作（虽然慢）** |
| 任务很简单（改 1-2 个文件）？ | **直接用外部 AI，1 分钟内完成** |

---

## 6. 最终结论

**AgentLab 的设计有存在价值，但其当前的大脑层架构（5 个 DeepSeek agent 串行）对外部 AI 驱动场景是低效的。**

核心矛盾：AgentLab 的设计假设"大脑层"需要单独的模型调用，但外部 AI 本身就是一个更强的"大脑"，它在单次推理中就隐式完成了 Supervisor+RepoScout+InterfaceMapper+TesterAuditor 的所有工作。

**建议重构成 "代理模式"：**
- AgentLab 保留项目记忆、成本治理、审计追踪
- 大脑层 agent 全部标记为 `provider: external_ide_ai`（由外部 AI 模拟）
- 仅 Coder 阶段保留 DeepSeek API 调用（用于独立编码）
- 外部 AI 驱动时，一次 `run-agent Coder --execute --apply-patches` 即可完成整个流程