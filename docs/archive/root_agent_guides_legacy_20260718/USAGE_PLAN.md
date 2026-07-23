# AgentLab 使用规划 (Usage Strategy)

> 制定日期: 2026-06-19
> 角色定位: Olivia (Claude/OpenClaw) = 聊天入口+调度台 | AgentLab = 后端任务工厂

---

## 一、核心决策树：什么时候用 AgentLab？

```
收到开发任务
  │
  ├─ 简单查询/问答 (1轮对话能解决)
  │   → 自己直接回答，不调度 AgentLab
  │   → 例: "这个函数干什么的?" "怎么配置nginx?"
  │
  ├─ 小修改 (单文件, <50行改动)
  │   → 自己 Read → Edit → Verify
  │   → 例: typo修复, 加个参数, 改个报错信息
  │   → Token预算: <5K
  │
  ├─ 中等任务 (2-5文件, 功能开发, 重构)
  │   → 调度 AgentLab (L2标准路由)
  │   → budget: balanced_L2 (默认) 或 brain_allocated_L2
  │   → 例: 加个API接口, 重构一个模块, 写单元测试
  │
  ├─ 复杂任务 (架构变更, 安全审计, 多模块)
  │   → 调度 AgentLab (L3全流程路由)
  │   → budget: brain_allocated_L3 或 max_quality
  │   → 例: 微服务迁移, 权限系统重构, 性能优化
  │
  └─ 不确定
      → 先用 Supervisor 评估，根据 supervisor_plan.md 决定
```

### 决策速查表

| 任务类型 | 自己处理 | L1 frugal | L2 balanced | L3 brain | L3 max_quality |
|----------|:---:|:---:|:---:|:---:|:---:|
| 问答/解释 | ✅ | | | | |
| typo/config修改 | ✅ | | | | |
| 单文件小修改 | ✅ | ✅ | | | |
| 加个flag/option | | ✅ | | | |
| 加个API endpoint | | | ✅ | | |
| 跨文件重构 | | | ✅ | | |
| 新模块开发 | | | ✅ | ✅ | |
| 架构变更 | | | | ✅ | |
| 安全审计 | | | | ✅ | ✅ |
| 全栈项目 | | | | ✅ | ✅ |
| 竞品分析/调研 | | | ✅ | ✅ | |

---

## 二、调度工作流

### 2.1 标准下发流程

```bash
# Step 1: 初始化任务
cd ~/.openclaw/workspace/Agentlab
./agentlab.sh init-task \
  --project <ProjectName> \
  --task-id task_XXXX \
  --request-text "用户原始需求"

# Step 2: 检查仓库状态
./agentlab.sh harness-status --project <ProjectName> --task-id task_XXXX

# Step 3: 生成工作计划（Supervisor 会读取上下文、判断路由）
./agentlab.sh prepare --project <ProjectName> --task-id task_XXXX --write-plan

# Step 4: 审查 supervisor_plan.md（人工/我的review）
# 检查 scope、budget、route 是否合理

# Step 5: 运行管线
./agentlab.sh run-pipeline --project <ProjectName> --task-id task_XXXX --dry-run
# 确认无误后去掉 --dry-run

# Step 6: 检查结果
./agentlab.sh status --project <ProjectName> --task-id task_XXXX
./agentlab.sh check --project <ProjectName> --task-id task_XXXX

# Step 7: 反馈结果给用户
# 总结做了什么、花了多少钱、有什么需要注意的
```

### 2.2 快速对话式下发

```bash
# 对于不想走完整流程的快速查询:
./agentlab.sh chat --agent Supervisor --project <ProjectName>
# 然后在对话中描述需求
```

### 2.3 外部 AI 透传

当用户通过外部 AI (Codex, Claude IDE, Cline) 提需求时:
- 外部 AI 不做思考，只做转录
- 我（Supervisor）做规划
- 外部 AI 可执行 Coder 阶段（Codex Full-Driver 模式）

---

## 三、预算模式选择策略

### 3.1 默认预算: `balanced_L2`

```
绝大多数任务: balanced_L2 (~$1.20, 42K tokens)
- Supervisor: deepseek-v4-pro
- RepoScout: qwen3.6-plus
- Coder: qwen3-coder-next
- TesterAuditor + Verifier + Archivist: qwen3.6-flash
```

### 3.2 升级条件

```
升级到 balanced_L3 (~$4.00):
- 涉及架构/安全/迁移
- >5个文件改动
- 需要 Researcher + InterfaceMapper
- 代码量 >500行

升级到 max_quality (~$5-12):
- 生产环境关键路径
- 安全审计
- 用户明确要求最高质量
- 复杂重构需要 Thinking mode
```

### 3.3 降级条件

```
降级到 frugal_L1 (~$0.15):
- 简单脚本修改
- 配置变更
- 单文件小修
- 用户说"随便改改"
```

---

## 四、项目组织

### 4.1 现有项目

```
projects/
├── AgentLab/          # AgentLab 自身追踪 (dogfooding)
│   ├── agent_docs/    # 项目记忆文档
│   └── runs/          # 任务运行记录
├── 逆命天书/          # 小说项目
│   ├── agent_docs/
│   └── runs/
└── AO-SpatialAuthoring-Modular/  # 音频工具项目
    ├── agent_docs/
    └── runs/
```

### 4.2 新项目初始化

```bash
# 创建新项目目录
mkdir -p projects/<ProjectName>/agent_docs
mkdir -p projects/<ProjectName>/runs

# 初始化项目上下文
cat > projects/<ProjectName>/project_config.yml << EOF
name: <ProjectName>
repo_url: <github_url>
language: python  # or typescript, rust, etc.
default_budget: balanced_L2
EOF

# 先跑一次 Supervisor 评估
./agentlab.sh chat --agent Supervisor --project <ProjectName>
```

---

## 五、技能生命周期集成

### 5.1 当前可用技能

AgentLab 的 skill 系统与 workspace skills 互补:

```
AgentLab skills/        # AgentLab 自己的技能（生命周期管理）
├── registry.yml        # 技能注册表
├── staging/            # 待验证技能
├── active/             # 活跃技能（可注入任务）
└── retired/            # 退役技能

Workspace skills/       # Olivia 的全局技能
├── agentlab-orchestrator/  # AgentLab 调度技能
├── searxng/            # 私有搜索引擎
├── anysearch/          # 联网搜索
├── find-skills/        # 技能发现
├── skill-vetter/       # 技能审查
└── ...
```

### 5.2 技能流转

```
发现好用的技能 → skill-import-url → staging → fake-validate → promote → active
                                                                    ↓
发现不好用 → skill-retire → retired/
```

---

## 六、监控与反馈

### 6.1 日常检查

```bash
# 每天检查一次
./agentlab.sh doctor                        # 系统健康
./agentlab.sh guard-scan --project <P>      # 检查死锁
./agentlab.sh task-search --status paused   # 暂停的任务
./agentlab.sh watchdog-scan --project <P>   # 看门狗扫描
```

### 6.2 任务后审查

```bash
# 每个任务完成后
./agentlab.sh check --project <P> --task-id <T>
./agentlab.sh learning-review --project <P> --task-id <T>
./agentlab.sh skill-candidates --project <P> --task-id <T>
```

### 6.3 成本审计

```bash
# 月度检查
cat projects/<P>/runs/task_*/cost_ledger.yml | grep total_cost
```

---

## 七、与其他工具的协作

```
┌─────────────────────────────────────────────┐
│              用户 (User)                     │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Olivia (Claude Code / OpenClaw)           │
│   角色: 聊天入口, 需求理解, 调度决策          │
│   自己处理: 问答, 小修改, 读代码              │
└──────────┬──────────────────────────────────┘
           │ 下发任务
           ▼
┌─────────────────────────────────────────────┐
│   AgentLab (后端工厂)                        │
│   Supervisor → RepoScout → Coder → Audit    │
│   角色: 结构化开发, 审计追踪, 记忆维护         │
└──────────┬──────────────────────────────────┘
           │ 分发执行
           ▼
┌─────────────────────────────────────────────┐
│   执行层 (Execution)                         │
│   ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│   │ Qwen API │ │ DeepSeek │ │ Codex (IDE) │ │
│   │ (默认)   │ │ (全量)   │ │ (外部窗口)  │ │
│   └──────────┘ └──────────┘ └─────────────┘ │
└─────────────────────────────────────────────┘
```

### 工具选择矩阵

| 场景 | 工具 | 原因 |
|------|------|------|
| 快速代码QA | 我自己 | 不需要走管线 |
| 单文件修改 | 我自己 (Edit) | L1 trivial, token节约 |
| 功能开发 | AgentLab L2 | 需要 RepoScout + Audit |
| 复杂重构 | AgentLab L3 | 需要完整9 Agent |
| 联网搜索 | searxng skill | 私有引擎, 无追踪 |
| 外部 AI 编码 | AgentLab + Codex Full-Driver | 消耗 Codex 配额 |
| 终端对话 | AgentLab chat | 快速测试 Agent 响应 |
| 学习审查 | AgentLab learning-review | 生成 skill candidates |

---

## 八、演进路线图

### 短期 (本周)
- [x] 理解 AgentLab 架构
- [x] 配置 token 节约策略
- [ ] 跑通一个 L2 真实任务

### 中期 (本月)
- [ ] 积累 10+ 个任务运行记录
- [ ] 分析 cost_ledger 优化预算
- [ ] 至少 1 个 skill 从 staging 晋升 active
- [ ] 配置 webhook 通知

### 长期
- [ ] 完整 CI/CD 集成
- [ ] 自有 skill 库建设
- [ ] 多项目并行管理
- [ ] 对接 OpenClaw 实时反馈

---

*文档版本: v1.0 | 下次审查: 2026-07-19*
