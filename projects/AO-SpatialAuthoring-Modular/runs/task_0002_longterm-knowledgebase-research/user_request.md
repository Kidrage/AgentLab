# User Request

## 自然语言任务描述
全量模式驱动 AgentLab：为本地仓库 `/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular` 建立一个独立的长期开发知识库/项目记忆。这个知识库要专门收录所有关于 AO-SpatialAuthoring-Modular 的相关信息，供后续长期开发、风险预判、架构演进和交接使用。

## 目标仓库
`/Users/saintpeter/Desktop/Coding/AO-SpatialAuthoring-Modular`

## 需要重点收录的信息
1. 仓库整体结构、主要模块、模块化处理方式与边界。
2. JUCE app / plugin / standalone 的闭环结构。
3. CMake 构建结构，以及不同芯片/架构构建流程，尤其是 macOS arm64 与 x86_64。
4. SCNet / AI Stems separate / AI 模型调用链路：模型资源位置、Python/ONNX/外部模型库调用方式、运行时依赖、分发风险。
5. third_party、本地化依赖、模型资源、运行时资源与分发包关系。
6. 既有历史任务中与构建、SCNet、ONNX、回滚、Git 上传、分发验证相关的重要结论。
7. 下一步可能进行 GUI 升级，已知方向是往 Xcode 迁移；请提前 research 相关风险、迁移路径、JUCE 与 Xcode 工程组织方式、CMake/Xcode generator、macOS 多架构构建、资源 bundle、签名/分发等风险。

## 约束条件
- 主要目标是建立仓库记忆和 research 风险，不进行源码改动。
- 不安装依赖，不清理构建产物，不改 Git remote，不 push。
- 可以读取仓库结构、README、CMakeLists、模块 README、脚本、历史 AgentLab 任务工件、构建/分发文档。
- 可以输出新的 AgentLab project memory 文档和 task run 工件。
- 如果需要真实外部网络 research 但 provider 或网络不可用，记录为风险与后续待办，不要伪造。

## 期望产出
- 更新 `projects/AO-SpatialAuthoring-Modular/agent_docs/` 下的长期项目记忆。
- 至少包含：Context Pack、Repo Map、Interface Registry、Risk Register、Development Log、Decision Log、Research Notes 或等价工件。
- 研究并记录 Xcode 迁移/GUI 升级前置风险。
- 明确下一步开发建议和待补充信息。

## AgentLab 路由要求（用户已要求全量模式）
请按 L3 large_or_risky_task / full route 处理：architecture migration, multi-module, cross-module, release, performance, long-term knowledge base, Xcode migration research。必须包含 Researcher、RepoScout、InterfaceMapper、TesterAuditor、Verifier、Archivist；本任务是知识库和 research 建设，不进行目标源码改动。
