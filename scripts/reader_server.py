import os
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

PROJECT_ROOT = "/Users/saintpeter/Desktop/AgentLab/projects/Crown_of_Ash"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crown of Ash - 实时阅读器</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=Outfit:wght@300;400;600&family=Noto+Serif+SC:wght@300;400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0c10;
            --sidebar-bg: rgba(20, 22, 31, 0.7);
            --card-bg: #15161e;
            --text-color: #c9d1d9;
            --text-muted: #8b949e;
            --accent-color: #7928ca;
            --accent-glow: rgba(121, 40, 202, 0.4);
            --hover-bg: rgba(255, 255, 255, 0.05);
            --border-color: rgba(255, 255, 255, 0.08);
            --font-family: 'Inter', sans-serif;
            --font-size: 18px;
            --line-height: 1.8;
        }

        body.light-theme {
            --bg-color: #f6f8fa;
            --sidebar-bg: rgba(255, 255, 255, 0.85);
            --card-bg: #ffffff;
            --text-color: #24292f;
            --text-muted: #57606a;
            --accent-color: #0969da;
            --accent-glow: rgba(9, 105, 218, 0.25);
            --hover-bg: rgba(0, 0, 0, 0.04);
            --border-color: rgba(0, 0, 0, 0.08);
        }

        body.sepia-theme {
            --bg-color: #f4ecd8;
            --sidebar-bg: rgba(235, 222, 196, 0.85);
            --card-bg: #fdf6e3;
            --text-color: #5b4636;
            --text-muted: #8f7d6e;
            --accent-color: #b58900;
            --accent-glow: rgba(181, 137, 0, 0.25);
            --hover-bg: rgba(0, 0, 0, 0.04);
            --border-color: rgba(0, 0, 0, 0.08);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: var(--font-family);
            display: flex;
            height: 100vh;
            overflow: hidden;
            transition: background-color 0.3s ease, color 0.3s ease;
        }

        /* Sidebar styling */
        #sidebar {
            width: 320px;
            background: var(--sidebar-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            height: 100%;
            z-index: 10;
            transition: width 0.3s ease;
        }

        #sidebar-header {
            padding: 24px;
            border-bottom: 1px solid var(--border-color);
            background: linear-gradient(135deg, var(--accent-color), #ff007f);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        #sidebar-header h1 {
            font-size: 24px;
            font-weight: 800;
            letter-spacing: -0.5px;
            font-family: 'Outfit', sans-serif;
        }

        #sidebar-header p {
            font-size: 12px;
            color: var(--text-muted);
            -webkit-text-fill-color: var(--text-muted);
            margin-top: 4px;
        }

        #chapter-list {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }

        .chapter-item {
            display: flex;
            align-items: center;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 8px;
            cursor: pointer;
            border: 1px solid transparent;
            transition: all 0.2s ease;
        }

        .chapter-item:hover {
            background-color: var(--hover-bg);
        }

        .chapter-item.active {
            background: rgba(121, 40, 202, 0.1);
            border-color: var(--accent-color);
            box-shadow: 0 0 15px var(--accent-glow);
        }

        body.light-theme .chapter-item.active {
            background: rgba(9, 105, 218, 0.08);
            border-color: var(--accent-color);
        }

        .chapter-num {
            font-size: 12px;
            font-weight: 600;
            background: var(--border-color);
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 12px;
            color: var(--text-muted);
        }

        .chapter-title {
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Main reader pane */
        #main-reader {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
            position: relative;
        }

        /* Controls bar */
        #controls-bar {
            height: 64px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 32px;
            background: rgba(11, 12, 16, 0.2);
            backdrop-filter: blur(8px);
            z-index: 5;
        }

        .control-group {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .btn-control {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 6px 12px;
            font-size: 12px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-control:hover {
            border-color: var(--accent-color);
            box-shadow: 0 0 8px var(--accent-glow);
        }

        .theme-indicator {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: transform 0.2s;
        }

        .theme-indicator:hover {
            transform: scale(1.15);
        }

        .theme-dark { background-color: #0b0c10; }
        .theme-light { background-color: #ffffff; }
        .theme-sepia { background-color: #fdf6e3; }

        /* Reading area */
        #content-area {
            flex: 1;
            overflow-y: auto;
            padding: 48px 24px;
            scroll-behavior: smooth;
        }

        #reader-container {
            max-width: 720px;
            margin: 0 auto;
        }

        #chapter-heading {
            font-size: 32px;
            font-weight: 800;
            margin-bottom: 40px;
            font-family: 'Outfit', sans-serif;
            letter-spacing: -0.5px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
        }

        .novel-p {
            font-size: var(--font-size);
            line-height: var(--line-height);
            margin-bottom: 24px;
            text-align: justify;
            text-justify: inter-character;
            letter-spacing: 0.3px;
        }

        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: transparent;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-muted);
        }

        /* Font selectors */
        .font-selected {
            background-color: var(--accent-color);
            color: #fff;
        }

        /* Mobile adjustments */
        @media (max-width: 768px) {
            #sidebar {
                width: 0px;
                position: absolute;
                left: 0;
            }
            #sidebar.open {
                width: 280px;
            }
        }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div id="sidebar">
        <div id="sidebar-header">
            <h1>Crown of Ash</h1>
            <p>实时自动跑批阅读器 • 连载中</p>
        </div>
        <div id="chapter-list">
            <!-- Dynamic chapter items -->
            <div style="color:var(--text-muted); text-align:center; padding-top:20px;">加载章节中...</div>
        </div>
    </div>

    <!-- Main reader -->
    <div id="main-reader">
        <div id="controls-bar">
            <div class="control-group">
                <button class="btn-control" id="toggle-sidebar">📖 目录</button>
            </div>
            <div class="control-group">
                <div class="theme-indicator theme-dark" onclick="setTheme('dark')"></div>
                <div class="theme-indicator theme-light" onclick="setTheme('light')"></div>
                <div class="theme-indicator theme-sepia" onclick="setTheme('sepia')"></div>
                <button class="btn-control" onclick="adjustFontSize(-1)">A-</button>
                <button class="btn-control" onclick="adjustFontSize(1)">A+</button>
                <button class="btn-control font-btn" onclick="setFont('serif')" id="font-serif-btn">宋体</button>
                <button class="btn-control font-btn font-selected" onclick="setFont('sans')" id="font-sans-btn">黑体</button>
            </div>
        </div>
        <div id="content-area">
            <div id="reader-container">
                <h1 id="chapter-heading">欢迎阅读</h1>
                <div id="chapter-body">
                    <p class="novel-p">请在左侧选择章节开始阅读。</p>
                    <p class="novel-p">系统目前正在后台实时撰写全新章节，每写完一章，左侧目录将自动刷新同步！</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentChapterId = null;
        let knownChapters = [];

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            if (sidebar.style.width === '0px' || sidebar.style.width === '') {
                sidebar.style.width = '320px';
            } else {
                sidebar.style.width = '0px';
            }
        }

        document.getElementById('toggle-sidebar').addEventListener('click', toggleSidebar);

        function setTheme(theme) {
            document.body.classList.remove('light-theme', 'sepia-theme');
            if (theme === 'light') document.body.classList.add('light-theme');
            if (theme === 'sepia') document.body.classList.add('sepia-theme');
            localStorage.setItem('reader-theme', theme);
        }

        // Load saved theme
        const savedTheme = localStorage.getItem('reader-theme');
        if (savedTheme) setTheme(savedTheme);

        function adjustFontSize(dir) {
            const root = document.documentElement;
            const style = window.getComputedStyle(root);
            let size = parseInt(style.getPropertyValue('--font-size'));
            size = Math.max(14, Math.min(28, size + dir));
            root.style.setProperty('--font-size', size + 'px');
        }

        function setFont(font) {
            const root = document.documentElement;
            const fontSerifBtn = document.getElementById('font-serif-btn');
            const fontSansBtn = document.getElementById('font-sans-btn');
            
            document.querySelectorAll('.font-btn').forEach(btn => btn.classList.remove('font-selected'));
            
            if (font === 'serif') {
                root.style.setProperty('--font-family', "'Noto Serif SC', 'Georgia', serif");
                fontSerifBtn.classList.add('font-selected');
            } else {
                root.style.setProperty('--font-family', "'Inter', sans-serif");
                fontSansBtn.classList.add('font-selected');
            }
        }

        async function fetchChapters() {
            try {
                const res = await fetch('/api/chapters');
                const chapters = await res.json();
                
                // Compare and refresh only if updated
                if (JSON.stringify(chapters) !== JSON.stringify(knownChapters)) {
                    knownChapters = chapters;
                    renderSidebar(chapters);
                }
            } catch (err) {
                console.error('Fetch chapters error:', err);
            }
        }

        function renderSidebar(chapters) {
            const container = document.getElementById('chapter-list');
            if (chapters.length === 0) {
                container.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding-top:20px;">暂无生成好的章节...</div>';
                return;
            }
            container.innerHTML = '';
            chapters.forEach(ch => {
                const item = document.createElement('div');
                item.className = 'chapter-item';
                if (currentChapterId === ch.num) {
                    item.classList.add('active');
                }
                item.onclick = () => loadChapter(ch.num, ch.title);
                
                const numSpan = document.createElement('span');
                numSpan.className = 'chapter-num';
                numSpan.innerText = `Ch ${ch.num.toString().padStart(2, '0')}`;
                
                const titleSpan = document.createElement('span');
                titleSpan.className = 'chapter-title';
                titleSpan.innerText = ch.title;
                
                item.appendChild(numSpan);
                item.appendChild(titleSpan);
                container.appendChild(item);
            });
        }

        async function loadChapter(num, title) {
            currentChapterId = num;
            // Update active state in sidebar
            document.querySelectorAll('.chapter-item').forEach((item, idx) => {
                if (knownChapters[idx] && knownChapters[idx].num === num) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });

            document.getElementById('chapter-heading').innerText = `第 ${num.toString().padStart(2, '0')} 章：${title}`;
            const bodyContainer = document.getElementById('chapter-body');
            bodyContainer.innerHTML = '<p class="novel-p">加载中...</p>';

            try {
                const res = await fetch(`/api/chapter/${num}`);
                const data = await res.json();
                
                // Parse markdown paragraphs to clean HTML paragraphs
                const paragraphs = data.content.split('\\n');
                bodyContainer.innerHTML = '';
                paragraphs.forEach(p => {
                    const trimmed = p.trim();
                    if (!trimmed) return;
                    if (trimmed.startsWith('#')) return; // skip header lines
                    
                    const pEl = document.createElement('p');
                    pEl.className = 'novel-p';
                    // Strip basic markdown syntax like bold, italic or backticks
                    pEl.innerText = trimmed.replace(/\\*\\*/g, '').replace(/`/g, '');
                    bodyContainer.appendChild(pEl);
                });
                
                // Scroll to top
                document.getElementById('content-area').scrollTop = 0;
            } catch (err) {
                bodyContainer.innerHTML = `<p class="novel-p" style="color:red;">加载失败: ${err.message}</p>`;
            }
        }

        // Initialize and poll
        fetchChapters().then(() => {
            // Auto load first chapter if none selected
            if (knownChapters.length > 0 && currentChapterId === null) {
                loadChapter(knownChapters[0].num, knownChapters[0].title);
            }
        });
        
        setInterval(fetchChapters, 8000);
    </script>
</body>
</html>
"""

class ReaderHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute console output to keep the agent command stdout clean
        return

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
            return

        elif self.path == '/api/chapters':
            # List all chapters
            zhengwen_dir = os.path.join(PROJECT_ROOT, "正文")
            chapters = []
            if os.path.exists(zhengwen_dir):
                for f in os.listdir(zhengwen_dir):
                    if f.startswith("第") and f.endswith(".md"):
                        match = re.search(r"第(\d+)章_?(.*)\.md", f)
                        if match:
                            num = int(match.group(1))
                            title = match.group(2)
                            chapters.append({"num": num, "title": title, "filename": f})
            chapters.sort(key=lambda x: x["num"])
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(chapters, ensure_ascii=False).encode('utf-8'))
            return

        elif self.path.startswith('/api/chapter/'):
            num_str = self.path.split('/')[-1]
            try:
                num = int(num_str)
            except ValueError:
                self.send_error(400, "Bad Request")
                return

            zhengwen_dir = os.path.join(PROJECT_ROOT, "正文")
            target_file = None
            if os.path.exists(zhengwen_dir):
                for f in os.listdir(zhengwen_dir):
                    if f.startswith(f"第{num:02d}章") and f.endswith(".md"):
                        target_file = os.path.join(zhengwen_dir, f)
                        break
            
            if target_file and os.path.exists(target_file):
                with open(target_file, "r", encoding="utf-8") as f_in:
                    content = f_in.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"num": num, "content": content}, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_error(404, "Chapter Not Found")
            return

        else:
            self.send_error(404, "Not Found")

def run(port=8888):
    server_address = ('', port)
    httpd = HTTPServer(server_address, ReaderHTTPRequestHandler)
    print(f"Reader server running at: http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Server stopped.")

if __name__ == '__main__':
    port = 8888
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run(port)
