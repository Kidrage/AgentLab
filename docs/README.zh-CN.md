# AgentLab

[English](README.en-US.md) | [中文](README.zh-CN.md) |
[当前能力手册](CURRENT_VERSION_CAPABILITIES.zh-CN.md)

AgentLab 是本地优先、可审计的生产运行时。它把请求编译为 mission contract，选择
路线和 production pack，按角色解析已注册壳/模型，持久化可恢复状态，并把 candidate
和正式 promotion 分开。

## 阅读入口

- [`../README.md`](../README.md)：快速开始与安全边界。
- [`../AGENTS.md`](../AGENTS.md)：精简仓库地图。
- [`../OPERATING_MODEL.md`](../OPERATING_MODEL.md)：当前运行与状态模型。
- [`../DRIVER_PROTOCOL.md`](../DRIVER_PROTOCOL.md)：外部 worker 边界。
- [`CURRENT_VERSION_CAPABILITIES.zh-CN.md`](CURRENT_VERSION_CAPABILITIES.zh-CN.md)：能力域与权威来源。
- [`TEST_SUITE_GOVERNANCE.md`](TEST_SUITE_GOVERNANCE.md)：测试剪枝和执行策略。

当前验收状态只看
`../acceptance_runs/agentlab_capability_acceptance/current.yml`，不要从历史说明推断。

## 常用命令

```bash
./agentlab.sh repository-handoff --repo .
./agentlab.sh route-probe "<request>"
./agentlab.sh init-task --project <Project> --task-id <task_id> \
  --request-text "<request>"
./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan
./agentlab.sh run-agent <Role> --project <Project> --task-id <task_id> --execute
./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --execute
```

当前命令面以 `./agentlab.sh --help` 为准。角色分配来自
`config/agent_model_profiles.yml`，壳命令来自
`config/worker_invocation_contracts.yml`。

## 产物布局

- 任务状态/证据：`projects/<Project>/runs/<task_id>/`
- 候选产物：`projects/<Project>/runs/<task_id>/artifacts/`
- 正式产物：`projects/<Project>/production/`
- 被替换正式产物：`projects/<Project>/archive/`

`PROJECT_HANDOFF.md` 是唯一可写仓库 handoff。历史报告、旧 prompt pack、验收快照
和 handoff 别名只读。

## 开发验证

```bash
./agentlab.sh model-doctor
./agentlab.sh protocol-doctor
./agentlab.sh repo-hygiene-check --root .
python3 -m pytest -q <focused tests>
```

共享 runtime 改动交付前需跑一次完整测试。默认测试必须离线，不调用 live provider。

旧快照式说明保存在 `archive/readme_legacy_20260718/`。
