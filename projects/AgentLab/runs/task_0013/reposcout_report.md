# RepoScout Report

## Task
- **Task id:** task_0013  
- **User request:** 为 AgentLab 设计 TrueNAS 存储后端接入方案：用户自建了一个 TrueNAS 仓库，希望 AgentLab 使用它来存放项目记忆文件（agent_docs/*.md, agent_docs/*.yml 等持久化记忆）和项目代码库（repo 目录下的源代码）。要求设计目录结构、新增配置和代码组件、安全凭证管理、与本地优先架构共存，并评估协议（NFS/SMB/iSCSI/WebDAV/S3-MinIO）。  
- **Assigned scope:** 对 AgentLab 仓库进行只读扫描，识别所有与存储、配置、同步、运行时路径、凭证管理相关的现有代码和文件，为 TrueNAS 后端设计提供上下文地图。

## Work Performed
- **Files read:**
  - `repo/agent_runtime/` 下的所有 Python 模块（入口、agent 运行器、LLM 提供者、brain 治理、成本追踪、工作流计划、任务路由）
  - `repo/config/` 下的所有 YAML/政策文件
  - `repo/web_ui/` 下的 HTML/CSS/JS
  - `repo/projects/AgentLab/agent_docs/` 下的上下文包、仓库地图、开发日志、对话日志、成本台账、同步台账
  - `repo/AGENTS.md`、`repo/README.md`、`repo/OPERATING_MODEL.md`、`repo/DRIVER_PROTOCOL.md`
  - `repo/agentlab.sh`（CLI 入口包装器）
  - `repo/project_config.yml`（项目路径映射）
- **Commands run:**
  ```bash
  # 获得完整目录树，深度不超过 4，排除 .git 和 __pycache__
  find /Users/saintpeter/Desktop/AgentLab/projects/AgentLab/repo -not \( -path "*/.git/*" -o -path "*/__pycache__/*" \) -maxdepth 4 | sort
  ```
  （输出较长，关键结构在下方表格中汇总）
- **Key observations:**
  - AgentLab 当前**没有**任何远程存储或同步组件；所有数据完全本地存储于 `projects/<ProjectName>/` 下。
  - `memory_policy.yml` 定义了“local_first”模式，但预留了 `server_sync: optional_future_phase` 和 `github_private_backup: planned_local_first_manual_sync`，表明远程同步是计划内但尚未实现。
  - `config/` 下没有 `storage_policy.yml`、`backend_config.yml` 之类文件，也没有凭证存储相关的模块。
  - `agent_runtime/` 中没有任何直接文件 IO 抽象层；所有文件路径在 `00_CONTEXT_PACK.md` 和 `01_REPO_MAP.md` 中硬编码为相对路径（基于项目根）。
  - `agentlab.sh` 是一个包装脚本，调用 `python3 -B agent_runtime/run_task.py`，没有环境变量配置外层。
  - `web_ui/` 仅为静态壳，本地文件系统读取示例 JSON，无远程端点。
  - 所有项目记忆文件（agent_docs/*）目前由 Archivist agent 在验证后手动写入本地。
  - **无任何现有后端抽象（如 `StorageBackend` 接口）**——这是设计 TrueNAS 集成时最大的空白。需要新建一个存储抽象层。

## Findings

### Summary
AgentLab 是一个**纯本地优先**、**无后端抽象**的轻量级多 agent 工作流框架。所有持久化数据（项目记忆、任务状态、代码仓库）直接存储在本地文件系统，路径由 `project_config.yml` 硬编码。现有架构中不存在任何存储层抽象、远程后端接口或凭证管理组件。因此