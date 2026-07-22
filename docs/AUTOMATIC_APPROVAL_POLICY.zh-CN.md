# AgentLab 默认自动批准策略

AgentLab 的默认审批模式是 `auto`：任务编译、角色分配、能力选择、运行时风险检查和
外部执行器路由，统一调用 `agent_runtime.approvals.policy_engine`。任务编译阶段只标记
计划决策并声明必须运行时复核；真正的执行请求符合策略时，不会创建待人工处理的
阻塞点，而会签发一个有范围、有期限、可审计的 Policy Approval Grant。

## 三种结果

- `auto_approved`：请求在默认策略范围内，立即继续并记录授权。
- `human_required`：请求触及硬人工边界，或成本、范围、能力信息不足，暂停等待人工。
- `forbidden`：请求违反不可批准的安全边界，直接拒绝，人工也不能把该次决定改成放行。

自动授权包含 `actor`、`policy_id`、`policy_hash`、`scope_hash`、`issued_at` 和
`expires_at`。运行时必须用同一策略和完整请求重新校验；动作、能力、文件范围、成本、
策略版本或有效期任一变化都会使授权失效。

## 默认仍需人工的边界

当前默认策略保留以下人工决策：公开发布、生产晋升、Git push/merge、私密数据外传、
provider 路由变更、预算越权、破坏性操作和主观最终验收。未知外部成本、超过
`0.10 USD` 的单次预计成本、关键能力（secret/private path/destructive shell）以及
无边界的写操作也会转人工。

证据篡改、审批绕过、秘密暴露和无边界破坏操作属于 `forbidden`，不是可由人工普通
审批解除的等待项。

## 迁移规则

旧链路中的 `requires_approval` 只表示“必须进入统一策略评估”，不再天然等同于人工
阻塞。链路必须保留 `approval_mode` 和授权正文，并在真正执行前按具体参数复核。
外部执行结果仍必须经过证据和独立审查；自动批准只授权动作，不替代质量验收。

策略源是 `config/approval_policy.yml`。调整硬边界、预算或有效期会改变 `policy_hash`，
因此旧授权自动失效。
