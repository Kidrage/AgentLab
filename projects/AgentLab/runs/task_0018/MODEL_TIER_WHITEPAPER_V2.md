# AgentLab 模型分层白皮书 v2.0 — 项目体量自适应 + 三层预算策略

> 版本: 2.0 | 日期: 2026-05-31 | 任务: task_0018
> 继承: task_0017 (MODEL_TIER_WHITEPAPER v1.0)

---

## 一、最新模型生态调研 (2026年5月)

> 数据来源: OpenRouter API 模型注册表 (2026-05-31)、DeepSeek 官方 API 文档、Qwen/DashScope 官方文档、Qwen GitHub 仓库。

---

### 1.1 Qwen 全系列模型目录 (完备版)

#### 1.1.1 旗舰 / 前沿系列 — API 可用

| API 标识符 (OpenRouter) | 版本代际 | 架构类型 | 上下文长度 | 输入 $/1M tokens | 输出 $/1M tokens | 核心能力定位 |
|---|---|---|---|---|---|---|
| `qwen/qwen3.7-max` | **3.7 最新** | 闭源旗舰 (MoE) | **1M** | $1.25 | $3.75 | 🏆 **当前最强 Qwen** — 全能旗舰，多模态理解，中文优化，大脑层首选 Qwen |
| `qwen/qwen3.6-max-preview` | 3.6 预览 | 稀疏 MoE 前沿 | 262K | $1.04 | $6.24 | 前沿预览版，推理定价偏高 |
| `qwen/qwen3-max-thinking` | 3.0 推理特化 | 闭源推理专精 | 262K | $0.78 | $3.90 | 🧠 **复杂推理专精** — 数学/逻辑/多步推理，DeepSeek unavailable 时的推理备选 |

#### 1.1.2 均衡 / 性价比系列 — API 可用

| API 标识符 (OpenRouter) | 版本代际 | 架构类型 | 上下文长度 | 输入 $/1M tokens | 输出 $/1M tokens | 核心能力定位 |
|---|---|---|---|---|---|---|
| `qwen/qwen3.6-plus` | **3.6 最新** | 混合线性注意力 + 稀疏 MoE | **1M** | **$0.325** | **$1.95** | ⭐ **性价比之王** — AgentLab 感知层/审核层主力 |
| `qwen/qwen3.5-plus-20260420` | 3.5 (2026-04) | 混合线性注意力 + 视觉语言 | 1M | $0.30 | $1.80 | 稳定成熟版，多模态视觉语言 |
| `qwen/qwen3.5-plus-02-15` | 3.5 (2026-02) | 混合线性注意力 + 视觉语言 | 1M | $0.26 | $1.56 | 上一版稳定版 |

#### 1.1.3 轻量 / 高吞吐系列 — API 可用

| API 标识符 (OpenRouter) | 版本代际 | 架构类型 | 上下文长度 | 输入 $/1M tokens | 输出 $/1M tokens | 核心能力定位 |
|---|---|---|---|---|---|---|
| `qwen/qwen3.6-flash` | **3.6 最新** | 高效闪速 | **1M** | **$0.1875** | **$1.125** | ⚡ **Frugal 模式主力** — 极致低成本+高吞吐 |
| `qwen/qwen3.5-flash-02-23` | 3.5 (2026-02) | 混合线性注意力 + 视觉语言 | 1M | $0.065 | $0.26 | 更便宜的上一代 flash |

#### 1.1.4 开源 / 中小尺寸系列 — API 可用 (含本地部署)

| API 标识符 (OpenRouter) | 开源模型名 | 参数量 (总/激活) | 架构类型 | 上下文 | 输入 $/1M | 输出 $/1M | 本地部署 | 定位 |
|---|---|---|---|---|---|---|---|---|
| `qwen/qwen3.6-35b-a3b` | Qwen3.6-35B-A3B | 35B / 3B | MoE 混合注意力 | 262K | $0.14 | $1.00 | ✅ 消费级GPU | 本地 Coder 首选 |
| `qwen/qwen3.6-27b` | Qwen3.6-27B | 27B | Dense | 262K | $0.29 | $3.20 | ✅ 高端GPU | 本地感知层 |
| `qwen/qwen3.5-35b-a3b` | Qwen3.5-35B-A3B | 35B / 3B | MoE 混合注意力 + VL | 262K | $0.14 | $1.00 | ✅ 消费级GPU | 本地 Coder (成熟版) |
| `qwen/qwen3.5-27b` | Qwen3.5-27B | 27B | Dense 线性注意力 + VL | 262K | $0.195 | $1.56 | ✅ 高端GPU | 本地强感知 |
| `qwen/qwen3.5-9b` | Qwen3.5-9B | 9B | Dense + VL | 262K | $0.04 | $0.15 | ✅ 任意GPU | 本地 flash 级/简易审核 |
| `qwen/qwen3.5-122b-a10b` | Qwen3.5-122B-A10B | 122B / 10B | MoE 混合注意力 + VL | 262K | $0.26 | $2.08 | ⚠️ 高端多卡 | 本地强推理 |
| `qwen/qwen3.5-397b-a17b` | Qwen3.5-397B-A17B | 397B / 17B | MoE 混合注意力 + VL | 262K | $0.39 | $2.34 | ❌ 数据中心级 | 本地大脑层 (极限) |

#### 1.1.5 专用模型系列

| API 标识符 (OpenRouter) | 版本代际 | 架构类型 | 上下文长度 | 输入 $/1M tokens | 输出 $/1M tokens | 核心能力定位 |
|---|---|---|---|---|---|---|
| `qwen/qwen3-coder-next` | **3.0 Coder** | 因果语言模型 (开源) | 262K | **$0.11** | **$0.80** | 🔧 **代码生成专用** — 全系列最低价，编码优于通用模型 |

#### 1.1.6 完整开源模型清单 (仅本地部署 / 无需 API)

以下模型通过 Hugging Face / ModelScope 可直接下载，通过 Ollama / vLLM / SGLang 本地运行：

| 模型名 | 总参 / 激活参 | 上下文 | 显存需求 (估算) | 适用 AgentLab 角色 | HuggingFace 仓库 |
|---|---|---|---|---|---|
| **Qwen3.6-35B-A3B** | 35B / 3B | 262K | ~8 GB (FP16) / ~4 GB (INT4) | 本地 Coder (Frugal 主力) | `Qwen/Qwen3.6-35B-A3B` |
| **Qwen3.6-27B** | 27B | 262K | ~54 GB (FP16) / ~14 GB (INT4) | 本地感知层 | `Qwen/Qwen3.6-27B` |
| **Qwen3.5-35B-A3B** | 35B / 3B | 262K | ~8 GB (FP16) / ~4 GB (INT4) | 本地 Coder | `Qwen/Qwen3.5-35B-A3B` |
| **Qwen3.5-27B** | 27B | 262K | ~54 GB (FP16) / ~14 GB (INT4) | 本地感知层 | `Qwen/Qwen3.5-27B` |
| **Qwen3.5-9B** | 9B | 262K | ~18 GB (FP16) / ~5 GB (INT4) | 本地 flash/审核 | `Qwen/Qwen3.5-9B` |
| **Qwen3.5-122B-A10B** | 122B / 10B | 262K | ~20 GB (FP16) / ~10 GB (INT4) | 本地强推理 | `Qwen/Qwen3.5-122B-A10B` |
| **Qwen3.5-397B-A17B** | 397B / 17B | 262K | ~35 GB (FP16) / ~18 GB (INT4) | 本地大脑层备选 | `Qwen/Qwen3.5-397B-A17B` |
| **Qwen3-235B-A22B-2507** | 235B / 22B | 256K | ~45 GB (FP16) / ~23 GB (INT4) | 本地大脑层 (2507更新) | `Qwen/Qwen3-235B-A22B-Instruct-2507` |
| **Qwen3-30B-A3B-2507** | 30B / 3B | 256K | ~8 GB (FP16) / ~4 GB (INT4) | 本地 Coder (2507更新) | `Qwen/Qwen3-30B-A3B-Instruct-2507` |
| **Qwen3-4B-2507** | 4B | 256K | ~8 GB (FP16) / ~2 GB (INT4) | 本地极简任务 | `Qwen/Qwen3-4B-Instruct-2507` |

> **注**: Qwen3-2507 系列是 2025 年 7-8 月发布的大幅更新版本，支持 256K-1M 超长上下文。Thinking 版本支持思维链推理。

---

### 1.2 DeepSeek 模型矩阵

| 模型 | 架构 | 上下文 | 核心优势领域 | 官方API输入 (每百万token) | 官方API输出 (每百万token) |
|---|---|---|---|---|---|
| **deepseek-v4-pro** | MoE 1.6T总参 | 1M | 复杂规划、多步推理、战略决策、长链CoT | ~$1.74 (cache miss) / ~$0.0145 (cache hit) | ~$3.48 |
| **deepseek-v4-flash** | MoE 284B总参 | 1M | 高吞吐、简单任务、快速响应 | ~$1.74 (cache miss) / ~$0.0112 (cache hit) | ~$3.48 |
| **deepseek-v4-flash (free)** | MoE 284B总参 | 1M | 免费层，轻量任务 | **$0** | **$0** | OpenRouter 免费通道 |

> **⚠️ 关键变动 (2026-05-31)**: DeepSeek V4 系列 **75% 折扣促销今天到期**。结束后价格恢复至原始定价的 1/4 折扣（即当前价格的 4 倍）。cache hit 价格保持 1/10 发行价。
>
> 这意味着 DeepSeek API 成本将**显著上升**，对大脑层预算策略有重大影响。
>
> **DeepSeek-V3.1 Nex-N1** (`nex-agi/deepseek-v3.1-nex-n1`): 第三方后训练版本，在编码和推理上有增强，可在特殊场景作为备选。

**能力定位**:
- **deepseek-v4-pro**: 顶级推理模型。在规划、代码架构设计、长链思维推理上表现最佳。Thinking Mode 是其核心差异点。适合 AgentLab 大脑层的规划/路由/决策工作。
- **deepseek-v4-flash**: 轻量版，损失部分推理深度换取速度。适合 prompt 模板生成、简单分类、快速摘要等工作。
- **deepseek-v4-flash (free)**: OpenRouter 上的免费通道，适合原型测试和极低成本场景。

### 1.3 核心能力对比矩阵

#### 1.3.1 AgentLab 场景 → 最佳模型推荐

| AgentLab 场景 | 首选模型 | 备选模型 | 选择理由 |
|---|---|---|---|
| 🧠 大脑层规划/路由/决策 (L2/L3) | `deepseek-v4-pro` | `qwen3.7-max` | Thinking Mode + 顶级推理 |
| 🧠 大脑层规划 (L1 轻量) | `qwen3.6-plus` | `qwen3.7-max` | 性价比足够，flash 太弱 |
| 👁️ 代码仓库扫描/依赖分析 (L2) | `qwen3.6-plus` | `qwen3.7-max` | 性价比之王，代码理解不输max |
| 👁️ 代码仓库扫描 (L3 深度) | `qwen3.7-max` | `deepseek-v4-pro` | 1M上下文 + 强推理，超大仓库 |
| 👁️ 接口契约/架构分析 | `qwen3.6-plus` | `qwen3.7-max` | 架构分析需要推理但不必 max |
| 🔍 搜索汇总/信息合成 | `qwen3.6-flash` | `qwen3.5-flash` | 不需要强推理，flash 最便宜 |
| 🔧 API 代码生成 (默认) | `qwen3-coder-next` | — | **全系列最便宜+代码专用** |
| 🔧 代码生成 (安全关键) | `deepseek-v4-pro` | `qwen3.7-max` | 安全关键需要最强推理 |
| 🔧 本地代码生成 (Frugal) | `Qwen3.6-35B-A3B` (本地) | `qwen3-coder-next` (API) | 零成本，3B激活消费级GPU可跑 |
| ✅ 验证/审查 (常规) | `qwen3.6-flash` | `qwen3.5-flash` | 验证是模式匹配，flash 足够 |
| ✅ 验证/审查 (L3 关键) | `qwen3.6-plus` | `qwen3.7-max` | 复杂项目验证需要更高准确率 |
| 📦 归档/记忆压缩 | `qwen3.6-flash` | `qwen3.5-flash` | 记录压缩不需要推理 |
| 🆓 极致省钱 (原型/测试) | `qwen3.5-flash-02-23` | `deepseek-v4-flash (free)` | $0.065/$0.26，全模型最便宜API |

#### 1.3.2 模型综合能力雷达

| 维度 | deepseek-v4-pro | qwen3.7-max | qwen3.6-plus | qwen3-coder-next | qwen3.6-flash |
|---|---|---|---|---|---|
| 规划/决策 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| 代码理解 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 代码生成 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| 长上下文 | ⭐⭐⭐⭐⭐ (1M) | ⭐⭐⭐⭐⭐ (1M) | ⭐⭐⭐⭐⭐ (1M) | ⭐⭐⭐ (262K) | ⭐⭐⭐⭐⭐ (1M) |
| 中文能力 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 数学/逻辑 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| 多模态 | ❌ | ✅ | ✅ | ❌ | ✅ |
| 推理速度 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| API 成本 | $$$$ | $$$ | $$ | $ | $ |

### 1.4 价格排序总览 (2026-05-31)

```
输入价格 ($/1M tokens)  低 → 高:
  $0.11  qwen3-coder-next        ← 代码生成最便宜
  $0.1875 qwen3.6-flash           ← 高吞吐首选
  $0.30   qwen3.5-plus
  $0.325  qwen3.6-plus            ← 均衡性价比之王
  $0.78   qwen3-max-thinking
  $1.04   qwen3.6-max-preview
  $1.25   qwen3.7-max             ← Qwen旗舰
  $1.74   deepseek-v4-pro/flash   ← 折扣后(今天起生效)

输出价格 ($/1M tokens)  低 → 高:
  $0.80   qwen3-coder-next
  $1.125  qwen3.6-flash
  $1.80   qwen3.5-plus
  $1.95   qwen3.6-plus
  $3.48   deepseek-v4-pro/flash   ← 折扣后
  $3.75   qwen3.7-max
  $3.90   qwen3-max-thinking
```

**核心结论**:
1. DeepSeek V4 折扣结束后，**Qwen3.6-plus 性价比远优于 DeepSeek** (输入便宜 5.4x)
2. **qwen3-coder-next 是代码生成的最优解** — 专为编码优化且价格最低
3. **qwen3.7-max 与 deepseek-v4-pro 价格接近** — 需要根据具体任务选择
4. 对于强推理任务，**deepseek-v4-pro 的 Thinking Mode 仍是差异化优势**
5. 本地部署模型虽然能力弱一级，但**零边际成本**，适合高频+中等复杂度场景

---

### 1.5 DeepSeek V4 两大模型全方位对比

#### 1.5.1 特性对比

| 特性 | deepseek-v4-pro | deepseek-v4-flash | 对 AgentLab 的影响 |
|---|---|---|---|
| **Thinking Mode** | ✅ 默认启用，CoT 内部推理链 | ✅ 支持，可切换 non-thinking | V4-pro 的 Thinking Mode 是其大脑层核心优势 — 规划任务输出更稳定 |
| **Context Caching** | ✅ 支持 (75% off cache hit) | ✅ 支持 (75% off cache hit) | **关键**: AgentLab 多 agent 共用同一仓库上下文 → 大量 cache hit → 实际成本远低于 face price |
| **Context Length** | 1M tokens | 1M tokens | 仓库级代码分析无压力，与 qwen3.7-max/qwen3.6-plus 持平 |
| **Max Output** | 384K tokens | 384K tokens | 远超 Qwen 系列 (通常 8K-32K)，适合生成超长实现计划 |
| **FIM Completion** | ❌ (仅 non-thinking) | ❌ (仅 non-thinking) | 对 Coder 的 Fill-in-the-Middle 能力有限，建议 Coder 用 qwen3-coder-next |
| **JSON Output / Tool Calls** | ✅ 支持 | ✅ 支持 | AgentLab 结构化输出需求全部满足 |
| **Chat Prefix Completion** | ❌ (non-thinking) | ❌ (non-thinking) | 对 AgentLab 影响小 |
| **Anthropic API 兼容** | ✅ | ✅ | 多协议接入灵活性 |
| **总参数量** | 1.6T (MoE) | 284B (MoE) | V4-pro 的参数量级优势体现在复杂推理 |
| **推理深度** | ⭐⭐⭐⭐⭐ 顶级 | ⭐⭐⭐ 中等 | 规划/决策场景差距显著 |
| **推理速度** | 中等 (CoT 耗时) | 快 (轻量 MoE) | V4-flash 适合高吞吐低延迟场景 |

#### 1.5.2 定价与 Cache Hit 深度分析

**当前定价 (2026-05-31, 75%折扣到期后)**:

| 价格项 | deepseek-v4-pro | deepseek-v4-flash | 对比 Qwen |
|---|---|---|---|
| 1M input tokens (cache miss) | $1.74 | $1.74 | qwen3.6-plus: $0.325 — **便宜 5.35x** |
| 1M input tokens (cache hit) | $0.0145 | $0.0112 | 极低！AgentLab 的杀手级优势 |
| 1M output tokens | $3.48 | $3.48 | qwen3-coder-next: $0.80 — 便宜 4.35x |

**Cache Hit 的 AgentLab 场景价值**:

在 AgentLab 的多 Agent 流水线中，同一代码仓库的上下文会被反复读取：
- RepoScout 读取文件 A → **cache miss**
- InterfaceMapper 再次引用文件 A → **cache hit** (75% off)
- Supervisor 合成时引用接口 → **cache hit**
- Coder 实现时读取 → **cache hit**
- TesterAuditor 审查时引用 → **cache hit**

这意味着**对于多次使用同一代码上下文的完整流水线，实际输入成本远低于 $1.74/M**。
估算：假设 60% 的 input tokens 命中 cache，则实际加权输入成本为 $1.74 × 0.4 + $0.0145 × 0.6 ≈ **$0.70/M**。

**核心结论**：
- DeepSeek V4-pro 在大脑层的真实成本可能是面价的 **40-60%**
- Cache hit 机制使得"重度规划 + 多轮引用"的场景比单次调用更有优势
- 这也解释了为什么 **Supervisor + RepoScout + InterfaceMapper 都用 DeepSeek 不会线性增加成本**

#### 1.5.3 推理能力场景化评估

| AgentLab 任务场景 | v4-pro (Thinking) | v4-flash (Non-thinking) | qwen3.7-max | qwen3.6-plus |
|---|---|---|---|---|
| **多模块架构规划** | ⭐⭐⭐⭐⭐ 最佳 | ⭐⭐⭐ 可用但不推荐 | ⭐⭐⭐⭐ 接近 v4-pro | ⭐⭐⭐ 不够 |
| **安全审计 / 风险分析** | ⭐⭐⭐⭐⭐ 最强 CoT | ⭐⭐ 弱 | ⭐⭐⭐⭐ | ⭐⭐ |
| **路由决策 (小任务)** | ⭐⭐⭐⭐ 过度杀伤 | ⭐⭐⭐⭐ 正合适 | ⭐⭐⭐ | ⭐⭐⭐ 合适 |
| **代码结构理解** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ 中文场景更强 | ⭐⭐⭐⭐ |
| **长文档合成** | ⭐⭐⭐⭐⭐ (384K 输出) | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **数学 / 逻辑推理** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **多轮对话一致性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **批量文件生成** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ (coder-next) |
| **搜索汇总 / 资料合成** | ⭐⭐⭐⭐ 过度杀伤 | ⭐⭐⭐⭐⭐ 最优 | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **验证 / 匹配检查** | ⭐⭐⭐⭐ 过度杀伤 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

#### 1.5.4 DeepSeek vs Qwen 性价比决策矩阵

| 场景 | 选取 DeepSeek v4-pro | 选取 Qwen (cheaper) | 理由 |
|---|---|---|---|
| L2/L3 大脑层规划 | ✅ 默认 | qwen3.7-max (备选) | Thinking Mode 输出更稳定；cache hit 打折后成本可控 |
| L1 大脑层规划 | ❌ 过度杀伤 | ✅ qwen3.6-plus | 成本便宜 5x+，规划质量足够 |
| 强感知层 (RepoScout L3) | ❌ | ✅ qwen3.7-max | 代码理解 Qwen 不输，成本更低 |
| Coder | ❌ (除非 max_quality) | ✅ qwen3-coder-next | 代码生成专用，价格差 15x |
| 安全关键 Coder (MaxQ) | ✅ | — | 牺牲成本换安全性 |
| TesterAuditor (常规) | ❌ | ✅ qwen3.6-flash | flash 便宜且足够 |
| Archivist | ❌ | ✅ qwen3.6-flash | flash 最适合轻量工作 |
| Researcher | ❌ | ✅ qwen3.6-flash/plus | flash/plus 搜索汇总够用 |
| 多 Agent 高频调用同一仓库 | ✅ | — | cache hit 让 DeepSeek 实际成本大幅降低 |

#### 1.5.5 三个月成本预测（按折扣后价格）

假设每月执行 20 个 L2 标准任务（大脑层分配）：

| 模型组合 | 月 API 成本估算 | 年成本 |
|---|---|---|
| 全 DeepSeek 方案 (v4-pro × 所有Agent) | ~$80-120 | ~$1,200 |
| 当前大脑层分配方案 (v4-pro 大脑 + Qwen 感知/审核) | ~$30-45 | ~$450 |
| 全 Qwen 方案 (qwen3.7-max 大脑 + qwen3.6-plus 其他) | ~$18-28 | ~$280 |
| Frugal 方案 (全 flash) | ~$5-8 | ~$80 |

**推荐**: 当前大脑层分配方案 — 年省 $750 vs 全 DeepSeek，年多花 $170 vs 全 Qwen 但换来关键决策质量。

### 1.6 最终模型推荐矩阵（整合 DeepSeek + Qwen）

| Agent | 🧠 Brain L1 | 🧠 Brain L2 | 🧠 Brain L3 | ⚡ MaxQ | 💰 Frugal |
|---|---|---|---|---|---|
| **Supervisor** | qwen3.6-plus | **deepseek-v4-pro** | **deepseek-v4-pro** | deepseek-v4-pro (Thinking) | qwen3.6-flash |
| **RepoScout** | — | qwen3.6-plus | qwen3.7-max | qwen3.7-max | qwen3.6-flash |
| **InterfaceMapper** | — | qwen3.6-plus | qwen3.7-max | qwen3.7-max | 跳过 |
| **Researcher** | — | qwen3.6-flash | qwen3.6-plus | qwen3.6-plus | 跳过 |
| **Coder (API)** | qwen3-coder-next | qwen3-coder-next | qwen3-coder-next | qwen3-coder-next | qwen3-coder-next |
| **Coder (MaxQ)** | — | — | — | deepseek-v4-pro | — |
| **TesterAuditor** | 可选 qwen3.6-flash | qwen3.6-flash | qwen3.6-plus | qwen3.7-max | qwen3.6-flash |
| **Verifier** | — | qwen3.6-flash | qwen3.6-plus | qwen3.7-max | 跳过 |
| **Archivist** | — | qwen3.6-flash | qwen3.6-plus | qwen3.6-plus | 跳过 |

> **DeepSeek 使用约束**: DeepSeek v4-pro **仅用于 L2/L3 大脑层 + MaxQ 编码**。其他所有场景使用 Qwen 系列 (性价比更优)。DeepSeek v4-flash 不直接用于 AgentLab（被 qwen3.6-flash 替代，便宜 9.3x 输入）。

---

## 二、项目体量分类体系

### 2.1 项目分类维度

AgentLab 大脑层 (Supervisor) 在收到新项目描述时，必须从以下维度综合判断项目体量：

| 维度 | 长期/大型项目 | 一次性/小型项目 |
|---|---|---|
| **时间跨度** | 数周至数月持续迭代 | 数小时至数天完成 |
| **代码规模** | 多模块/多仓库 | 单文件/少量文件 |
| **维护需求** | 需要长期记录、版本管理、回归测试 | 一次产出，后续可丢弃 |
| **质量要求** | 高复现率、高稳定性、可审计 | 功能可用即可 |
| **协作复杂度** | 多Agent/多人协作 | 单人/单Agent |
| **长期记忆需求** | 需要完整 agent_docs 和 changelog | 仅需 run 级别记录 |
| **外部依赖** | API变更、版本升级、安全补丁 | 无或极少外部依赖 |

### 2.2 三级项目分类

#### L1 — 轻量项目 (Lightweight / One-shot)
- **特征**: 脚本、配置修改、Bug修复、单文件功能添加、格式转换
- **判断标准**: 涉及文件 ≤ 5, 预估 token ≤ 15K, 无架构变更
- **示例**: "给cli加一个--verbose参数"、"修复日志格式"、"转换CSV到JSON"
- **路由**: Supervisor → Coder → (可选)TesterAuditor
- **预算档位**: 最低成本 (Frugal)

#### L2 — 标准项目 (Standard / Iterative)
- **特征**: 功能模块开发、中等规模重构、跨文件实现
- **判断标准**: 涉及文件 5-20, 预估 token 15K-50K, 可能有接口变更
- **示例**: "实现用户认证模块"、"重构数据库访问层"、"添加REST API端点"
- **路由**: Supervisor → RepoScout → (InterfaceMapper) → Coder → TesterAuditor → Verifier → Archivist
- **预算档位**: 大脑层分配 (Brain-allocated, 默认)

#### L3 — 重型项目 (Heavy / Long-term)
- **特征**: 架构重构、多模块系统、安全敏感、长期维护的核心基础设施
- **判断标准**: 涉及文件 > 20, 预估 token > 50K, 架构级变更
- **示例**: "全栈微服务架构迁移"、"实现插件系统"、"安全加固整个项目"
- **路由**: Supervisor → RepoScout → Researcher → InterfaceMapper → Coder → TesterAuditor → Verifier → Archivist (全流程)
- **预算档位**: 全量运算 (Max Quality)

### 2.3 Agent 参与矩阵

| Agent | L1 轻量 | L2 标准 | L3 重型 |
|---|---|---|---|
| Supervisor | ✅ (轻量模型) | ✅ (旗舰模型) | ✅ (旗舰模型) |
| RepoScout | ❌ | ✅ (中档模型) | ✅ (旗舰模型) |
| InterfaceMapper | ❌ | ⚠️ 按需 | ✅ |
| Researcher | ❌ | ⚠️ 按需 | ✅ |
| Coder | ✅ | ✅ | ✅ |
| TesterAuditor | ⚠️ 按需 | ✅ | ✅ |
| Verifier | ❌ | ✅ | ✅ |
| Archivist | ❌ | ✅ | ✅ (完整记录) |

---

## 三、三层预算策略

### 3.1 三种预算模式

用户可为任何项目选择以下三种预算模式之一，**默认 = 大脑层分配**。

```
┌─────────────────────────────────────────────────────────────────┐
│                     AgentLab 预算模式                            │
│                                                                 │
│  🧠 大脑层分配 (Brain-allocated)  ← 默认                        │
│     Supervisor 根据项目体量自动选择最优模型组合                    │
│     兼顾质量与成本，不同Tier使用不同级别模型                      │
│                                                                 │
│  ⚡ 全量运算 (Max Quality)                                       │
│     所有 Agent 使用其能力范围内最强模型                           │
│     适合: 安全关键、架构重构、长期核心项目                        │
│     成本: $$$$$ (约为大脑层分配的 2-3x)                          │
│                                                                 │
│  💰 最低成本 (Frugal)                                           │
│     所有 Agent 使用最具性价比的 API 模型                          │
│     Coder 用 qwen3-coder-next ($0.11/$0.80, 全系最便宜)        │
│     适合: 原型验证、一次性脚本、低风险修改                       │
│     成本: $ (约为大脑层分配的 1/3-1/5)                           │
│                                                                 │
│  用户选择方式:                                                    │
│     - user_request.md 中显式声明                                 │
│     - CLI: --budget brain | max-quality | frugal                │
│     - 环境变量: AGENTLAB_BUDGET_MODE                             │
│     - 未指定 → 默认 brain-allocated                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 各模式下的模型分配

#### 🧠 大脑层分配 (Brain-allocated, 默认)

Supervisor 根据项目体量 (L1/L2/L3) 自动选择：

| Agent | L1 轻量 | L2 标准 | L3 重型 |
|---|---|---|---|
| **Supervisor** | qwen3.6-plus | deepseek-v4-pro | deepseek-v4-pro |
| **RepoScout** | — | qwen3.6-plus | qwen3.7-max |
| **InterfaceMapper** | — | qwen3.6-plus | qwen3.7-max |
| **Researcher** | — | qwen3.6-flash | qwen3.6-plus |
| **Coder** (API) | qwen3-coder-next | qwen3-coder-next | qwen3-coder-next |
| **Coder** (外部IDE) | External AI | External AI | External AI |
| **TesterAuditor** | qwen3.6-flash * | qwen3.6-flash | qwen3.6-plus |
| **Verifier** | — | qwen3.6-flash | qwen3.6-plus |
| **Archivist** | — | qwen3.6-flash | qwen3.6-plus |

> * L1 的 TesterAuditor 可选，仅在 Supervisor 判断需要时加入。

**成本特征**: 约 $0.5-1.5/L2任务, $2-5/L3任务

#### ⚡ 全量运算 (Max Quality)

所有 Agent 用最强可用模型，不考虑成本：

| Agent | 模型 |
|---|---|
| **Supervisor** | deepseek-v4-pro (Thinking Mode) |
| **RepoScout** | qwen3.7-max |
| **InterfaceMapper** | qwen3.7-max |
| **Researcher** | qwen3.6-plus |
| **Coder** (API) | deepseek-v4-pro |
| **Coder** (外部IDE) | External AI |
| **TesterAuditor** | qwen3.7-max |
| **Verifier** | qwen3.7-max |
| **Archivist** | qwen3.6-plus |

**成本特征**: 约 $8-15/L3任务 (为大脑层分配的 2-3x)

#### 💰 最低成本 (Frugal)

极简模型，能省则省：

| Agent | 模型 |
|---|---|
| **Supervisor** | qwen3.6-flash |
| **RepoScout** | qwen3.6-flash (或本地 Qwen3.5-35B) |
| **InterfaceMapper** | — (跳过，除非必须) |
| **Researcher** | — (跳过，除非必须) |
| **Coder** (API) | qwen3-coder-next |
| **TesterAuditor** | qwen3.6-flash |
| **Verifier** | — (跳过) |
| **Archivist** | — (跳过) |

**成本特征**: 约 $0.10-0.30/L1任务 (为大脑层分配的 1/5)

### 3.3 本地算力接入（可选、默认关闭）

本地 LLM 是**完全可选**的功能——默认关闭，不影响任何现有工作流。
用户若未来有本地 GPU 资源，可通过以下配置启用 Frugal 模式的本地编码加速：

```
# 启用本地 LLM（需先在本地运行 Ollama / vLLM）
AGENTLAB_LOCAL_LLM_ENABLED=1
AGENTLAB_LOCAL_CODER_MODEL=qwen3.6-35b-a3b
AGENTLAB_LOCAL_BASE_URL=http://localhost:11434/v1
```

启用后，Frugal 模式下 Coder 会优先尝试本地模型，不可用时自动 fallback 到 `qwen3-coder-next` API。
在不启用的情况下，Frugal 模式的 Coder 直接用 `qwen3-coder-next` ($0.11/$0.80)——已经是全系列最便宜的 API。

本地模型优势：
- **零 API 成本** (仅电费/GPU算力)
- **无限调用** 无配额焦虑
- **数据隐私** 代码不离开本地

本地模型劣势：
- 推理能力弱于旗舰 API 模型
- 需要 GPU 硬件
- 长上下文支持有限

---

## 四、Updated 五层架构 (T1-T5) with 三层预算

### 4.1 新架构图

```
┌───────────────────────────────────────────────────────────────────┐
│                     AgentLab 模型分层 v2.0                          │
│                                                                    │
│  预算模式: 🧠大脑分配 / ⚡全量运算 / 💰最低成本                      │
│  项目体量: L1轻量 / L2标准 / L3重型 → 自动选择模型                  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ T1 大脑层 (Brain)                                            │  │
│  │ Supervisor                                                   │  │
│  │ 🧠 L1: qwen3.6-plus    L2/L3: deepseek-v4-pro               │  │
│  │ ⚡ deepseek-v4-pro (Thinking Mode)                          │  │
│  │ 💰 qwen3.6-flash                                             │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │ T2 感知层 (Perception)                                       │  │
│  │ RepoScout · InterfaceMapper · Researcher                     │  │
│  │ 🧠 L2: qwen3.6-plus    L3: qwen3.7-max / qwen3.6-plus      │  │
│  │ ⚡ qwen3.7-max / qwen3.6-plus                               │  │
│  │ 💰 qwen3.6-flash (或本地部署)                                │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │ T3 执行层 (Execution)                                        │  │
│  │ Coder · CodexPromptGen                                       │  │
│  │ 🧠 qwen3-coder-next (API) / External IDE AI                 │  │
│  │ ⚡ deepseek-v4-pro (API) / External IDE AI                  │  │
│  │ 💰 qwen3-coder-next (API) / 本地 Qwen3.6-35B                │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │ T4 审核层 (Audit)                                            │  │
│  │ TesterAuditor · Verifier                                     │  │
│  │ 🧠 qwen3.6-flash / qwen3.6-plus                             │  │
│  │ ⚡ qwen3.7-max                                               │  │
│  │ 💰 qwen3.6-flash / 跳过                                      │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │ T5 归档层 (Archive)                                          │  │
│  │ Archivist                                                    │  │
│  │ 🧠 qwen3.6-flash / qwen3.6-plus                             │  │
│  │ ⚡ qwen3.6-plus                                              │  │
│  │ 💰 跳过                                                      │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### 4.2 模型引用更新 (新旧对照)

| 旧引用 (v1.0) | 新引用 (v2.0) | 变更原因 |
|---|---|---|
| `qwen3-max` | `qwen3.7-max` | Qwen 已从 3.0 → 3.5 → 3.6 → 3.7，当前最新旗舰 |
| `qwen-plus` | `qwen3.6-plus` | 原 qwen-plus 已映射到 3.6-plus |
| `qwen-coder-plus` | `qwen3-coder-next` | Coder 系列已迭代到 next 版本 |
| `deepseek-v4-flash` (prompt生成) | `qwen3.6-flash` | flash 生成不再需要 deepseek，qwen flash 便宜 10x+ |
| `qwen` provider (旧dashscope endpoint) | `qwen3` provider (compatible mode) | 统一使用 OpenAI-compatible endpoint |

---

## 五、配置文件变更总览

### 5.1 model_providers.yml

**新增/更新项**:
- `qwen3` provider: 升级 default_model 为 `qwen3.7-max`
- `qwen` provider: 升级为 `qwen3.6-plus` (原 qwen-plus 指向)
- `qwen-coder` provider: 升级为 `qwen3-coder-next`
- 新增 `qwen-local` provider: 本地 LLM (Ollama/vLLM)
- `deepseek` provider: 价格变动告警 (75%折扣结束)
- 标记废弃: `deepseek-v4-flash` 在非prompt场景不再推荐

### 5.2 model_profiles.yml

**新增 profiles**:
- `brain_coordinator_frugal`: Supervisor 最低成本 → qwen3.6-flash
- `brain_coordinator_maxq`: Supervisor 全量 → deepseek-v4-pro + thinking
- `perception_reposcout_frugal`: RepoScout 最低成本 → qwen3.6-flash
- `perception_reposcout_maxq`: RepoScout 全量 → qwen3.7-max
- `perception_interface_frugal/maxq`: 同上
- `execution_coder_maxq`: Coder 全量 → deepseek-v4-pro (API)
- `execution_coder_local`: Coder 本地 → local LLM
- `audit_tester_frugal/maxq`: 审核层两端
- `archive_archivist_maxq`: 归档层全量

### 5.3 execution_policy.yml

**新增**:
- `budget_mode_policy`: 预算模式选择规则
- `project_sizing_policy`: 项目体量判断规则 (L1/L2/L3)
- `budget_mode_options`: [brain_allocated, max_quality, frugal]
- `default_budget_mode`: brain_allocated
- `local_llm_policy`: 本地模型启用与 fallback 规则

### 5.4 budget_profiles.yml

**完全重写**: 按 L1/L2/L3 + 三种预算模式重新预算 token 分配

### 5.5 routing_rules.yml

**更新**: 新增 `project_classification_keywords` 支持 L1/L2/L3 自动分类

---

## 六、实施路线图

### Phase 1: 配置文件更新 (本次 task_0018)
- [ ] 更新 `model_providers.yml` — 模型名/价格注释更新
- [ ] 更新 `model_profiles.yml` — 新增三层 profile
- [ ] 更新 `execution_policy.yml` — 新增预算模式策略
- [ ] 重写 `budget_profiles.yml` — L1/L2/L3 × 三模式
- [ ] 更新 `routing_rules.yml` — 项目体量关键词
- [ ] 更新 `agent_registry.yml` — 模型引用更新

### Phase 2: Runtime 实现 (后续任务)
- [ ] `budget_planner.py` — 实现三层预算逻辑
- [ ] `brain_governor.py` — 实现项目体量判断 (L1/L2/L3)
- [ ] `task_router.py` — 根据体量+预算模式路由
- [ ] `llm_provider.py` — 支持本地 LLM backend

### Phase 3: 本地算力 (后续任务)
- [ ] Ollama/vLLM 适配器
- [ ] 本地模型能力评估
- [ ] 本地↔API fallback 策略

---

## 七、成本对比分析

### 7.1 典型任务成本 (估算)

| 项目类型 | 预算模式 | Supervisor | 感知层 | 执行层 | 审核+归档 | **总成本** |
|---|---|---|---|---|---|---|
| L1 脚本修复 | Frugal | qwen3.6-flash | — | qwen3-coder-next | qwen3.6-flash (可选) | **~$0.15** |
| L1 脚本修复 | Brain | qwen3.6-plus | — | qwen3-coder-next | qwen3.6-flash (可选) | **~$0.25** |
| L1 脚本修复 | MaxQ | deepseek-v4-pro | — | deepseek-v4-pro | qwen3.7-max | **~$1.50** |
| L2 功能开发 | Frugal | qwen3.6-flash | qwen3.6-flash | qwen3-coder-next | qwen3.6-flash | **~$0.50** |
| L2 功能开发 | Brain | deepseek-v4-pro | qwen3.6-plus | qwen3-coder-next | qwen3.6-flash | **~$1.20** |
| L2 功能开发 | MaxQ | deepseek-v4-pro(thinking) | qwen3.7-max | deepseek-v4-pro | qwen3.7-max | **~$5.00** |
| L3 架构重构 | Frugal | qwen3.6-flash | qwen3.6-flash | qwen3-coder-next | qwen3.6-flash | **~$1.50** |
| L3 架构重构 | Brain | deepseek-v4-pro | qwen3.6-plus/qwen3.7-max | qwen3-coder-next | qwen3.6-plus | **~$4.00** |
| L3 架构重构 | MaxQ | deepseek-v4-pro(thinking) | qwen3.7-max | deepseek-v4-pro | qwen3.7-max | **~$12.00** |

> *Frugal 模式 L3 虽可用但**不推荐** — 架构重构用 flash 模型风险高。

### 7.2 长期维护项目 vs 一次性项目的累计成本

| 时间跨度 | 大脑层分配 (L2) | Frugal |
|---|---|---|
| 1个项目 (1次) | $1.20 | $0.50 |
| 10次迭代 (月) | $12.00 | $5.00 |
| 50次迭代 (半年) | $60.00 | $25.00 |
| 200次迭代 (两年) | $240.00 | $100.00 |

对于长期维护项目，额外 $140 换取两年内 200 次高质量决策，ROI 极高。这验证了**长期项目必须用大脑层分配或全量运算**的策略。

---

## 八、关键决策原则

1. **默认大脑层分配** — 让 Supervisor 根据项目体量智能选择
2. **长期项目不省钱** — 架构决策质量影响每次后续迭代，初始省下的 token 会被低质量决策的返工成本反噬
3. **Frugal 模式绝不用于大脑层** — Supervisor 在 Frugal 模式用 qwen3.6-flash 只是降低推理成本，但仍保留基本决策能力
4. **DeepSeek 折扣结束后重新评估** — 如果 deepseek-v4-pro 太贵，L2 标准项目的大脑层可考虑降级到 qwen3.7-max
5. **Coder 固定用 qwen3-coder-next** — 代码生成专用模型优于通用模型，且价格最低
6. **未来的本地算力预留** — 本地 LLM 作为可选扩展（默认关闭），未来有 GPU 资源时可零成本处理高频重复工作
7. **用户始终有最终选择权** — 任何项目都可以覆写预算模式

---

## 九、文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `projects/AgentLab/runs/task_0018/MODEL_TIER_WHITEPAPER_V2.md` | **新增** | 本白皮书 |
| `config/model_providers.yml` | **更新** | 模型名+价格注释 |
| `config/model_profiles.yml` | **更新** | 新增三层 profiles |
| `config/execution_policy.yml` | **更新** | 新增预算模式+项目体量策略 |
| `config/budget_profiles.yml` | **重写** | L1/L2/L3 × 三模式 |
| `config/routing_rules.yml` | **更新** | 项目体量关键词 |
| `config/agent_registry.yml` | **更新** | 模型引用同步 |