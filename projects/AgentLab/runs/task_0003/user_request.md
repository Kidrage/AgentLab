# Web-UI 设计完善任务

## 背景
web_ui 当前已有完整的静态面板（index.html 164行、styles.css 691行、app.js 655行、agent_status.sample.json 137行），task_0002 已实现了中文 i18n、Qwen 模型选择器、Coder 提供商切换等功能。现需要进一步打磨 UI 设计质量和健壮性。

## 需要完善的设计点（按优先级排列）

### 1. 暗色模式支持
- 使用 CSS 自定义属性和 prefers-color-scheme 媒体查询实现暗色模式
- 添加暗色模式手动切换按钮（位于顶栏右侧 task-pill 旁边）
- 所有组件（卡片、侧栏、事件列表、计量条等）需在暗色模式下保持良好的可读性和对比度
- 使用 localStorage 持久化用户偏好，优先级：手动选择 > 系统偏好

### 2. 数据实时刷新
- 添加定时轮询机制（每 30 秒重新 fetch agent_status.sample.json）
- 在顶栏或摘要区域显示"最后刷新时间"标签
- 添加手动刷新按钮，点击时立即拉取数据并显示加载指示器
- 数据变化时计量条和进度条做平滑 CSS transition（已部分实现，需确认全覆盖）

### 3. 可访问性（A11y）增强
- 为所有交互元素（按钮、输入框、选择器）添加 aria-label
- 分段控件添加 role="tablist"、role="tab"、aria-selected 等 ARIA 属性
- 确保所有可交互元素有可见的 :focus-visible 样式
- 计量条添加 role="progressbar"、aria-valuenow、aria-valuemin、aria-valuemax
- Agent 卡片添加适当的语义角色

### 4. 动画与微交互
- Agent 卡片 hover 时添加微妙的 transform 上浮效果和阴影增强
- 状态筛选切换时卡片做淡入淡出过渡
- 路由步骤中标记当前/活跃步骤的视觉脉冲
- 事件列表新条目可采用微妙滑入
- 确保所有动画可用 prefers-reduced-motion 媒体查询禁用

### 5. 空状态与错误状态完善
- 搜索无结果时显示友好的空状态提示（含图标/emoji 和文案"没有匹配的 Agent"已有，但可增强视觉表现）
- 数据加载失败时显示错误提示和重试按钮
- fetch 请求添加超时处理（如 10 秒超时）
- 各区域（agent 卡片区、事件列表）添加独立的 skeleton 加载占位

### 6. Agent 卡片展开/折叠
- 点击 agent 卡片可展开查看详细信息面板
- 展开内容包括：最近日志摘要、关联的 report 文件路径
- 使用 CSS max-height transition 做平滑展开/折叠动画
- 同一时间只允许一个卡片展开（手风琴模式）

### 7. 通知/提示系统
- 实现轻量 toast 通知组件（纯 CSS + JS，无需额外依赖）
- 支持 success / error / warning / info 四种类型
- 自动消失（默认 3 秒），可手动点击关闭
- 多条通知垂直堆叠显示在右上角
- 进入/退出动画

### 8. 安全性修复
- app.js 第592行硬编码了 DashScope API key（Bearer sk-92d436...），必须移除
- 测试按钮改为提示用户配置自己的 API key（通过浏览器 prompt 或配置输入框）
- 不在前端代码中存储任何密钥

### 9. 响应式增强
- 在 480px 断点以下：摘要指标改为 2 列布局
- 侧栏在小屏变为可折叠的底部面板（或保留 sticky 但优化宽度）
- 分段控件按钮在小屏适当缩小
- Agent 卡片在窄屏下 meta-cell 保持可读性

### 10. 数据导出
- 在工具栏或侧栏添加"导出 JSON"按钮
- 点击后将当前快照数据导出为 .json 文件下载（使用 Blob + URL.createObjectURL）
- 事件日志区域添加"复制全部事件"按钮

## Agent 协作路线
1. **Supervisor** → 分析需求，制定实施路线和 token 预算
2. **RepoScout** → 读取 web_ui/ 下所有文件，确认当前代码结构
3. **InterfaceMapper** → 追踪 index.html、app.js、styles.css 之间的接口关系，确保改动不破坏现有功能
4. **Coder** → 逐项实施设计改进，每次改动后自测确认无回归
5. **TesterAuditor** → 审计所有改动，检查功能完整性、无回归、无安全漏洞
6. **Archivist** → 更新项目记忆、开发日志、连续性记录

## 禁止事项
- 不能删除任何现有功能
- 不能改变现有的中文界面语言
- 不能引入任何外部依赖（保持零依赖纯 HTML/CSS/JS）
- 不能修改 config/execution_policy.yml
- 不能修改 agent_runtime/ 下的任何 Python 代码
- 只能修改 web_ui/ 目录下的文件