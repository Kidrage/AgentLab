# User Request

## 自然语言任务描述
完善 AgentLab Web UI 并完成桌面 App 封装：

1. **Web UI 完善**：
   - agentlab_app.py 目前只是一个 shell，需要完善——自动安装依赖、错误处理、窗口图标、多窗口支持
   - Web UI 的模型选择控件需要在 HTML 中实际可用（之前只改了后端配置，前端没有切换入口）
   - 配置面板 (Tab: 配置) 应支持实时编辑和保存
   - 新增关于/帮助页面

2. **App 打包**：
   - 创建 macOS .app bundle 结构
   - 创建 Linux desktop entry
   - 创建 Windows .exe 打包脚本 (pyinstaller)
   - README 中说明如何构建和安装桌面 App

## 约束条件
- 保持 Web UI 零依赖（纯 HTML/CSS/JS）
- App 端依赖最小化（仅 pywebview）
- 不改变 AgentLab 核心逻辑