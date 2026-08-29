# AgentLab 69 ↔ 250 工作区同步

## 权威边界

- GitHub `agentlab/unified-stable` 管理源码、配置、协议、测试和文档。
- `projects/AgentLab` 与 `projects/Crown_of_Ash` 使用带哈希回执的单写者同步。
- RAG 是派生数据：首次迁移复制现有索引，之后在项目同步完成后由目标端重建。
  自动重建不重写项目内的封存快照，避免把派生回执误判为项目内容冲突。
- CLI/OAuth 主目录、`.env`、`.agents/workspaces`、缓存和任务临时状态永不传输。
- OpenClaw 仅是 Frontdesk；不允许承担 AgentLab Worker 角色。

## 防冲突规则

每次成功同步会在两端写入：

```text
.agentlab/sync/cloud_250/current.json
.agentlab/sync/cloud_250/receipts/<sync_id>.json
```

同步器比较上次回执与两端当前项目树哈希：

- 只有 69 改变：推送到 250。
- 只有 250 改变：拉回 69。
- 两端得到相同变更：更新回执。
- 两端产生不同变更：立即阻断，禁止按时间戳覆盖。

源码只允许通过 GitHub 快进到 250。小补丁也必须先提交并推送。

## 命令

```bash
# 只读检查
python3 scripts/sync_250_workspace.py status

# 首次迁移（包括当前 RAG）
python3 scripts/sync_250_workspace.py push --execute --seed-rag

# 后续自动判定方向
python3 scripts/sync_250_workspace.py auto --execute

# 安装 macOS 五分钟同步计划（先预览，再执行）
python3 scripts/sync_250_workspace.py install
python3 scripts/sync_250_workspace.py install --execute
```

计划任务允许最多约五分钟延迟。本地关机或网络不可用时不会猜测成功；下次运行会
从最后一个双方共有回执继续。任何双边漂移都需要人工合并后重新建立共同回执。
