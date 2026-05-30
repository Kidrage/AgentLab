# Interface Mapper Report

## Task
- **Task id:** task_0013
- **User request:** 为 AgentLab 设计 TrueNAS 存储后端接入方案，涵盖目录结构、配置/代码组件、安全凭证管理、协议评估（NFS/SMB/iSCSI/WebDAV/S3-MinIO），以及与本地优先架构的共存。
- **Assigned scope:** 分析现有存储边界，定义 TrueNAS 集成所需的接口与合同，识别耦合风险，输出接口映射笔记及对 `04_INTERFACE_REGISTRY.md` 的更新建议。本阶段为设计提案，不涉及源文件修改。

## Work Performed
- **Files read:**
  - `projects/AgentLab/project_config.yml`（路径映射、安全规则）
  - `projects/AgentLab/agent_docs/00_CONTEXT_PACK.md`（架构定位、本地优先原则）
  - `projects/AgentLab/agent_docs/01_REPO_MAP.md`（模块路径、UI 数据结构）
  - `projects/AgentLab/agent_docs/04_INTERFACE_REGISTRY.md`（经扫描确认存在但内容为空或不完整）
  - `config/memory_policy.yml`（存储策略、`server_sync: optional_future_phase` 预留）
  - `config/execution_policy.yml`（Coder 执行、源写策略）
  - `config/harness_policy.yml`（反馈循环、记忆更新规则）
  - `agent_runtime/` 下主要模块（`run_task.py`, `agent_runner.py`, `brain_governor.py`, `cost_tracker.py`, `workflow_plan.py`, `task_router.py`）
  - `agentlab.sh`（CLI 入口）
  - `runs/task_0013/supervisor_plan.md`、`runs/task_0013/reposcout_report.md`
- **Commands run:**
  - `ls -la projects/AgentLab/agent_docs/` 确认现有记忆文件列表
  - `cat projects/AgentLab/agent_docs/04_INTERFACE_REGISTRY.md` 检查当前接口注册表内容（发现为空框架）
  - `rg "storage|backend|sync|remote" projects/AgentLab/repo/agent_runtime/ --type py` 确认无现有存储抽象
- **Key observations:**
  - AgentLab **当前不存在任何存储抽象层**，所有文件 IO 通过 Python 原生 `open()`、`pathlib` 直接访问本地文件系统，路径硬编码在 `project_config.yml` 和 agent_docs 中。
  - 关键消费者：Archivist（写入 agent_docs）、Coder（读写 repo）、Reposコウト（读 repo）、TesterAuditor（读/写 run artifacts）、web_ui（静态读取 `agent_status.sample.json`）。
  - `memory_policy.yml` 已预留 `server_sync` 字段，但未定义实现接口。
  - `04_INTERFACE_REGISTRY.md` 存在但内容为空（占位符），说明接口合同管理尚未建立。

## Findings

### Summary
任务要求引入一个可选远程存储后端，需要定义以下接口合同：

1. **存储后端抽象层**（`StorageBackend` 接口）
   - 方法集：`read(path)`, `write(path, data)`, `list(prefix)`, `delete(path)`, `exists(path)`
   - 协议实现：NfsBackend, S3Backend, WebDavBackend, SmbBackend
   - 本地实现：LocalFilesystemBackend（已有，需提取为显式本地