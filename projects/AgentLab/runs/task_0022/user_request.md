# User Request

## Original Request
让 agentlab 来执行 AgentLab Codex Full-Driver 操作链规范。

## Attached Specification
用户提供了完整规范文档 `AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md`，要求按照该规范实现所有必要文件：
1. 创建 `docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md`（规范文档）
2. 创建 `agent_templates/codex_full_driver/` 下的所有角色模板
3. 更新 `DRIVER_PROTOCOL.md` 增加 codex_full_driver 模式
4. 创建 `config/execution_modes.yml` 配置文件
5. 创建 `agent_runtime/codex_artifact_validator.py` 工件验证器
6. 创建 `agent_runtime/handoff_builder.py` 交接包构建器
7. 创建 `agent_runtime/api_continuation.py` API 延续模块
8. 更新 `agentlab.sh` CLI 增加 codex 相关命令

## Explicit Constraints
- 所有工件必须写入本地 AgentLab 项目文件夹
- 不能依赖聊天记忆作为唯一真理源
- 必须保留完整的角色分离和工件隔离
- 必须生成 handoff_packet.yml 使任务可恢复

## Forbidden Assumptions
- 请勿自行扩充需求范围
- 请勿修改无关文件
- 请勿将多个角色输出合并为单一未归档的聊天响应

## Requested Execution Mode
Codex Full-Driver Mode

## Continuation Requirement
所有报告、决策、diff 和交接状态必须保存到本地，以便 AgentLab API agents 后续恢复执行。