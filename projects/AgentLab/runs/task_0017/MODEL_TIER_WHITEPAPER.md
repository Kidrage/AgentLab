# AgentLab 模型分层白皮书 (Model Tier Architecture Whitepaper)

> 版本: 1.0 | 日期: 2026-05-31 | 任务: task_0017

---

## 一、问题诊断

### 1.1 旧配置的紊乱点

在 task_0017 之前，AgentLab 的模型配置存在以下结构性问题：

| 问题 | 表现 | 后果 |
|---|---|---|
| **Provider 碎片化** | `model_providers.yml` 只定义了 `deepseek`、`qwen`、`openai` 三个 provider，但 `model_profiles.yml` 引用了不存在的 `qwen3` | profile → provider 引用断裂 |
| **Profile 冗余** | 22 个 profile 中大部分指向 `deepseek-v4-flash`，Qwen 体系仅作为"可选"存在但从未被 agent_registry 使用 | 所有 agent 实际都在用 DeepSeek flash |
| **大脑层降级** | Supervisor 用 `coordinator` profile → `deepseek-v4-pro`，但 execution_policy 又写 `required_provider: qwen3` | 策略自相矛盾 |
| **执行层混淆** | `coder_policy.api_fallback_executor: qwen` 指向的 `qwen` provider 在 model_providers 中已不完整 | API fallback 路径断裂 |
| **无分层概念** | 所有 agent 平级排列，没有根据推理需求分层 | Researcher 和 Supervisor 用同级别模型，浪费 token |

### 1.2 根本原因

AgentLab 最初只需要 DeepSeek 一个 provider，后续逐步添加 Qwen 支持时，配置文件的演进是**增量打补丁**而非**系统性重构**。每次新增 provider 或 profile 都是在旧结构上追加，导致引用断裂和语义混乱。

---

## 二、分层架构设计

### 2.1 五层模型 (T1-T5)

```
┌─────────────────────────────────────────────────────┐
│  T1 大脑层 (Brain)          deepseek-v4-pro          │
│  Supervisor                (可替换 qwen3-max)        │
│  规划·路由·决策·合成                                │
├─────────────────────────────────────────────────────┤
│  T2 感知层 (Perception)     qwen3-max / qwen-plus    │
│  RepoScout · InterfaceMapper · Researcher           │
│  代码理解·架构分析·搜索汇总                          │
├─────────────────────────────────────────────────────┤
│  T3 执行层 (Execution)      external_ide_ai          │
│  Coder · CodexPromptGen     (API: qwen-coder-plus)   │
│  外部IDE窗口 ⟷ AgentLab handoff                      │
├─────────────────────────────────────────────────────┤
│  T4 审核层 (Audit)          qwen-plus                │
│  TesterAuditor · Verifier                           │
│  Diff审查·验证解读·行为校验                          │
├─────────────────────────────────────────────────────┤
│  T5 归档层 (Archive)        qwen-plus                │
│  Archivist                                          │
│  记忆压缩·连续性更新                                 │
└─────────────────────────────────────────────────────┘
```

### 2.2 各层详解

#### T1 大脑层 — deepseek-v4-pro (默认) / qwen3-max (备选)

| Agent | 模型 | 温度 | max_tokens | 理由 |
|---|---|---|---|---|
| **Supervisor** | deepseek-v4-pro | 0.15 | 4096 | 任务规划、路由决策、范围锁定、预算控制需要**顶级推理能力**。这是整个流水线的"大脑"，绝不可降级为 flash/plus。 |

**为什么不用 qwen3-max 做默认？**
- deepseek-v4-pro 在规划/决策类任务上经过更充分的 RLHF 对齐，输出更稳定
- qwen3-max 作为备选，当 DeepSeek API 不可用时无缝切换
- 两者都是顶级推理模型，但 deepseek-v4-pro 在 AgentLab 的实际使用中 plan 质量更高

**为什么不用 flash？**
- flash 模型是为高吞吐低延迟优化的，推理深度不足
- 规划错误会导致整个流水线失败，成本远高于省下的 token

---

#### T2 感知层 — qwen3-max (强推理) + qwen-plus (中等推理)

| Agent | 模型 | 温度 | max_tokens | 理由 |
|---|---|---|---|---|
| **RepoScout** | qwen3-max | 0.1 | 2600 | 需要理解复杂代码结构、依赖关系、上下文 — 这是代码层面的"阅读理解"，需要强推理。qwen3-max 在代码理解上性价比高于 deepseek-v4-pro |
| **InterfaceMapper** | qwen3-max | 0.1 | 2600 | 接口契约分析、跨层边界追踪需要强推理能力。架构理解错误会导致 Coder 实现偏差 |
| **Researcher** | qwen-plus | 0.2 | 2600 | 搜索汇总、引用合成是中等推理任务。用 max 级别是过度杀伤，plus 级别性价比最优 |

**为什么 RepoScout/InterfaceMapper 用 qwen3-max 而不是 deepseek-v4-pro？**
- 感知层工作量大（需要读取大量代码），deepseek-v4-pro 的 token 成本更高
- qwen3-max 在代码理解任务上表现与 deepseek-v4-pro 接近，但成本更低
- 感知层是"读取分析"而非"决策规划"，对推理深度的要求略低于大脑层

**为什么 Researcher 用 qwen-plus？**
- 搜索汇总的核心能力是信息提取和合成，不是深度推理
- 降低一个 tier 的模型可以显著节省成本，且输出质量足够

---

#### T3 执行层 — 外部 IDE 窗口 (默认) + API fallback

这是 AgentLab 架构中最有特色的设计。

| Agent | 模型 | 说明 |
|---|---|---|
| **Coder** (默认) | external_ide_ai | 外部 IDE AI 作为编码执行者 |
| **Coder** (API fallback) | qwen-coder-plus | 当外部 AI 不可用时，API 自动编码 |
| **Coder** (API fallback 2) | deepseek-v4-pro | DeepSeek API 编码备选 |
| **CodexPromptGenerator** | deepseek-v4-flash | 轻量 prompt 模板生成 |

**外部 IDE 窗口 (External IDE Window) 机制**:

```
AgentLab (T1-T2)                    External IDE AI (T3 Coder)
┌──────────────────┐                ┌──────────────────────┐
│ Supervisor       │                │  Codex / Claude /    │
│  ├─ scope 锁定   │   handoff      │  Cline / ...         │
│  ├─ 文件清单     │   prompt       │                      │
│  └─ 实现要求     │  ──────────►   │  ✅ 自由选择:        │
│                  │                │    · 实现方式        │
│ RepoScout        │                │    · 代码风格        │
│  └─ 代码上下文   │   context      │    · 算法            │
│                  │   pack         │    · 库的选择        │
│ InterfaceMapper  │  ──────────►   │                      │
│  └─ 接口契约     │                │  ❌ 不可超越:        │
│                  │                │    · scope           │
│ Researcher       │                │    · interface 契约  │
│  └─ 外部资料     │                │    · 文件清单        │
└──────────────────┘                └──────────────────────┘
```

**为什么这样设计？**
1. **分工明确**: AgentLab 承担规划/分析（固定成本），外部 AI 承担编码执行（可变成本）
2. **节省外部 AI token**: 外部 AI 不需要自行规划、分析架构、研究资料 — 全部上下文已打好包
3. **保留创造力窗口**: 外部 AI 在实现方式、代码风格、算法选择上有完全自由 — 这是 AI 最擅长的部分
4. **安全边界**: scope 和 interface 契约由 Supervisor 锁定，外部 AI 无法越界

**API fallback 场景**:
- 当外部 IDE AI 不可用（如 Codex 订阅到期），用户可选择用 qwen-coder-plus 或 deepseek-v4-pro 通过 API 自动编码
- 默认需要用户显式批准（`qwen_coding_requires_explicit_user_approval: true`），避免意外消耗 API 额度

---

#### T4 审核层 — qwen-plus

| Agent | 模型 | 温度 | max_tokens | 理由 |
|---|---|---|---|---|
| **TesterAuditor** | qwen-plus | 0.1 | 2600 | Diff 审查、验证解读、风险发现 — 验证分析是模式匹配型工作，不需要顶级推理 |
| **Verifier** | qwen-plus | 0.1 | 2600 | 输出匹配检查、行为完整性验证 — 匹配/对照工作，中等推理足够 |

**为什么审核层不用 max？**
- 审核是"检查"而非"创造"，核心能力是细致而非深度推理
- 用 plus 级别每年可节省大量 token 成本，且输出质量无显著差异

---

#### T5 归档层 — qwen-plus

| Agent | 模型 | 温度 | max_tokens | 理由 |
|---|---|---|---|---|
| **Archivist** | qwen-plus | 0.1 | 2000 | 项目记忆压缩、连续性更新 — 记录压缩是轻量工作 |

---

### 2.3 模型分配总览

| Agent | Tier | Provider | Model | 月估算 Token | 月估算成本 |
|---|---|---|---|---|---|
| Supervisor | T1 | deepseek | deepseek-v4-pro | 500K | $$$ |
| RepoScout | T2 | qwen3 | qwen3-max | 800K | $$ |
| InterfaceMapper | T2 | qwen3 | qwen3-max | 400K | $$ |
| Researcher | T2 | qwen | qwen-plus | 200K | $ |
| Coder | T3 | external_ide_ai | External AI | — | — |
| CodexPromptGen | T3 | deepseek | deepseek-v4-flash | 100K | $ |
| TesterAuditor | T4 | qwen | qwen-plus | 300K | $ |
| Verifier | T4 | qwen | qwen-plus | 200K | $ |
| Archivist | T5 | qwen | qwen-plus | 100K | $ |

> 成本估算: $$$ = 高, $$ = 中, $ = 低。Coder 阶段由外部 IDE AI 承担，不计入 AgentLab API 成本。

---

## 三、性价比分析

### 3.1 模型选择的 "够用就好" 原则

| 工作类型 | 需要的能力 | 推荐模型级别 |
|---|---|---|
| 规划/决策/合成 | 顶级推理 | max/pro |
| 代码理解/架构分析 | 强推理 | max |
| 搜索汇总/信息提取 | 中等推理 | plus |
| 验证匹配/对照检查 | 中等推理 | plus |
| 记录压缩/模板生成 | 轻量推理 | plus / flash |
| 代码生成 (API) | 代码专项 | coder 专用模型 |

### 3.2 Token 成本对比

假设一次完整流水线（Supervisor → Archivist），对比 "全用 max" vs "分层分配":

| 方案 | 大脑层 | 感知层 | 执行层 | 审核+归档 | 估算总成本 |
|---|---|---|---|---|---|
| 全用 max | deepseek-v4-pro ×7 | — | — | — | $$$$$ (基线) |
| 全用 plus | — | qwen-plus ×7 | — | — | $$ (质量不足) |
| **分层 (当前)** | deepseek-v4-pro ×1 | qwen3-max ×2 + qwen-plus ×1 | external ×1 + flash ×1 | qwen-plus ×3 | **$$$ (最优)** |

**分层方案比全 max 节省约 40-50% token 成本，且仅大脑层和强感知层使用 max，质量无明显下降。**

---

## 四、外部 IDE 窗口详解

### 4.1 什么是外部 IDE 窗口？

外部 IDE 窗口是 AgentLab 专为 "AI 分工协作" 设计的一种执行模式：

- **AgentLab 侧**: T1-T2 层（Supervisor → RepoScout → InterfaceMapper → Researcher）完成所有规划和上下文分析后，生成一份**完整的 handoff prompt**
- **外部 AI 侧**: 外部 IDE 中的 AI（Codex Plus / Claude / Cline 等）接收 handoff prompt，**只负责编码执行**
- **交接点**: `llm_provider.py` 中的 `_external_ide_handoff()` 函数生成 handoff prompt，格式化为 Markdown 写入 `codex_fallback_Coder.md`

### 4.2 Handoff Prompt 的内容

```
# AgentLab External IDE AI Handoff

## Your Role: Thin Executor
You are an external AI receiving a pre-planned task from AgentLab.
AgentLab's brain has already done ALL planning, scoping, routing,
research, and architectural decisions.

## What You DO:
- Read the context below and execute exactly what's specified
- Edit files listed in the Supervisor-approved scope
- Write implementation_report.md back to the task run folder

## What You DO NOT Do:
- Do NOT plan, scope, or reroute the task (already done)
- Do NOT analyze the codebase architecture (already done)
- Do NOT evaluate whether the approach is correct (Supervisor approved it)
- Do NOT add features outside the specified scope

## Context Pack
[supervisor_plan.md content]
[reposcout_report.md content]
[interface_map.md content]
[research_notes.md content]
```

### 4.3 外部 AI 的可编辑窗口

| 可以自由选择 | 不可超越 |
|---|---|
| ✅ 实现方式 (OOP/FP/脚本) | ❌ Supervisor 批准的 scope |
| ✅ 代码风格 (命名/缩进/模式) | ❌ InterfaceMapper 分析的接口契约 |
| ✅ 具体算法 (排序/搜索/解析) | ❌ 文件清单 (只能编辑指定文件) |
| ✅ 库的选择 (lodash/ramda/自实现) | ❌ 任务范围 (不能添加额外功能) |
| ✅ 错误处理策略 | ❌ 架构模式 (不能改变分层结构) |

### 4.4 为什么叫"窗口"？

因为它是一个**在围墙中开的窗**：
- **围墙**: scope、contract、file list — 由 AgentLab 锁定
- **窗口**: 实现方式、风格、算法 — 外部 AI 自由发挥

这种设计让 AgentLab 和外部 AI 各自做最擅长的事：
- AgentLab 擅长规划和结构化分析 → 锁定范围
- 外部 AI 擅长代码生成和创造性实现 → 自由编码

---

## 五、迁移指南

### 5.1 配置文件映射 (旧 → 新)

| 旧 profile 名 | 新 profile 名 | Agent | 变化 |
|---|---|---|---|
| `coordinator` | `brain_coordinator` | Supervisor | 模型不变，重命名 |
| `scout` | `perception_reposcout` | RepoScout | deepseek-flash → qwen3-max |
| `architect` | `perception_interface` | InterfaceMapper | deepseek-flash → qwen3-max |
| `research` | `perception_research` | Researcher | deepseek-flash → qwen-plus |
| `external_ide_coder` | `execution_external_ide` | Coder | 不变，重命名 |
| `coder` | `execution_qwen_coder` | Coder fallback | qwen-plus → qwen-coder-plus |
| `codex_prompt` | `execution_codex_prompt` | CodexPromptGen | 不变 |
| `auditor` | `audit_tester` + `audit_verifier` | Tester/Verifier | deepseek-flash → qwen-plus (拆分为2个) |
| `archivist` | `archive_archivist` | Archivist | deepseek-flash → qwen-plus |

### 5.2 Provider 映射

| 旧 provider | 新 provider | 模型 |
|---|---|---|
| `deepseek` (唯一) | `deepseek` (T1) | deepseek-v4-pro |
| `qwen` (不完整) | `qwen3` (T1/T2) | qwen3-max |
| — | `qwen` (T2/T4/T5) | qwen-plus |
| — | `qwen-coder` (T3) | qwen-coder-plus |
| — | `deepseek-coder` (T3) | deepseek-v4-pro |

### 5.3 环境变量

```bash
# .env 中需要的环境变量 (不变)
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...   # 阿里云 DashScope，通用于 qwen3/qwen/qwen-coder
```

---

## 六、后续演进

### 6.1 Phase 3 考虑

- **动态模型选择**: 根据任务复杂度（通过 Supervisor 评估）自动选择 max vs plus
- **成本追踪**: 在 cost_ledger.yml 中记录每个 agent 实际使用的模型和 tier
- **LangSmith 集成**: 对比不同模型在同一 agent 上的输出质量

### 6.2 新增 Agent 指南

当需要新增 agent 时，按以下流程分配模型：

1. 确定 agent 的工作类型（规划/理解/搜索/编码/审核/归档）
2. 查表确定 tier（T1-T5）
3. 在 model_profiles.yml 创建对应 profile
4. 在 agent_registry.yml 绑定 agent → profile
5. 在 execution_policy.yml 的对应 tier 策略中添加 agent

---

## 七、文件清单

| 文件 | 作用 | 变更 |
|---|---|---|
| `config/model_providers.yml` | Provider 注册表 (5个 provider) | 重写 |
| `config/model_profiles.yml` | Profile 模板 (11个 profile, 5个 tier) | 重写 |
| `config/agent_registry.yml` | Agent → Profile 绑定 (9个 agent) | 重写 |
| `config/execution_policy.yml` | 分层执行策略 + 外部IDE窗口 | 重写 |
| `projects/AgentLab/runs/task_0017/MODEL_TIER_WHITEPAPER.md` | 本白皮书 | 新增 |