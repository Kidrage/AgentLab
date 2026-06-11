---
name: agentskills-io
description: >
  Standard Agent Skills SKILL.md package specification for
  composable, reusable agent capabilities.  Defines the
  frontmatter schema, skill lifecycle, filesystem layout,
  validation rules, and injection contract used by
  OpenClaw-compatible skill registries.
version: 1.0.0
license: Apache-2.0
author: OpenClaw Skills
homepage: https://agentskills.io
tags:
  - agent-skills
  - skill-spec
  - composability
  - openclaw
---

# Agent Skills — SKILL.md 标准规范

## 概述

Agent Skills 是一种可组合、可复用的智能体能力包规范。每个 Skill 由一个
`SKILL.md` 文件定义入口，搭配 frontmatter 元数据、可选脚本、测试、
和依赖声明。

## Frontmatter 必需字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Skill 唯一标识符，snake_case 或 kebab-case |
| `description` | string | 一句话描述 Skill 的用途 |
| `version` | string | 语义化版本号 |
| `license` | string | SPDX 许可证标识 |

## Frontmatter 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `author` | string | 作者或组织 |
| `homepage` | string | 项目主页 URL |
| `tags` | list | 分类标签 |
| `dependencies` | list | 依赖的其他 skill 名称 |
| `requires_network` | bool | 是否需要网络访问 |
| `requires_filesystem` | bool | 是否需要文件系统写权限 |
| `min_agent_version` | string | 最低 Agent 运行时版本 |

## 文件系统布局

```
skills/<skill-name>/
  SKILL.md          # 入口文件（必需）
  scripts/          # 可执行脚本（可选）
  tests/            # 冒烟测试（推荐）
  examples/         # 使用示例（推荐）
  CHANGELOG.md      # 变更日志（推荐）
```

## 生命周期

```
proposed → reviewed → staged → validated → active → retired
                ↘ rejected
```

## 注入约束

- 注入前必须通过风险扫描（脚本、网络、文件系统）。
- High-risk skill 注入前需要显式用户审批。
- 每个 task 注入 skill 数量受 `max_skills_per_task` 限制。
- 注入后追踪 usage ledger 并写入 task-level skill_usage.yml。