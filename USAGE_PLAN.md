# AgentLab 使用入口

本文只保留稳定操作入口。角色、模型、执行壳和 fallback 以 `config/` 中的
权威配置为准，不在这里复制易漂移的表格。

## 创建与准备

```bash
./agentlab.sh init-task --project <Project> --task-id <task_id> \
  --request-text "<request>"

./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
```

先检查 run-local 的 `mission_contract.yml`、`workflow_plan.yml`、
`artifact_intent`、路由、production pack 和 resolved model profiles。准备阶段
不等于执行，也不允许写 production。

需要先观察路由但不创建任务时：

```bash
./agentlab.sh route-probe "<request>"
```

## 执行

```bash
# 单角色
./agentlab.sh run-agent <Role> --project <Project> --task-id <task_id> --execute

# 当前路线
./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --execute
```

执行前必须确认用户授权、外发边界、可编辑路径和 provider/worker 选择。未声明
fallback 时，后端失败应停止并留下证据，不得换模型继续。

## 状态与恢复

```bash
./agentlab.sh task-find "<query>"
./agentlab.sh watchdog-status --project <Project> --task-id <task_id>
./agentlab.sh daemon-status --project <Project>
```

状态以 `state.yml`、`progress.yml`、`lifecycle.yml`、`task_events.jsonl` 和
decision cards 为准。旧对话不是状态源。暂停、恢复和重试必须通过 operator/task
control 入口或对应 CLI 命令留下事件，不能手改成“完成”。

后台执行必须有 durable job/service receipt。`background-job` 是当前 Crown
长篇批次专用控制器，不是任意任务的通用快捷入口。

## 候选与正式产物

- 候选：`projects/<Project>/runs/<task_id>/artifacts/`
- 正式：`projects/<Project>/production/`
- 历史：`projects/<Project>/archive/`

正式发布必须经过 artifact steward 的 lineage、review、approval、archive 和 index
门禁。不要把 run report、prompt、audit log 或未验收 candidate 手工复制进
production。

## 配置检查

```bash
./agentlab.sh models show --role <Role>
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor
./agentlab.sh repo-hygiene-check --root .
```

模型调整使用配置 proposal/apply 流程。不要在 Web UI、文档、route 或 prompt 中
另建一套模型选择状态。

## 仓库交接

```bash
./agentlab.sh repository-handoff --repo .
./agentlab.sh repository-handoff --repo . --write
```

只写 `PROJECT_HANDOFF.md`。共享副本仅在明确跨端交接时生成；历史别名只读。

## 清理与测试

```bash
./agentlab.sh task-purge --project <Project> --keep-days 7
python3 -m pytest -q <focused tests>
```

测试文件不因数量多就合并。只有重复行为、重复昂贵 setup 或重复 subprocess
场景被真正删除时才合并；默认测试不得发起 live provider 调用。

旧版累计使用规划保存在
`docs/archive/root_agent_guides_legacy_20260718/USAGE_PLAN.md`，不再作为操作依据。
