# 模型额度、探针与更新治理

## 1. 权威结论

AgentLab 只使用 CLI 实际公开并经白名单声明的非消耗型探针。探针成功只能证明
CLI/认证或模型目录在观察时可用，不能证明仍有多少额度，也不能清除已经打开的
quota breaker。

| CLI / 后端 | 安全探针 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| Agy | `agy models` | CLI 可达、模型目录可读取 | remaining、5h/weekly reset |
| Codex CLI | `codex login status` | OAuth 登录状态 | remaining、5h/weekly reset |
| Grok / Hermes xAI | `hermes auth status xai-oauth` | xAI OAuth 登录状态 | remaining、reset |

Agy 没有额度查询命令。禁止假设或伪造 `agy /usage`。三类探针的
`reports_remaining` 和 `reports_reset_at` 均为 `false`；没有 provider 运行证据时，
这两个值必须保持 `null`。

统一探针入口：

```bash
./agentlab.sh models capacity \
  --run-dir <审计目录> \
  --probe all
```

也可将 `all` 换成 `config/model_capacity.yml` 中的单个 pool id。该命令适合由外部
调度器定期调用，但它不会为了“测额度”发送一次消耗模型额度的聊天请求。

## 2. 自动 fallback 与恢复

执行过程中的真实失败是容量判断的主要证据。AgentLab 会分类
`quota_exhausted`、`rate_limited`、`auth_missing`、`network_required` 和
`model_unavailable`，并仅在 `model_capacity.yml` 已声明的同角色 fallback 链内
切换。

如果 provider 响应包含可信的 `Retry-After` 或 reset 倒计时，系统记录
`reset_at`。到时后仅放行一个 canary：

1. canary 成功：关闭 breaker，恢复主模型；
2. canary 失败：重新打开 breaker，继续 fallback；
3. provider 未给 reset：保持 `null`，不猜测 5h 或 weekly 到账时间。

当前 capacity ledger 是 run-local，因此同一次任务/运行可以自动切换和恢复；
不同任务之间尚不共享一个全局额度账本。即使未来改为共享账本，也不能承诺“永远
不卡壳”：当同角色 fallback 链耗尽、备用认证失效、网络整体不可用或替代模型不
满足模态/权限要求时，正确行为仍是阻断并留下证据，而不是静默换 provider。

## 3. 后端模型更新接口

新增或修改模型先生成提案：

```bash
./agentlab.sh models catalog-propose \
  --model-key codex_gpt_5_7_sol_high_cli_oauth \
  --entry-file /path/to/model-entry.yml
```

`model-entry.yml` 是完整 YAML mapping，可声明 `provider`、`model_id`、
`cli_model_id`、`reasoning_effort`、`max_output`、`context_window`、
`capacity_pool`、capabilities 等。提案会绑定 entry SHA-256 及旧 entry SHA-256，
不会直接修改权威 catalog。

审核后应用：

```bash
./agentlab.sh models catalog-apply --proposal <proposal-id>
```

接口会拒绝未知 provider、未知 capacity pool、非法 reasoning effort、提案内容
漂移以及 catalog 并发漂移。

catalog 注册完成后，再通过受契约和 capacity route 约束的路由提案设置角色默认
模型。单档：

```bash
./agentlab.sh models propose \
  --role Writer \
  --cli agy \
  --model gemini_3_6_flash_high_agy_oauth \
  --mode performance
```

同步 `full / performance / low` 三档：

```bash
./agentlab.sh models propose \
  --role Writer \
  --cli agy \
  --model gemini_3_6_flash_high_agy_oauth \
  --all-tiers
```

最后执行：

```bash
./agentlab.sh models apply --proposal <proposal-id>
./agentlab.sh models doctor
```

模型 catalog 更新与默认路由更新是两个独立审批动作。新模型若没有匹配的 worker
contract、role binding 和 capacity route，路由提案必须失败；接口不会替用户
隐式扩大权限或创造 fallback。
