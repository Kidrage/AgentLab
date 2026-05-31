# AgentLab 模型分层白皮书 v3.0 — 事实校准版 + 可执行路由方案

> 版本：3.0 corrected  
> 日期：2026-05-31  
> 输入文件：`MODEL_TIER_WHITEPAPER_V2.md`  
> 修订目标：删除事实性幻觉、避免把价格误读带进架构决策、把“模型清单白皮书”改成“可执行的 AgentLab 模型路由策略”。

---

## 0. 结论先行

v2.0 的总体方向是对的：AgentLab 确实需要按照项目体量、风险等级、预算模式，把不同 Agent 分配给不同模型。但 v2.0 有几个会直接误导工程实现的硬伤：

1. **DeepSeek V4 价格被误读**  
   v2.0 把 `deepseek-v4-pro` 的 75% 折扣到期理解成“到期后涨回 4 倍”。按 DeepSeek 官方价格页，当前展示的是：
   - `deepseek-v4-flash`: cache miss $0.14 / 1M input，cache hit $0.0028 / 1M input，output $0.28 / 1M。
   - `deepseek-v4-pro`: cache miss $0.435 / 1M input，cache hit $0.003625 / 1M input，output $0.87 / 1M。
   - 官方说明是 Pro 在折扣结束后“正式调整为原价 1/4”，不是简单恢复到 $1.74 / $3.48。

2. **DeepSeek Flash 的价格写错了**  
   v2.0 把 `deepseek-v4-flash` 写成和 Pro 一样贵，这是明显错误。Flash 实际是极低成本通用模型，不能简单被 `qwen3.6-flash` 替代。

3. **Qwen / DashScope / OpenRouter 价格混在一起了**  
   v2.0 表格里有些价格是 OpenRouter 美元价，有些描述像 DashScope 官方价，还有些是估算价。正确做法不是写一个“全球统一价格表”，而是把 provider 明确拆开：
   - `openrouter`：统一 API、美元计价、适合多模型切换。
   - `dashscope_cn`：中国内地，北京资源区，人民币计价，有免费额度。
   - `dashscope_intl`：新加坡/国际资源区，人民币计价，无免费额度。
   - `deepseek_official`：DeepSeek 官方 API，美元计价，价格当前明显优于 v2.0 的假设。

4. **本地 MoE 显存估算错误**  
   “35B / 3B 激活，所以 FP16 约 8GB”这个结论不成立。激活参数少只降低每 token 计算量，不代表显存只存激活专家。除非有专家卸载/分层加载，否则模型权重仍接近总参数规模。35B FP16 权重大约 70GB，INT4 理论权重约 17.5GB，再加 KV cache、runtime、量化开销，实际通常需要 20GB+ 级别显存或内存卸载策略。

5. **模型选择不应只按“项目大小”，还要按“风险等级”**  
   小项目也可能高风险，例如鉴权、删除数据、财务接口、CI/CD、生产配置。大项目也可能低风险，例如纯文档重构或实验原型。v3.0 改为：`项目体量 Size × 风险等级 Risk × 预算模式 Budget` 三轴决策。

---

## 1. 事实校准：只保留可验证、可落地的模型信息

### 1.1 DeepSeek 官方 API 快照

| 模型 | 适合角色 | 上下文 | 最大输出 | cache hit 输入价 | cache miss 输入价 | 输出价 | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| `deepseek-v4-flash` | Frugal Supervisor、摘要、分类、低风险路由、轻量审查 | 1M | 384K | $0.0028 / 1M | $0.14 / 1M | $0.28 / 1M | **非常便宜，应保留** |
| `deepseek-v4-pro` | 高风险规划、架构决策、复杂 bug 定位、MaxQ 审查 | 1M | 384K | $0.003625 / 1M | $0.435 / 1M | $0.87 / 1M | **比 v2.0 假设便宜很多** |

设计影响：
- v2.0 的“DeepSeek 太贵，所以 L2 尽量换 Qwen”这个结论需要撤回。
- `deepseek-v4-pro` 可以作为 L2/L3 高风险规划模型，但不必让所有 Agent 都用它。
- `deepseek-v4-flash` 是 Frugal 模式强候选，尤其适合低风险、文本型、非多模态任务。

### 1.2 Qwen via OpenRouter 快照

| 模型 | 适合角色 | 上下文 | 输入价 | 输出价 | 结论 |
|---|---:|---:|---:|---:|---|
| `qwen/qwen3.7-max` | 高质量 RepoScout、复杂代码理解、跨文件计划复核 | 1M | $1.25 / 1M | $3.75 / 1M | 贵，但适合关键感知/复核 |
| `qwen/qwen3.6-plus` | Balanced 感知层、接口分析、常规规划 | 1M | $0.325 / 1M | $1.95 / 1M | 稳定均衡，但不一定比 DeepSeek Pro 便宜多少 |
| `qwen/qwen3.6-flash` | 轻量摘要、批处理、快速分类、低成本审查 | 1M | $0.1875 / 1M | $1.125 / 1M | 好用，但输出价高于 DeepSeek Flash |
| `qwen/qwen3-coder-next` | 低成本 coding agent、代码草稿、局部补丁 | 262K | $0.11 / 1M | $0.80 / 1M | 可以作为默认 API Coder，但不是唯一选择 |

设计影响：
- Qwen 仍然非常适合中文、代码仓库理解、多模态/视觉相关场景。
- 不应再写“Qwen Flash 比 DeepSeek Flash 便宜 9.3x”这种结论；按官方 DeepSeek 价，DeepSeek Flash 反而更便宜。
- `qwen3-coder-next` 可作为默认 Coder，但对于真实工程，最好让 Coder 输出 patch plan 或 diff，再由测试/审查闭环，而不是盲信一次生成。

### 1.3 DashScope 官方 API 快照

DashScope 价格按地域、部署范围、上下文长度、是否思考模式、Batch、缓存等变化。AgentLab 不应把 DashScope 价格硬转换成一个固定美元表，而应在配置里显式写 provider profile：

```yaml
providers:
  dashscope_cn:
    region: cn-beijing
    currency: CNY
    note: 中国内地资源区，可能有免费额度，适合大陆网络与阿里云生态。
  dashscope_international:
    region: singapore
    currency: CNY
    note: 国际资源区，无免费额度，适合非中国内地部署。
  openrouter:
    currency: USD
    note: 多模型统一入口，价格和可用性以 OpenRouter 当前注册表为准。
  deepseek_official:
    currency: USD
    note: DeepSeek 官方 API，当前 V4 Flash/Pro 成本非常有竞争力。
```

---

## 2. v3.0 的核心设计原则

### 2.1 从“模型排行榜”改成“任务路由系统”

v2.0 最大的问题不是列错几个数字，而是思路太像“模型导购表”。AgentLab 真正需要的是：

```text
用户任务 → 项目体量判断 → 风险等级判断 → 预算模式 → Agent 编排 → 模型选择 → 测试/审查门禁 → 归档
```

也就是说，模型只是执行层资源，不能把架构决策建立在“某模型最强”“某模型最便宜”这种静态判断上。

### 2.2 体量 Size 与风险 Risk 必须分开

#### Size：工作量 / 上下文规模

| Size | 判断标准 | 典型任务 |
|---|---|---|
| S0 Tiny | 单文件、无依赖、无架构影响，预计上下文 < 8K | 改 README、改配置注释、修小 typo |
| S1 Small | 1–5 文件，局部功能，预计上下文 8K–30K | 加 CLI 参数、修函数 bug、补单元测试 |
| S2 Medium | 5–20 文件，跨模块接口，预计上下文 30K–120K | 新功能模块、API endpoint、数据流改造 |
| S3 Large | 20+ 文件，架构相关，预计上下文 120K–500K | 重构插件架构、引入任务队列、多 Agent 编排 |
| S4 XLarge | 多仓库/长期项目，预计上下文 500K+ | 平台化 AgentLab、长期维护系统、跨服务迁移 |

#### Risk：失败代价 / 返工代价

| Risk | 判断标准 | 必要门禁 |
|---|---|---|
| R0 Low | 原型、草稿、可丢弃脚本 | 可跳过二次审查 |
| R1 Normal | 常规功能，不涉及生产/权限/数据损坏 | 必须跑测试或静态检查 |
| R2 High | 鉴权、支付、删除、数据库迁移、生产配置、核心架构 | 双模型审查 + 测试计划 |
| R3 Critical | 安全边界、不可逆数据操作、线上发布、合规/隐私 | MaxQ 路由 + 人类确认 + 回滚方案 |

### 2.3 预算 Budget 只决定“多豪华”，不决定“要不要安全”

| Budget | 目标 | 允许牺牲 | 不允许牺牲 |
|---|---|---|---|
| `frugal` | 最低成本跑通 | 推理深度、审查覆盖率、模型强度 | 高风险任务的测试/确认门禁 |
| `balanced` | 默认方案，质量/成本平衡 | 不必要的全量上下文扫描 | 核心接口理解、测试闭环 |
| `max_quality` | 关键任务高可靠 | 成本、速度 | 事实校验、双模型复核、回滚计划 |

---

## 3. AgentLab v3.0 推荐 Agent 编排

### 3.1 Agent 角色重新定义

| Agent | 主要责任 | 不该做什么 |
|---|---|---|
| Supervisor | 判断 Size/Risk/Budget，拆任务，生成执行计划 | 不直接写大量代码 |
| RepoScout | 扫描仓库结构、定位相关文件、生成 repo map | 不做业务决策 |
| InterfaceMapper | 找接口契约、数据结构、调用链、边界条件 | 不做大范围重构 |
| Coder | 生成 patch / diff / 实现计划 | 不跳过测试、不自行修改无关文件 |
| TesterAuditor | 设计测试、执行结果解释、回归风险审查 | 不只做格式化检查 |
| Verifier | 独立复核是否满足用户需求 | 不重复 Coder 的话 |
| Archivist | 记录变更、决策理由、后续 TODO | 不参与实时决策 |

### 3.2 推荐模型路由矩阵

#### Frugal 模式

| Agent | S0/S1 Low Risk | S2 Medium | S3+ 或 R2+ |
|---|---|---|---|
| Supervisor | `deepseek-v4-flash` 或 `qwen3.6-flash` | `deepseek-v4-flash` | 不推荐 Frugal，自动升级到 Balanced |
| RepoScout | 跳过或 `deepseek-v4-flash` | `qwen3.6-flash` | 自动升级 |
| InterfaceMapper | 跳过 | 按需 `qwen3.6-flash` | 自动升级 |
| Coder | `qwen3-coder-next` | `qwen3-coder-next` | 自动升级 |
| TesterAuditor | 轻量规则 + `deepseek-v4-flash` | `qwen3.6-flash` | 自动升级 |
| Archivist | 跳过或规则模板 | 规则模板 | 自动升级 |

Frugal 的定位：
- 适合实验脚本、一次性 demo、小 bug。
- 不适合架构重构、插件核心、私有格式解析、数据迁移、安全相关代码。

#### Balanced 模式（默认）

| Agent | S1 Small | S2 Medium | S3 Large | R2 High Risk 附加 |
|---|---|---|---|---|
| Supervisor | `qwen3.6-plus` 或 `deepseek-v4-flash` | `deepseek-v4-pro` | `deepseek-v4-pro` | 必须输出风险清单 |
| RepoScout | 按需 `qwen3.6-flash` | `qwen3.6-plus` | `qwen3.7-max` 或 `qwen3.6-plus` | 必须生成相关文件列表 |
| InterfaceMapper | 跳过或 `qwen3.6-plus` | `qwen3.6-plus` | `qwen3.7-max` | 必须列接口契约 |
| Coder | `qwen3-coder-next` / 外部 IDE AI | `qwen3-coder-next` / 外部 IDE AI | 外部 IDE AI + 分批 patch | 不允许一次性大改 |
| TesterAuditor | `qwen3.6-flash` | `qwen3.6-plus` | `qwen3.6-plus` | 独立模型复核 |
| Verifier | 跳过或规则 | `deepseek-v4-flash` | `qwen3.6-plus` | 必须执行 |
| Archivist | 规则模板 | `qwen3.6-flash` | `qwen3.6-plus` | 必须记录回滚点 |

Balanced 的定位：
- AgentLab 默认模式。
- 适合真实项目日常开发。
- 核心是“不要所有步骤都用最贵模型”，但关键节点必须用强模型。

#### Max Quality 模式

| Agent | 推荐模型 | 额外要求 |
|---|---|---|
| Supervisor | `deepseek-v4-pro` | 输出架构计划、失败模式、回滚策略 |
| RepoScout | `qwen3.7-max` | 仓库级结构图 + 相关文件排名 |
| InterfaceMapper | `qwen3.7-max` | 数据结构、接口契约、调用链 |
| Researcher | `qwen3.6-plus` 或外部搜索工具 | 只在涉及外部 API/库/论文时启用 |
| Coder | 外部 IDE AI / `qwen3-coder-next` / 高级 coder 模型 | 分 patch，不允许一次性大爆改 |
| TesterAuditor | `qwen3.7-max` + `deepseek-v4-pro` 交叉审查 | 双模型复核，关注不同错误模式 |
| Verifier | 与 Coder 不同模型家族 | 防止同源幻觉 |
| Archivist | `qwen3.6-plus` | 完整 changelog、风险、测试结果 |

MaxQ 的定位：
- 核心架构、生产安全、长期主干、不可逆操作。
- 不是“全部都用最贵模型”，而是“关键决策双模型 + 强门禁”。

---

## 4. 更合理的模型选择原则

### 4.1 大脑层：首选不是永远 DeepSeek，也不是永远 Qwen

推荐逻辑：

```text
若任务低风险 + 轻量：DeepSeek Flash / Qwen Flash
若任务中等复杂：Qwen Plus 或 DeepSeek Pro
若任务高风险 / 架构级：DeepSeek Pro 生成计划 + Qwen Max/Plus 复核
若任务偏中文、多模态、前端/仓库理解：优先 Qwen
若任务偏长链推理、规划、失败模式分析：优先 DeepSeek Pro
```

### 4.2 执行层：Coder 不应该“自由发挥”

Coder 的输出必须被限制为以下三种之一：

1. `patch_plan`：列要改哪些文件、为什么改、每个文件改什么。
2. `diff`：只输出精确 patch。
3. `implementation_notes`：给外部 IDE/Codex/Claude Code/Cline 的任务提示。

不要让 Coder 在没有 RepoScout 和 InterfaceMapper 的情况下直接改大型项目。

### 4.3 审查层：要用“不同模型家族”减少同源错误

如果 Coder 用 Qwen，审查尽量用 DeepSeek。  
如果 Coder 用 DeepSeek，审查尽量用 Qwen。  
如果 Coder 用外部 IDE AI，审查层至少要用一个独立 API 模型。

这比“所有 Agent 都用同一个最强模型”更稳。

### 4.4 缓存策略：不要幻想自动 cache hit

缓存只有在这些条件满足时才可靠：

- 同一 provider。
- 相同或高度稳定的 prompt prefix。
- 仓库上下文作为固定前缀注入。
- AgentLab runtime 显式保留 `repo_context_hash`、`prompt_prefix_hash`、`provider_cache_id`。

错误假设：

```text
RepoScout 看过文件 A → InterfaceMapper 一定 cache hit
```

正确策略：

```text
AgentLab 构造统一 repo_context_block，所有后续 Agent 复用同一 prefix/context id。
```

---

## 5. 建议的配置文件结构

### 5.1 `model_catalog.yml`

```yaml
schema_version: 3
last_verified: "2026-05-31"
valid_until_days: 14

models:
  deepseek_v4_flash:
    provider: deepseek_official
    model_id: deepseek-v4-flash
    context_window: 1000000
    max_output: 384000
    strengths: [cheap, fast, long_context, routing, summarization]
    weaknesses: [less_deep_than_pro]
    pricing:
      currency: USD
      input_cache_hit_per_m: 0.0028
      input_cache_miss_per_m: 0.14
      output_per_m: 0.28

  deepseek_v4_pro:
    provider: deepseek_official
    model_id: deepseek-v4-pro
    context_window: 1000000
    max_output: 384000
    strengths: [planning, reasoning, risk_analysis, long_context]
    weaknesses: [slower_than_flash]
    pricing:
      currency: USD
      input_cache_hit_per_m: 0.003625
      input_cache_miss_per_m: 0.435
      output_per_m: 0.87

  qwen3_7_max_openrouter:
    provider: openrouter
    model_id: qwen/qwen3.7-max
    context_window: 1000000
    strengths: [repo_understanding, coding_agents, chinese, long_context]
    pricing:
      currency: USD
      input_per_m: 1.25
      output_per_m: 3.75

  qwen3_6_plus_openrouter:
    provider: openrouter
    model_id: qwen/qwen3.6-plus
    context_window: 1000000
    strengths: [balanced, repo_understanding, chinese, multimodal]
    pricing:
      currency: USD
      input_per_m: 0.325
      output_per_m: 1.95

  qwen3_6_flash_openrouter:
    provider: openrouter
    model_id: qwen/qwen3.6-flash
    context_window: 1000000
    strengths: [fast, cheap, batch, summary]
    pricing:
      currency: USD
      input_per_m: 0.1875
      output_per_m: 1.125

  qwen3_coder_next_openrouter:
    provider: openrouter
    model_id: qwen/qwen3-coder-next
    context_window: 262000
    strengths: [coding_agent, local_workflow, cheap_coder]
    pricing:
      currency: USD
      input_per_m: 0.11
      output_per_m: 0.80
```

### 5.2 `routing_policy.yml`

```yaml
schema_version: 3

default_budget: balanced

risk_auto_upgrade:
  R2: balanced
  R3: max_quality

size_thresholds:
  S0:
    files_max: 1
    context_tokens_max: 8000
  S1:
    files_max: 5
    context_tokens_max: 30000
  S2:
    files_max: 20
    context_tokens_max: 120000
  S3:
    files_min: 21
    context_tokens_max: 500000
  S4:
    context_tokens_min: 500000

risk_keywords:
  high:
    - auth
    - permission
    - payment
    - billing
    - database migration
    - delete
    - production
    - security
    - private key
    - token
    - CI/CD
    - release
    - deployment
    - schema migration
  critical:
    - irreversible
    - user data
    - credential
    - compliance
    - production database
    - access control
```

### 5.3 `agent_model_profiles.yml`

```yaml
profiles:
  frugal:
    supervisor: deepseek_v4_flash
    reposcout: qwen3_6_flash_openrouter
    interface_mapper: skip_unless_required
    coder: qwen3_coder_next_openrouter
    tester_auditor: deepseek_v4_flash
    verifier: skip_unless_required
    archivist: template_only

  balanced:
    supervisor:
      S0: deepseek_v4_flash
      S1: qwen3_6_plus_openrouter
      S2: deepseek_v4_pro
      S3: deepseek_v4_pro
      S4: deepseek_v4_pro
    reposcout:
      S0: skip
      S1: qwen3_6_flash_openrouter
      S2: qwen3_6_plus_openrouter
      S3: qwen3_7_max_openrouter
      S4: qwen3_7_max_openrouter
    interface_mapper:
      S0: skip
      S1: skip_unless_required
      S2: qwen3_6_plus_openrouter
      S3: qwen3_7_max_openrouter
      S4: qwen3_7_max_openrouter
    coder: qwen3_coder_next_openrouter
    tester_auditor:
      low: deepseek_v4_flash
      normal: qwen3_6_plus_openrouter
      high: qwen3_6_plus_openrouter
    verifier:
      low: skip_unless_required
      normal: deepseek_v4_flash
      high: deepseek_v4_pro
    archivist:
      low: template_only
      normal: qwen3_6_flash_openrouter
      high: qwen3_6_plus_openrouter

  max_quality:
    supervisor: deepseek_v4_pro
    reposcout: qwen3_7_max_openrouter
    interface_mapper: qwen3_7_max_openrouter
    researcher: qwen3_6_plus_openrouter
    coder: qwen3_coder_next_openrouter
    tester_auditor:
      primary: qwen3_7_max_openrouter
      secondary: deepseek_v4_pro
    verifier: deepseek_v4_pro
    archivist: qwen3_6_plus_openrouter
```

---

## 6. Runtime 执行流程

### 6.1 标准流程

```text
1. Intake
   - 读取 user_request.md
   - 识别目标、限制、危险操作、期望预算

2. Classify
   - 判断 Size: S0–S4
   - 判断 Risk: R0–R3
   - 若 R2/R3，强制升级预算或增加审查门禁

3. Context Build
   - RepoScout 生成 repo map
   - InterfaceMapper 只读取相关接口，不全仓库乱扫
   - 生成 repo_context_hash

4. Plan
   - Supervisor 输出 patch_plan
   - 高风险任务必须列 rollback_plan

5. Execute
   - Coder 分批输出 diff
   - 每批 patch 都绑定目标文件与测试项

6. Test / Audit
   - TesterAuditor 运行或解释测试
   - Verifier 检查是否满足原始需求

7. Archive
   - 写 changelog
   - 写 decisions.md
   - 写 known_risks.md
```

### 6.2 高风险任务必须增加的门禁

```yaml
high_risk_gates:
  - require_human_confirmation_before_write
  - require_backup_or_git_clean_state
  - require_rollback_plan
  - require_test_plan
  - require_independent_model_review
  - require_changed_files_summary
```

---

## 7. 更合理的成本估算方式

v2.0 的“L2 约 $1.20，L3 约 $4.00”这类估算太死。建议改为公式化估算：

```text
cost = Σ(input_tokens_miss × miss_price)
     + Σ(input_tokens_hit × hit_price)
     + Σ(output_tokens × output_price)
```

每次运行记录：

```yaml
run_cost_record:
  task_id: task_0018
  model_calls:
    - agent: supervisor
      model: deepseek-v4-pro
      input_tokens: 52000
      cache_hit_tokens: 30000
      output_tokens: 4200
    - agent: reposcout
      model: qwen/qwen3.6-plus
      input_tokens: 90000
      output_tokens: 6000
  total_estimated_usd: auto_calculated
```

不要在白皮书里承诺固定任务成本。真实成本受以下因素影响：
- 输出长度。
- 是否命中缓存。
- 是否跨 provider。
- 是否把整个仓库塞进上下文。
- Coder 是否多轮失败重试。
- 是否使用外部 IDE AI，而不是 API Coder。

---

## 8. 对 v2.0 内容的保留 / 删除 / 修改建议

| v2.0 内容 | 处理 | 原因 |
|---|---|---|
| L1/L2/L3 项目体量 | 修改保留 | 思路对，但要升级为 S0–S4 + Risk |
| 三层预算策略 | 保留 | 方向正确 |
| DeepSeek 折扣结束后大涨 | 删除 | 官方价格解释与 v2.0 结论不一致 |
| DeepSeek Flash 被 Qwen Flash 替代 | 删除 | Flash 实际很便宜，应该保留 |
| “完整模型清单” | 删除 | 易过期，不适合白皮书核心 |
| 本地模型 FP16 8GB 估算 | 删除 | MoE 显存理解错误 |
| Coder 固定 qwen3-coder-next | 修改 | 可作默认，但应允许外部 IDE AI / 其他 coder 模型 |
| Cache hit 成本估算 | 修改 | 需要显式 prefix/cache 策略，不能默认跨 Agent 命中 |
| 全量运算 = 所有 Agent 最强模型 | 修改 | 更合理是关键节点双模型复核，而不是全员最贵 |

---

## 9. 最终推荐方案

### 9.1 默认策略

AgentLab 默认使用 `balanced`：

```text
Supervisor: 根据 Size/Risk 自动选择 DeepSeek Flash / Qwen Plus / DeepSeek Pro
RepoScout: 小任务跳过，中任务 Qwen Plus，大任务 Qwen Max
InterfaceMapper: 只在跨文件/接口变更时启用
Coder: qwen3-coder-next 或外部 IDE AI
TesterAuditor: 与 Coder 不同模型家族
Verifier: 中高风险启用
Archivist: 中大型任务启用
```

### 9.2 省钱策略

Frugal 不等于“全用最弱模型”，而是：

```text
低风险：DeepSeek Flash + Qwen Coder Next
中风险：允许 Frugal，但必须保留测试
高风险：自动升级 Balanced
关键风险：自动升级 MaxQ
```

### 9.3 高质量策略

MaxQ 不等于“所有 Agent 乱用旗舰模型”，而是：

```text
DeepSeek Pro 做规划与风险分析
Qwen Max 做仓库理解与代码结构复核
Coder 分批输出 patch
Tester 用不同模型家族交叉审查
Verifier 强制检查原始需求
Archivist 记录回滚点和已知风险
```

---

## 10. 下一步实施清单

### Phase 1：只改配置，不动 runtime

- [ ] 新建 `config/model_catalog.yml`
- [ ] 新建/更新 `config/provider_profiles.yml`
- [ ] 重写 `config/agent_model_profiles.yml`
- [ ] 重写 `config/routing_policy.yml`
- [ ] 删除 v2.0 中硬编码的“完整模型宇宙表”
- [ ] 删除 DeepSeek 涨价假设
- [ ] 删除本地 MoE 错误显存估算

### Phase 2：实现分类器

- [ ] `project_classifier.py`: 输出 Size/Risk/Budget
- [ ] `risk_detector.py`: 检测危险关键词和危险文件路径
- [ ] `model_router.py`: 根据 profile 选择模型
- [ ] `cost_estimator.py`: 基于 token usage 估算实际成本
- [ ] `cache_manager.py`: 管理 repo_context_hash 和 provider cache 信息

### Phase 3：实现质量门禁

- [ ] `patch_plan_required` for S2+
- [ ] `rollback_plan_required` for R2+
- [ ] `dual_review_required` for R3
- [ ] `test_plan_required` for all non-trivial code tasks
- [ ] `changed_files_summary_required` for every run

---

## 11. 附：资料来源快照

- DeepSeek API Docs — Models & Pricing: https://api-docs.deepseek.com/quick_start/pricing
- 阿里云百炼 — 模型调用价格: https://help.aliyun.com/zh/model-studio/model-pricing
- 阿里云百炼 — 模型选择: https://help.aliyun.com/zh/model-studio/models
- 阿里云百炼 — Qwen-Coder: https://help.aliyun.com/zh/model-studio/qwen-coder
- OpenRouter — Qwen 模型页: https://openrouter.ai/qwen

> 注意：模型价格和上下文长度变化极快。这个白皮书不应该长期硬编码价格结论。建议每 14 天刷新一次 `model_catalog.yml`，或者在 runtime 启动时提示“价格快照已过期”。
