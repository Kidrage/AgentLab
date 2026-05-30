/* ================================================================
   AgentLab — 完整的交互式 Web UI 应用
   ================================================================ */

/* ───── 默认快照数据 ───── */
const DEFAULT_SNAPSHOT = {
  generatedAt: new Date().toISOString(),
  project: "AgentLab",
  taskId: "task_0004",
  taskStatus: "进行中",
  stage: "实现阶段",
  coderProvider: "codex-plus",
  coderQuotaRemaining: 8500,
  coderQuotaWarningThreshold: 2000,
  brainProvider: "DeepSeek",
  route: ["Supervisor","RepoScout","Researcher","InterfaceMapper","Coder","CodexPromptGenerator","TesterAuditor","Archivist"],
  agents: [
    { name:"Supervisor", role:"确定范围、路线、Token 预算、停止规则和移交。", status:"complete", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"管理层", canEdit:false, budgetTokens:2700, usedTokens:620 },
    { name:"RepoScout", role:"读取仓库结构并报告相关上下文。", status:"complete", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"管理层", canEdit:false, budgetTokens:3200, usedTokens:780 },
    { name:"Researcher", role:"在需要时收集当前外部或参考上下文。", status:"skipped", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"管理层", canEdit:false, budgetTokens:2800, usedTokens:0 },
    { name:"InterfaceMapper", role:"追踪 UI、运行时、配置、I/O 和集成之间的边界。", status:"complete", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"管理层", canEdit:false, budgetTokens:3200, usedTokens:540 },
    { name:"Coder", role:"Codex Plus 通道：实际文件编辑、命令执行和本地验证。", status:"active", provider:"Codex Plus", model:"Codex", owner:"执行层", canEdit:true, budgetTokens:5400, usedTokens:1800 },
    { name:"CodexPromptGenerator", role:"为 Codex Plus 起草简洁的实现移交说明。", status:"skipped", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"管理层", canEdit:false, budgetTokens:1800, usedTokens:0 },
    { name:"TesterAuditor", role:"在接受之前验证行为并审计差异。", status:"waiting", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"审查层", canEdit:false, budgetTokens:3600, usedTokens:260 },
    { name:"Archivist", role:"验证后更新项目记忆和连续性记录。", status:"waiting", provider:"DeepSeek", model:"deepseek-v4-pro", owner:"记忆层", canEdit:false, budgetTokens:2200, usedTokens:0 }
  ],
  events: [
    { time:"12:22", level:"info", agent:"Supervisor", text:"Supervisor 创建了模拟任务路线和 Token 预算。" },
    { time:"12:24", level:"info", agent:"RepoScout", text:"RepoScout 检查了 AgentLab 结构并选择了静态 UI 界面。" },
    { time:"12:26", level:"info", agent:"InterfaceMapper", text:"InterfaceMapper 将 UI 文件与运行时和配置层分离。" },
    { time:"12:30", level:"info", agent:"Coder", text:"Coder 添加了第一个本地状态面板骨架。" },
    { time:"12:35", level:"warn", agent:"Supervisor", text:"Codex 配额警告：剩余 8500 tokens，接近阈值。" },
    { time:"12:38", level:"decision", agent:"Supervisor", text:"用户决策：是否批准 Coder 的完整文件编辑权限？" },
  ],
  costLedger: [
    { time:"12:22", agent:"Supervisor", provider:"DeepSeek", model:"deepseek-v4-pro", inputTokens:520, outputTokens:180, totalTokens:700, status:"ok" },
    { time:"12:24", agent:"RepoScout", provider:"DeepSeek", model:"deepseek-v4-pro", inputTokens:680, outputTokens:100, totalTokens:780, status:"ok" },
    { time:"12:26", agent:"InterfaceMapper", provider:"DeepSeek", model:"deepseek-v4-pro", inputTokens:400, outputTokens:140, totalTokens:540, status:"ok" },
    { time:"12:30", agent:"Coder", provider:"Codex Plus", model:"Codex", inputTokens:1200, outputTokens:600, totalTokens:1800, status:"manual_logged" }
  ],
  decisions: [
    { id:"dec_001", title:"Codex 配额决策", question:"Codex 配额可能不足以完成 Coder 阶段。请选择行动：", recommendations:["暂停直到 Codex 刷新","切换到 DeepSeek brain + Qwen Coder API","切换到 DeepSeek 全栈 API 编码"], default:"暂停直到 Codex 刷新", status:"pending" }
  ]
};

/* ───── 备用任务数据集 ───── */
const PROJECT_TASKS = {
  "AgentLab": ["task_0001","task_0002","task_0003","task_0004"],
  "ExampleProject": ["task_0001"]
};

const statusLabels = {
  active: "进行中", complete: "已完成", waiting: "等待中", skipped: "已跳过", blocked: "已阻塞"
};

/* ───── 应用状态 ───── */
const state = {
  project: "AgentLab",
  taskId: "task_0004",
  activeTab: "dashboard",
  filter: "all",
  search: "",
  snapshot: { ...DEFAULT_SNAPSHOT },
  qwenSelectedModel: "",
  coderProvider: "codex-plus",
  theme: "light",
  notifications: [
    { id:1, level:"warn", text:"Coder 配额低于 20%，建议切换至 Qwen 或 DeepSeek", time: Date.now()-300000 },
    { id:2, level:"decision", text:"task_0003 需要用户决策", time: Date.now()-600000 },
    { id:3, level:"info", text:"Supervisor 已完成 task_0004 路线规划", time: Date.now()-900000 }
  ],
  darkMode: false,
  collapsedLogs: new Set(),
};

/* ───── API 后端配置 ───── */
const API_BASE = (window.location.protocol === "file:") ? "http://localhost:8765" : "";

/* ───── 主 AgentLab 对象 ───── */
const AgentLab = {
  /* ======================== API 帮助方法 ======================== */
  async apiGet(path, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const url = `${API_BASE}${path}${qs ? "?" + qs : ""}`;
    try {
      const resp = await fetch(url);
      if (resp.ok) return await resp.json();
      console.warn("API GET failed:", path, resp.status);
    } catch (e) {
      console.warn("API fetch error:", e.message);
    }
    return null;
  },

  async apiPost(path, data = {}) {
    try {
      const resp = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (resp.ok) return await resp.json();
      console.warn("API POST failed:", path, resp.status);
    } catch (e) {
      console.warn("API post error:", e.message);
    }
    return null;
  },

  /* ======================== 数据加载 ======================== */
  async loadSnapshot() {
    // 尝试从后端 API 获取实时数据
    const data = await this.apiGet("/api/status", { project: state.project, task: state.taskId });
    if (data && !data.error) {
      return { ...DEFAULT_SNAPSHOT, ...data };
    }
    // 文件协议后备
    if (window.location.protocol === "file:") {
      try {
        const resp = await fetch("./agent_status.sample.json", { cache: "no-store" });
        if (resp.ok) return { ...DEFAULT_SNAPSHOT, ...(await resp.json()) };
      } catch (_) {}
    }
    return { ...DEFAULT_SNAPSHOT };
  },

  async refresh() {
    this.showToast("正在刷新数据…", "info");
    const btn = document.getElementById("refreshBtn");
    if (btn) { btn.classList.add("spinning"); }
    state.snapshot = await this.loadSnapshot();
    if (!state.snapshot.events) state.snapshot.events = DEFAULT_SNAPSHOT.events;
    if (!state.snapshot.costLedger) state.snapshot.costLedger = DEFAULT_SNAPSHOT.costLedger;
    if (!state.snapshot.decisions) state.snapshot.decisions = DEFAULT_SNAPSHOT.decisions;
    this.renderAll();
    setTimeout(() => { if (btn) btn.classList.remove("spinning"); }, 600);
    this.showToast("数据已刷新", "success");
  },

  /** 自动轮询（每5秒） */
  startPolling() {
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = setInterval(async () => {
      const fresh = await this.loadSnapshot();
      if (fresh) {
        state.snapshot = { ...state.snapshot, ...fresh };
        this.renderAll();
        this.checkDecisions();
      }
    }, 5000);
  },

  /* ======================== 渲染 ======================== */
  renderAll() {
    this.renderTaskDetail();
    this.renderDashboard();
    this.renderAgentGrid();
    this.renderLogs();
    this.renderCost();
    this.renderConfig();
    this.renderNotifications();
    this.updateTaskSelector();
  },

  /* ========== 总览面板 ========== */
  renderDashboard() {
    const snap = state.snapshot;
    const agents = snap.agents || [];
    const totals = agents.reduce((t,a) => { t.used += a.usedTokens||0; t.budget += a.budgetTokens||0; return t; }, {used:0,budget:0});
    const active = agents.filter(a=>a.status==="active").length;
    const complete = agents.filter(a=>a.status==="complete").length;
    const blocked = agents.filter(a=>a.status==="blocked").length;

    this.$("dashAgentCount", agents.length);
    this.$("dashActiveCount", active);
    this.$("dashCompleteCount", complete);
    this.$("dashTokenUsed", this.fmt(totals.used));
    const healthEl = this.$("dashHealth");
    if (healthEl) {
      if (blocked > 0) { healthEl.textContent = "有阻塞"; healthEl.className = "text-amber"; }
      else { healthEl.textContent = "正常"; healthEl.className = "text-green"; }
    }

    // 绘制环形图
    this.drawDonut(totals.used, totals.budget);
    // 绘制状态条形图
    this.drawBarChart(agents);
    // 绘制 Token 趋势
    this.drawTokenTrend(agents);
    // 最近事件
    this.renderDashEvents(snap.events || []);
  },

  renderDashEvents(events) {
    const el = this.$("dashEvents");
    if (!el) return;
    el.innerHTML = events.slice(-5).reverse().map(e => 
      `<li><span class="event-time">${e.time}</span><span class="event-level event-${e.level||'info'}">${e.agent||''}</span><span>${e.text}</span></li>`
    ).join("");
  },

  /* ========== 环形进度图 ========== */
  drawDonut(used, budget) {
    const el = this.$("donutChart");
    if (!el) return;
    const pct = budget > 0 ? Math.min(Math.round((used / budget) * 100), 100) : 0;
    const size = 160, stroke = 16, r = (size-stroke)/2, circ = 2*Math.PI*r;
    const offset = circ - (pct/100)*circ;
    const color = pct > 90 ? "var(--coral)" : pct > 70 ? "var(--amber)" : "var(--green)";
    el.innerHTML = `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--surface-strong)" stroke-width="${stroke}"/>
        <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-dasharray="${circ}" stroke-dashoffset="${offset}" stroke-linecap="round" transform="rotate(-90 ${size/2} ${size/2})" style="transition: stroke-dashoffset 0.6s ease"/>
        <text x="${size/2}" y="${size/2-8}" text-anchor="middle" font-size="28" font-weight="800" fill="var(--ink)">${pct}%</text>
        <text x="${size/2}" y="${size/2+16}" text-anchor="middle" font-size="11" fill="var(--muted)">任务进度</text>
      </svg>`;
  },

  /* ========== 状态条形图 ========== */
  drawBarChart(agents) {
    const el = this.$("barChart");
    if (!el) return;
    const counts = { active:0, complete:0, waiting:0, skipped:0, blocked:0 };
    agents.forEach(a => { if (counts[a.status] !== undefined) counts[a.status]++; });
    const max = Math.max(...Object.values(counts), 1);
    const colors = { active:"var(--blue)", complete:"var(--green)", waiting:"var(--amber)", skipped:"var(--muted)", blocked:"var(--coral)" };
    const labels = { active:"进行中", complete:"已完成", waiting:"等待中", skipped:"已跳过", blocked:"已阻塞" };
    el.innerHTML = Object.entries(counts).map(([k,v]) => `
      <div class="bar-row">
        <span class="bar-label">${labels[k]}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(v/max)*100}%;background:${colors[k]}"></div></div>
        <span class="bar-value">${v}</span>
      </div>`).join("");
  },

  /* ========== Token 趋势图 (Canvas) ========== */
  drawTokenTrend(agents) {
    const canvas = document.getElementById("tokenCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = 200;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0,0,w,h);

    const points = agents.map((a,i) => ({ x: i*(w/(agents.length-1||1)), y: h - (a.usedTokens / (a.budgetTokens||1)) * h * 0.8 - 30 }));
    // 网格线
    ctx.strokeStyle = "var(--line)"; ctx.lineWidth = 1;
    for (let i=0;i<5;i++) { const y = 30 + i*(h-50)/4; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
    // 折线
    ctx.strokeStyle = "var(--blue)"; ctx.lineWidth = 2.5; ctx.lineJoin = "round";
    ctx.beginPath(); points.forEach((p,i) => i===0 ? ctx.moveTo(p.x,p.y) : ctx.lineTo(p.x,p.y)); ctx.stroke();
    // 渐变填充
    const grad = ctx.createLinearGradient(0,30,0,h);
    grad.addColorStop(0,"rgba(47,111,189,0.25)"); grad.addColorStop(1,"rgba(47,111,189,0.02)");
    ctx.fillStyle = grad; ctx.beginPath();
    points.forEach((p,i) => i===0 ? ctx.moveTo(p.x,p.y) : ctx.lineTo(p.x,p.y));
    ctx.lineTo(points[points.length-1].x, h); ctx.lineTo(points[0].x, h); ctx.closePath(); ctx.fill();
    // 数据点
    points.forEach(p => { ctx.fillStyle="var(--blue)"; ctx.beginPath(); ctx.arc(p.x,p.y,4,0,2*Math.PI); ctx.fill(); });
    // 底部标签
    ctx.fillStyle = "var(--muted)"; ctx.font = "10px Inter, sans-serif"; ctx.textAlign = "center";
    agents.forEach((a,i) => ctx.fillText(a.name, i*(w/(agents.length-1||1)), h-4));
  },

  /* ========== Agent 面板 ========== */
  getVisibleAgents() {
    const search = state.search.trim().toLowerCase();
    return (state.snapshot.agents||[]).filter(a => {
      const mf = state.filter === "all" || a.status === state.filter;
      const ms = !search || a.name.toLowerCase().includes(search) || a.role.toLowerCase().includes(search);
      return mf && ms;
    });
  },

  renderAgentGrid() {
    const agents = this.getVisibleAgents();
    const el = this.$("agentGrid");
    if (!el) return;
    if (!agents.length) { el.innerHTML = '<div class="empty-state">没有匹配的 Agent</div>'; return; }
    el.innerHTML = agents.map(a => {
      const pct = a.budgetTokens > 0 ? Math.round((a.usedTokens / a.budgetTokens)*100) : 0;
      const dp = a.name==="Coder" ? (state.coderProvider==="qwen" ? "Qwen" : "Codex Plus") : a.provider;
      const dm = a.name==="Coder" ? (state.coderProvider==="qwen" ? (state.qwenSelectedModel||"qwen-plus") : "Codex") : a.model;
      const controls = a.status === "active"
        ? `<button class="btn btn-sm btn-warning" onclick="AgentLab.agentAction('${a.name}','pause')">⏸ 暂停</button><button class="btn btn-sm btn-danger" onclick="AgentLab.agentAction('${a.name}','stop')">⏹ 停止</button>`
        : a.status === "waiting"
        ? `<button class="btn btn-sm" onclick="AgentLab.agentAction('${a.name}','run')">▶ 启动</button>`
        : a.status === "blocked"
        ? `<button class="btn btn-sm btn-danger" onclick="AgentLab.agentAction('${a.name}','resume')">↻ 重试</button>`
        : `<span class="text-muted">${statusLabels[a.status]||a.status}</span>`;
      return `
      <article class="agent-card" data-status="${a.status}">
        <div class="agent-topline">
          <div><h3 class="agent-name">${a.name}</h3><p class="agent-role">${a.role}</p></div>
          <span class="status-badge" data-status="${a.status}">${statusLabels[a.status]||a.status}</span>
        </div>
        <div class="agent-meta">
          <div class="meta-cell"><span>提供商</span><strong>${dp}</strong></div>
          <div class="meta-cell"><span>归属层</span><strong>${a.owner}</strong></div>
          <div class="meta-cell"><span>模型</span><strong>${dm}</strong></div>
          <div class="meta-cell"><span>编辑权限</span><strong>${a.canEdit?'允许编辑':'不可编辑'}</strong></div>
        </div>
        <div class="agent-progress">
          <div class="progress-line"><span>Token 用量</span><span>${this.fmt(a.usedTokens)} / ${this.fmt(a.budgetTokens)}</span></div>
          <div class="meter" aria-hidden="true"><span style="width:${Math.min(pct,100)}%"></span></div>
        </div>
        <div class="agent-controls">${controls}</div>
      </article>`;
    }).join("");
  },

  agentAction(agentName, action) {
    const titles = { run:"启动 Agent", pause:"暂停 Agent", stop:"停止 Agent", resume:"重试 Agent" };
    const descs = { run:`确定要启动 ${agentName} 吗？`, pause:`确定要暂停 ${agentName} 吗？这会中断当前执行。`, stop:`确定要停止 ${agentName} 吗？未保存的进度将丢失。`, resume:`确定要重试 ${agentName} 吗？` };
    const modalTitle = this.$("agentActionTitle");
    const modalDesc = this.$("agentActionDesc");
    const modalConfirm = this.$("agentActionConfirm");
    const modal = this.$("agentActionModal");
    if (modalTitle) modalTitle.textContent = titles[action] || action;
    if (modalDesc) modalDesc.textContent = descs[action] || "";
    if (modalConfirm) {
      modalConfirm.onclick = () => {
        this.executeAgentAction(agentName, action);
        if (modal) modal.hidden = true;
      };
    }
    if (modal) modal.hidden = false;
  },

  executeAgentAction(agentName, action) {
    const agent = (state.snapshot.agents||[]).find(a => a.name === agentName);
    if (!agent) return;
    const statusMap = { run:"active", pause:"waiting", stop:"blocked", resume:"active" };
    agent.status = statusMap[action] || agent.status;
    this.renderAgentGrid();
    this.renderDashboard();
    this.addEvent(agentName, action==="run"?"info":"warn", `${agentName} ${action==="run"?"已启动":action==="pause"?"已暂停":action==="stop"?"已停止":"已重试"}`);
    const msgs = { run:"Agent 已启动", pause:"Agent 已暂停", stop:"Agent 已停止", resume:"Agent 已重试" };
    this.showToast(msgs[action] || "操作完成", "success");
  },

  runAllAgents() {
    (state.snapshot.agents||[]).filter(a=>a.status==="waiting").forEach(a => a.status="active");
    this.renderAgentGrid(); this.renderDashboard();
    this.showToast("所有等待中的 Agent 已启动","success");
  },
  pauseAllAgents() {
    (state.snapshot.agents||[]).filter(a=>a.status==="active").forEach(a => a.status="waiting");
    this.renderAgentGrid(); this.renderDashboard();
    this.showToast("所有进行中的 Agent 已暂停","info");
  },
  stopAllAgents() {
    (state.snapshot.agents||[]).filter(a=>a.status==="active"||a.status==="waiting").forEach(a => a.status="blocked");
    this.renderAgentGrid(); this.renderDashboard();
    this.showToast("所有 Agent 已停止","warn");
  },

  /* ========== 日志面板 ========== */
  renderLogs() {
    const el = this.$("logList");
    if (!el) return;
    const search = (this.$("logSearch")?.value || "").toLowerCase();
    const lvl = this.$("logLevelFilter")?.value || "all";
    const agt = this.$("logAgentFilter")?.value || "all";
    const from = this.$("logDateFrom")?.value;
    const to = this.$("logDateTo")?.value;

    // 更新 Agent 筛选选项
    const agentFilter = this.$("logAgentFilter");
    if (agentFilter) {
      const agents = [...new Set((state.snapshot.events||[]).map(e=>e.agent).filter(Boolean))];
      agentFilter.innerHTML = '<option value="all">所有 Agent</option>' + agents.map(a=>`<option value="${a}">${a}</option>`).join("");
    }

    let events = (state.snapshot.events||[]).slice().reverse();
    if (search) events = events.filter(e => (e.text||"").toLowerCase().includes(search) || (e.agent||"").toLowerCase().includes(search));
    if (lvl !== "all") events = events.filter(e => (e.level||"info") === lvl);
    if (agt !== "all") events = events.filter(e => (e.agent||"") === agt);
    if (from) events = events.filter(e => new Date(e.time) >= new Date(from));
    if (to) events = events.filter(e => new Date(e.time) <= new Date(to));

    if (!events.length) { el.innerHTML = '<div class="empty-state">没有匹配的日志条目</div>'; return; }

    el.innerHTML = events.map((e,i) => {
      const isCollapsed = state.collapsedLogs.has(i);
      const lvlClass = `log-level log-${e.level||'info'}`;
      return `
      <div class="log-entry" data-index="${i}">
        <div class="log-entry-header" onclick="AgentLab.toggleLog(${i})">
          <span class="log-expand">${isCollapsed?'▶':'▼'}</span>
          <span class="log-time">${e.time}</span>
          <span class="${lvlClass}">${e.level||'info'}</span>
          <span class="log-agent-tag">${e.agent||''}</span>
          <span class="log-text">${this.esc(e.text||'')}</span>
        </div>
        <div class="log-entry-body" ${isCollapsed?'hidden':''}>
          <pre>${this.esc(JSON.stringify(e, null, 2))}</pre>
        </div>
      </div>`;
    }).join("");
  },

  toggleLog(index) {
    if (state.collapsedLogs.has(index)) state.collapsedLogs.delete(index);
    else state.collapsedLogs.add(index);
    this.renderLogs();
  },
  expandAllLogs() { state.collapsedLogs.clear(); this.renderLogs(); this.showToast("已展开全部日志","info"); },
  collapseAllLogs() {
    const el = this.$("logList");
    if (el) {
      const items = el.querySelectorAll(".log-entry");
      items.forEach((_,i) => state.collapsedLogs.add(i));
    }
    this.renderLogs();
  },
  exportLogs() {
    const json = JSON.stringify(state.snapshot.events||[], null, 2);
    const blob = new Blob([json], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `agentlab-logs-${state.taskId}.json`; a.click();
    URL.revokeObjectURL(url);
    this.showToast("日志已导出","success");
  },

  /* ========== 成本分析面板 ========== */
  renderCost() {
    const snap = state.snapshot;
    const agents = snap.agents || [];
    const totals = agents.reduce((t,a)=>{ t.used+=a.usedTokens||0; t.budget+=a.budgetTokens||0; return t;},{used:0,budget:0});
    const remaining = totals.budget - totals.used;
    // DeepSeek v4-pro approx: $0.14/1M input, $0.28/1M output. Rough estimate
    const estCost = (totals.used * 0.0000002).toFixed(3);

    this.$("costTotalBudget", this.fmt(totals.budget));
    this.$("costTotalUsed", this.fmt(totals.used));
    this.$("costRemaining", this.fmt(remaining));
    this.$("costEstimate", `$${estCost}`);

    // 水平条形图
    const maxUsed = Math.max(...agents.map(a=>a.usedTokens||0), 1);
    const barEl = this.$("costBarChart");
    if (barEl) {
      barEl.innerHTML = agents.map(a => `
        <div class="bar-row">
          <span class="bar-label">${a.name}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${(a.usedTokens/maxUsed)*100}%;background:var(--blue)"></div></div>
          <span class="bar-value">${this.fmt(a.usedTokens||0)}</span>
        </div>`).join("");
    }

    // 成本摘要
    const breakdown = this.$("costBreakdown");
    if (breakdown) {
      const byProvider = {};
      agents.forEach(a => { const p = a.provider||"Unknown"; byProvider[p] = (byProvider[p]||0) + (a.usedTokens||0); });
      breakdown.innerHTML = Object.entries(byProvider).map(([p,t]) => `
        <div class="cost-row"><span>${p}</span><strong>${this.fmt(t)} tokens</strong><span class="text-muted">~$${(t*0.0000002).toFixed(3)}</span></div>`
      ).join("");
    }

    // 成本日志表
    const table = this.$("costTable")?.querySelector("tbody");
    if (table) {
      const ledger = snap.costLedger || [];
      table.innerHTML = ledger.map(l => `
        <tr><td>${l.time}</td><td>${l.agent}</td><td>${l.provider}</td><td>${l.model}</td><td>${this.fmt(l.inputTokens||0)}</td><td>${this.fmt(l.outputTokens||0)}</td><td>${this.fmt(l.totalTokens||0)}</td><td>${l.status}</td></tr>`
      ).join("") || '<tr><td colspan="8" class="text-muted">暂无成本数据</td></tr>';
    }
  },

  /* ========== 配置面板 ========== */
  async renderConfig() {
    // Try fetching real config from backend
    try {
      const configData = await this.apiGet("/api/config");
      if (configData && !configData.error) {
        this._configData = configData;
      }
    } catch (_) {
      this._configData = null;
    }

    const policyYaml = this._configData?.execution_policy
      ? JSON.stringify(this._configData.execution_policy, null, 2)
      : "brain_policy:\n  required_provider: deepseek\n  deepseek_required_for_all_agentlab_tasks: true\n  codex_may_simulate_brain: false\n\ncoder_policy:\n  primary_executor: codex_plus_manual\n  api_fallback_executor: qwen\n  deepseek_coding_allowed: true\n  no_automatic_deepseek_coding: false";

    this.$("configPolicy", `<pre id="configPolicyPre">${this.esc(policyYaml)}</pre>`);

    const providers = this._configData?.model_providers?.providers || {};
    const provRows = Object.entries(providers).map(([name, cfg]) => {
      const keyStatus = cfg.api_key ? "text-green" : "text-muted";
      const keyLabel = cfg.api_key ? "已配置" : "未配置";
      return `<tr><td>${name}</td><td>${cfg.type||""}</td><td>${cfg.default_model||""}</td><td class="${keyStatus}">${keyLabel}</td></tr>`;
    }).join("") || '<tr><td colspan="4" class="text-muted">未加载</td></tr>';
    this.$("configProviders", `<table><tr><th>Provider</th><th>Type</th><th>Model</th><th>API Key</th></tr>${provRows}</table>`);

    const profiles = this._configData?.model_profiles?.profiles || {};
    const profRows = Object.entries(profiles).map(([name, cfg]) =>
      `<tr><td>${name}</td><td>${cfg.provider||""}</td><td>${cfg.model||""}</td></tr>`
    ).join("") || '<tr><td colspan="3" class="text-muted">未加载</td></tr>';
    this.$("configProfiles", `<table><tr><th>Profile</th><th>Provider</th><th>Model</th></tr>${profRows}</table>`);

    this.$("configEnv", `<div><pre id="configEnvPre">AGENTLAB_ROOT=/Users/saintpeter/AgentLab\nDEFAULT_PROJECT=AgentLab\nLLM_PROVIDER=deepseek\nDEEPSEEK_MODEL=deepseek-v4-pro\nDEEPSEEK_API_KEY=sk-65f6... (已脱敏)\nQWEN_API_KEY=sk-92d4... (已脱敏)</pre></div>`);
  },

  editConfig() {
    // Make config panes editable
    const policyPre = document.getElementById("configPolicyPre");
    const envPre = document.getElementById("configEnvPre");
    if (policyPre) policyPre.contentEditable = "true";
    if (envPre) envPre.contentEditable = "true";
    // Toggle buttons
    const saveBtn = document.getElementById("configSaveBtn");
    const cancelBtn = document.getElementById("configCancelBtn");
    if (saveBtn) saveBtn.hidden = false;
    if (cancelBtn) cancelBtn.hidden = false;
    const editBtn = document.querySelector(".config-toolbar .btn:first-child");
    if (editBtn) editBtn.hidden = true;
    this.showToast("配置面板已进入编辑模式 — 修改后请保存", "info");
  },

  cancelEditConfig() {
    const policyPre = document.getElementById("configPolicyPre");
    const envPre = document.getElementById("configEnvPre");
    if (policyPre) policyPre.contentEditable = "false";
    if (envPre) envPre.contentEditable = "false";
    const saveBtn = document.getElementById("configSaveBtn");
    const cancelBtn = document.getElementById("configCancelBtn");
    if (saveBtn) saveBtn.hidden = true;
    if (cancelBtn) cancelBtn.hidden = true;
    const editBtn = document.querySelector(".config-toolbar .btn:first-child");
    if (editBtn) editBtn.hidden = false;
    this.renderConfig();
    this.showToast("已取消编辑", "info");
  },

  async saveConfig() {
    const policyPre = document.getElementById("configPolicyPre");
    const envPre = document.getElementById("configEnvPre");
    const statusEl = document.getElementById("configStatus");

    // Build config payload from editable pre elements
    const policyText = policyPre?.textContent || "";
    const envText = envPre?.textContent || "";

    const result = await this.apiPost("/api/config/save", {
      project: state.project,
      policyYaml: policyText,
      envText: envText,
    });

    if (result && result.success) {
      if (statusEl) { statusEl.textContent = "✓ 配置已保存"; statusEl.className = "config-status text-green"; }
      this.showToast("配置已保存", "success");
      // Exit edit mode
      this.cancelEditConfig();
    } else {
      const msg = result?.error || "保存失败 — 后端未连接，配置仅在前端可用";
      if (statusEl) { statusEl.textContent = "✗ " + msg; statusEl.className = "config-status text-coral"; }
      this.showToast(msg, "warn");
      // Still exit edit mode on frontend
      const policyPre2 = document.getElementById("configPolicyPre");
      const envPre2 = document.getElementById("configEnvPre");
      if (policyPre2) policyPre2.contentEditable = "false";
      if (envPre2) envPre2.contentEditable = "false";
      document.getElementById("configSaveBtn").hidden = true;
      document.getElementById("configCancelBtn").hidden = true;
      const editBtn = document.querySelector(".config-toolbar .btn:first-child");
      if (editBtn) editBtn.hidden = false;
    }
    setTimeout(() => { if (statusEl) statusEl.textContent = ""; }, 5000);
  },

  /* ========== 任务详情面板 ========== */
  renderTaskDetail() {
    const snap = state.snapshot;
    const idEl = this.$("taskDetailId");
    const statusEl = this.$("taskDetailStatus");
    const titleEl = this.$("taskDetailTitle");
    const descEl = this.$("taskDetailDescription");
    const prioEl = this.$("taskDetailPriority");
    const catEl = this.$("taskDetailCategory");
    const depEl = this.$("taskDetailSubtaskCount");
    const breadcrumbProj = this.$("breadcrumbProject");
    const breadcrumbTask = this.$("breadcrumbTask");

    // Breadcrumb: project → task
    const ledger = state._ledgerEntry || {};
    if (breadcrumbProj) breadcrumbProj.textContent = snap.project || state.project || "AgentLab";
    if (breadcrumbTask) breadcrumbTask.textContent = ledger.title || snap.stage || snap.taskId || "未知任务";

    // Task ID and status
    if (idEl) idEl.textContent = snap.taskId || state.taskId || "task_????";
    if (statusEl) {
      const ts = snap.taskStatus || ledger.status || "new";
      const statusText = statusLabels[ts] || ts;
      let icon = "❓";
      if (ts === "running" || ts === "active") icon = "🔄";
      else if (ts === "complete" || ts === "completed") icon = "✅";
      else if (ts === "blocked") icon = "🚫";
      else if (ts === "new") icon = "🆕";
      statusEl.textContent = `${icon} ${statusText}`;
      statusEl.setAttribute("data-status", ts);
    }

    // Title
    if (titleEl) titleEl.textContent = ledger.title || snap.stage || snap.taskStatus || "AgentLab 任务";

    // Description
    if (descEl) {
      const desc = ledger.description || snap.userRequest || snap.stage || "暂无描述";
      descEl.textContent = desc;
      descEl.title = desc;
    }

    // Meta
    if (prioEl) prioEl.textContent = ledger.priority || snap.priority || "--";
    if (catEl) catEl.textContent = ledger.category || snap.category || "--";

    // Subtask count
    const subtasks = ledger.subtasks || [];
    if (depEl) depEl.textContent = subtasks.length || "--";

    // Render subtask list
    this._renderSubtasks(subtasks);
  },

  _renderSubtasks(subtasks) {
    const listEl = this.$("subtaskList");
    const sectionEl = this.$("subtaskSection");
    if (!sectionEl) return;
    if (!subtasks || subtasks.length === 0) {
      sectionEl.style.display = "none";
      return;
    }
    sectionEl.style.display = "block";
    if (!listEl) return;
    const labels = { complete: "已完成", active: "进行中", pending: "待处理" };
    listEl.innerHTML = subtasks.map(s => `
      <div class="subtask-item" data-status="${s.status}">
        <span class="subtask-id">${s.id}</span>
        <span>${this.esc(s.description || "")}</span>
        <span class="subtask-status" data-status="${s.status}">${labels[s.status] || s.status}</span>
      </div>
    `).join("");

    // Update chat context target
    const target = this.$("nlContextTarget");
    if (target) {
      const ledger = state._ledgerEntry || {};
      const proj = state.snapshot.project || state.project || "AgentLab";
      const task = ledger.title || state.snapshot.taskId || state.taskId;
      target.textContent = `${proj} › ${task}`;
    }
  },

  /* ========== 通知面板 ========== */
  renderNotifications() {
    const list = this.$("notifList");
    const badge = this.$("notifBadge");
    if (badge) { badge.textContent = state.notifications.length; badge.hidden = state.notifications.length === 0; }
    if (!list) return;
    list.innerHTML = state.notifications.map(n => `
      <div class="notif-item notif-${n.level}">
        <span>${n.text}</span>
        <span class="notif-time">${this.timeAgo(n.time)}</span>
      </div>`).join("") || '<p class="text-muted">暂无通知</p>';
  },
  toggleNotifications() {
    const panel = this.$("notifPanel");
    if (panel) panel.hidden = !panel.hidden;
  },
  clearNotifications() { state.notifications = []; this.renderNotifications(); this.showToast("通知已清除","info"); },
  addNotification(level, text) { state.notifications.unshift({id:Date.now(),level,text,time:Date.now()}); this.renderNotifications(); },

  /* ========== 用户决策 ========== */
  checkDecisions() {
    const decisions = state.snapshot.decisions || [];
    const pending = decisions.filter(d => d.status === "pending");
    if (pending.length > 0) this.showDecision(pending[0]);
  },
  showDecision(decision) {
    const modal = this.$("decisionModal");
    const title = this.$("decisionTitle");
    const question = this.$("decisionQuestion");
    const recs = this.$("decisionRecs");
    if (!modal) return;
    if (title) title.textContent = decision.title || "用户决策";
    if (question) question.textContent = decision.question || "";

    // 存储当前决策数据
    state._activeDecision = decision;

    if (recs) {
      recs.innerHTML = (decision.recommendations||[]).map((r,i) => {
        const isDefault = decision.default === r || i === 0;
        return `<div class="rec-item ${isDefault?'rec-selected':''}" data-rec-idx="${i}" onclick="AgentLab.selectRecOption(${i})">${r}</div>`;
      }).join("");
    }
    modal.hidden = false;
    this.addNotification("decision", `${decision.title}: ${decision.question}`);
  },
  selectRecOption(idx) {
    // 选中推荐选项
    document.querySelectorAll("#decisionRecs .rec-item").forEach(el => el.classList.remove("rec-selected"));
    const target = document.querySelector(`#decisionRecs .rec-item[data-rec-idx="${idx}"]`);
    if (target) target.classList.add("rec-selected");
    state._selectedRecIdx = idx;
  },
  async resolveDecision(action) {
    const modal = this.$("decisionModal");
    if (modal) modal.hidden = true;
    const decisions = state.snapshot.decisions || [];
    const pending = decisions.find(d => d.status === "pending");
    if (pending) pending.status = action === "yes" ? "approved" : action === "no" ? "rejected" : "deferred";

    // 获取选中的推荐选项文本
    const recs = state._activeDecision?.recommendations || [];
    const chosen = recs[state._selectedRecIdx || 0] || "";
    state._selectedRecIdx = undefined;
    state._activeDecision = undefined;

    const actionLabel = action === "yes" ? "批准" : action === "no" ? "拒绝" : "推迟";
    this.showToast(`已${actionLabel}，正在通知 AgentLab…`, "info");

    // 通过 API 发送决策到后端（附带选择的推荐选项）
    const result = await this.apiPost("/api/decision", {
      project: state.project,
      taskId: state.taskId,
      action: action,
      chosenRecommendation: chosen,
    });

    this.addEvent("User", "decision", `用户${actionLabel}了决策: ${pending?.title||''} → ${chosen}`);

    if (result && result.success) {
      this.showToast(`已${actionLabel}，AgentLab 已收到反馈`, "success");
      if (result.actionResult) {
        this.addEvent("System", "info", `后端响应: ${result.actionResult}`);
      }
      setTimeout(() => this.refresh(), 1000);
    } else {
      this.showToast(`⚠ 后端未连接 — 决策仅在前端生效，未通知 AgentLab 引擎。请运行: cd web_ui && python3 server.py`, "error");
      this.addNotification("error", "后端服务未运行，决策未生效。启动方法: python3 web_ui/server.py");
    }
    setTimeout(() => this.checkDecisions(), 1000);
  },

  /* ========== 任务管理 ========== */
  async fetchTasks() {
    const data = await this.apiGet("/api/tasks", { project: state.project });
    if (data && data.tasks && data.tasks.length > 0) {
      state._taskData = data.tasks;
      return data.tasks;
    }
    // Fallback: build from PROJECT_TASKS when backend is unavailable
    const ids = PROJECT_TASKS[state.project] || [];
    const fallback = ids.map(id => ({ task_id: id, title: id, description: "", status: "", priority: "", category: "" }));
    state._taskData = fallback;
    return fallback;
  },
  updateTaskSelector() {
    const sel = this.$("taskSelector");
    if (!sel) return;
    const tasks = state._taskData || PROJECT_TASKS[state.project]?.map(id => ({ task_id: id, title: id, description: "" })) || [];
    sel.innerHTML = tasks.map(t => {
      const label = t.title || t.task_id;
      return `<option value="${t.task_id}" ${t.task_id===state.taskId?'selected':''}>${label}</option>`;
    }).join("");

    // Cache ledger entry for the current task to drive renderTaskDetail
    const current = tasks.find(t => t.task_id === state.taskId);
    if (current) {
      state._ledgerEntry = current;
    }
  },
  async switchProject(project) {
    state.project = project;
    state._taskData = await this.fetchTasks();
    state.taskId = (state._taskData[0]?.task_id || "task_0001");
    this.updateTaskSelector();
    this.refresh();
  },
  async switchTask(taskId) {
    state.taskId = taskId;
    this.updateTaskSelector();
    this.refresh();
  },
  openNewTask() {
    const modal = this.$("newTaskModal");
    if (modal) modal.hidden = false;
  },

  /* ========== 自然语言任务下达 ========== */
  async submitNaturalTask() {
    const input = this.$("nlTaskInput");
    const status = this.$("nlStatus");
    const btn = this.$("nlSubmitBtn");
    const text = (input?.value || "").trim();

    if (!text) { this.showToast("请输入任务描述", "warn"); return; }
    if (text.length < 5) { this.showToast("任务描述至少需要 5 个字符", "warn"); return; }

    // 禁用按钮，显示进度
    if (btn) { btn.disabled = true; btn.textContent = "执行中…"; }
    if (status) { status.innerHTML = '<span class="nl-progress">⏳ 正在创建任务并调用 DeepSeek…</span>'; status.style.display = "block"; }

    // 清空输入
    if (input) input.value = "";

    this.showToast("正在下达任务到 AgentLab…", "info");

    const result = await this.apiPost("/api/task/nl", {
      project: state.project,
      text: text,
      autoExecute: true,
    });

    if (btn) { btn.disabled = false; btn.textContent = "下达任务"; }

    if (result && result.success) {
      if (status) { status.innerHTML = `<span class="nl-success">✅ 任务 ${result.taskId} 已创建${result.stage === 'awaiting_decision' ? '，需要用户决策' : ''}</span>`; }
      this.showToast(`任务 ${result.taskId} 已下达`, "success");

      // 添加到任务列表
      if (!PROJECT_TASKS[state.project]) PROJECT_TASKS[state.project] = [];
      if (!PROJECT_TASKS[state.project].includes(result.taskId)) {
        PROJECT_TASKS[state.project].push(result.taskId);
      }

      // 切换到新任务
      state.taskId = result.taskId;
      this.updateTaskSelector();

      // 如果等待决策，显示决策弹窗
      if (result.stage === "awaiting_decision") {
        this.addNotification("decision", `任务 ${result.taskId} 需要用户决策`);
      }

      // 刷新数据
      await this.refresh();

      // 清除状态消息
      setTimeout(() => { if (status) { status.style.display = "none"; } }, 8000);
    } else {
      const errMsg = result?.error || "任务下达失败，请检查后端服务";
      if (status) { status.innerHTML = `<span class="nl-error">❌ ${this.esc(errMsg)}</span>`; }
      this.showToast(errMsg, "error");
    }
  },
  createTask(event) {
    event.preventDefault();
    const project = this.$("newTaskProject")?.value || "AgentLab";
    const id = this.$("newTaskId")?.value || `task_${String((PROJECT_TASKS[project]||[]).length+1).padStart(4,'0')}`;
    const request = this.$("newTaskRequest")?.value || "";
    const backend = this.$("newTaskBackend")?.value || "codex";
    if (!PROJECT_TASKS[project]) PROJECT_TASKS[project] = [];
    if (!PROJECT_TASKS[project].includes(id)) PROJECT_TASKS[project].push(id);
    state.snapshot.taskId = id; state.snapshot.project = project; state.snapshot.taskStatus = "新建";
    state.taskId = id; state.project = project;
    this.addEvent("System", "info", `新任务 ${id} 已创建 (项目: ${project}, 后端: ${backend})${request ? '，请求已记录' : ''}`);
    this.updateTaskSelector();
    this.renderDashboard(); this.renderAgentGrid();
    this.$("newTaskModal").hidden = true;
    this.showToast(`任务 ${id} 已创建`, "success");
  },

  /* ========== 模型切换 ========== */
  switchBrainModel(mode) {
    state.brainMode = mode;
    const labels = { "default": "默认 (Supervisor: v4-pro + 其余: v4-flash)", "deepseek-v4-pro": "全 DeepSeek V4 Pro", "qwen": "全 Qwen" };
    state.snapshot.brainProvider = mode === "qwen" ? "Qwen" : "DeepSeek";
    this.addEvent("User", "info", `大脑层模式切换至: ${labels[mode] || mode}`);
    this.showToast(`🧠 大脑层: ${labels[mode] || mode}`, "success");
    if (state.activeTab === "agents") this.renderAgentGrid();
  },
  switchExecModel(modelId) {
    state.execModel = modelId;
    if (modelId === "codex-plus") {
      state.coderProvider = "codex-plus";
    } else if (modelId.startsWith("qwen")) {
      state.coderProvider = "qwen";
      state.qwenSelectedModel = modelId;
    } else {
      state.coderProvider = "deepseek";
    }
    this.addEvent("User", "info", `执行层模型切换至: ${modelId}`);
    this.showToast(`⚡ 执行层已切换至 ${modelId}`, "success");
    // Show/hide API key input based on selection
    this._updateExecApiKeyUI(modelId);
    if (state.activeTab === "agents") this.renderAgentGrid();
  },
  _updateExecApiKeyUI(modelId) {
    const group = document.getElementById("execApiKeyGroup");
    const note = document.getElementById("execApiKeyNote");
    const label = document.getElementById("execApiKeyLabel");
    if (!group) return;
    if (modelId === "codex-plus") {
      group.style.display = "none";
      if (note) note.style.display = "block";
    } else {
      group.style.display = "grid";
      if (note) note.style.display = "none";
      if (label) {
        if (modelId.startsWith("qwen")) label.textContent = "Qwen API Key";
        else label.textContent = "DeepSeek API Key";
      }
    }
  },

  /* ========== 聊天模式 ========== */
  chatMode: "subtask", // subtask | task | project
  setChatMode(mode) {
    this.chatMode = mode;
    document.querySelectorAll(".nl-mode-btn").forEach(b => b.classList.toggle("is-active", b.dataset.mode === mode));
    const typeEl = document.getElementById("nlContextType");
    const input = document.getElementById("nlTaskInput");
    const labels = { subtask: "追加子任务", task: "创建新任务", project: "创建新项目" };
    const placeholders = {
      subtask: `为 ${state._ledgerEntry?.title || "当前任务"} 追加子任务…`,
      task: "描述新任务…",
      project: "描述新项目…",
    };
    if (typeEl) typeEl.textContent = labels[mode] || mode;
    if (input) input.placeholder = placeholders[mode] || "描述你的需求…";
    this.showToast(`聊天模式: ${labels[mode]}`, "info");
  },

  /* ========== 设置面板 ========== */
  toggleSettings() {
    const panel = document.getElementById("settingsPanel");
    const backdrop = document.getElementById("settingsBackdrop");
    if (!panel) return;
    const isOpen = !panel.hidden;
    if (isOpen) {
      panel.hidden = true;
      if (backdrop) backdrop.hidden = true;
    } else {
      panel.hidden = false;
      if (backdrop) backdrop.hidden = false;
      // Sync current exec model UI
      this._updateExecApiKeyUI(state.execModel || state.coderProvider || "codex-plus");
    }
  },
  setBrainApiKey(value) {
    if (value) {
      state._brainApiKey = value;
      this.showToast("🧠 大脑层 API Key 已设置（本地存储，不会上传）", "success");
    }
  },
  setExecApiKey(value) {
    if (value) {
      state._execApiKey = value;
      this.showToast("⚡ 执行层 API Key 已设置（本地存储，不会上传）", "success");
    }
  },

  /* ========== 主题切换 ========== */
  toggleTheme() {
    state.darkMode = !state.darkMode;
    document.documentElement.setAttribute("data-theme", state.darkMode ? "dark" : "light");
    const btn = this.$("themeBtn");
    if (btn) {
      const light = btn.querySelector(".theme-icon-light");
      const dark = btn.querySelector(".theme-icon-dark");
      if (light) light.hidden = state.darkMode;
      if (dark) dark.hidden = !state.darkMode;
    }
    this.showToast(state.darkMode ? "已切换至深色模式" : "已切换至浅色模式", "info");
    // 重新绘制 canvas
    if (state.activeTab === "dashboard") this.drawTokenTrend(state.snapshot.agents||[]);
  },

  /* ========== Tab 切换 ========== */
  switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("is-active", b.dataset.tab === tabName));
    document.querySelectorAll(".tab-content").forEach(s => s.hidden = s.id !== `tab-${tabName}`);
    if (tabName === "dashboard") this.renderDashboard();
    if (tabName === "agents") this.renderAgentGrid();
    if (tabName === "logs") this.renderLogs();
    if (tabName === "cost") this.renderCost();
    if (tabName === "config") this.renderConfig();
  },

  /* ========== 命令面板 ========== */
  openCommandPalette() {
    const palette = this.$("commandPalette");
    if (palette) { palette.hidden = false; this.$("commandInput")?.focus(); }
  },
  closeCommandPalette() { const p = this.$("commandPalette"); if (p) { p.hidden = true; } },

  /* ========== 快捷键面板 ========== */
  showShortcuts() { const o = this.$("shortcutsOverlay"); if (o) o.hidden = false; },

  /* ========== 事件日志 ========== */
  addEvent(agent, level, text) {
    const now = new Date();
    const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
    (state.snapshot.events||[]).push({ time, level, agent, text });
    if (state.activeTab === "dashboard") this.renderDashEvents(state.snapshot.events);
    if (state.activeTab === "logs") this.renderLogs();
  },

  /* ========== Toast ========== */
  showToast(message, level = "info") {
    const container = this.$("toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${level}`;
    toast.innerHTML = `<span>${level==="success"?"✓":level==="error"?"✕":level==="warn"?"⚠":"ℹ"} ${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 3000);
  },

  /* ========== 工具方法 ========== */
  $(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined) el.textContent = value;
    return el;
  },
  fmt(num) { return new Intl.NumberFormat("zh-CN").format(num); },
  esc(text) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
  },
  timeAgo(ts) {
    const diff = Date.now() - ts;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "刚刚";
    if (mins < 60) return `${mins}分钟前`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}小时前`;
    return `${Math.floor(hrs/24)}天前`;
  },
};

/* ======================== 初始化 ======================== */
async function init() {
  // 加载数据
  state.snapshot = await AgentLab.loadSnapshot();
  // 合并缺失数据
  if (!state.snapshot.events) state.snapshot.events = DEFAULT_SNAPSHOT.events;
  if (!state.snapshot.costLedger) state.snapshot.costLedger = DEFAULT_SNAPSHOT.costLedger;
  if (!state.snapshot.decisions) state.snapshot.decisions = DEFAULT_SNAPSHOT.decisions;
  state.coderProvider = state.snapshot.coderProvider || "codex-plus";

  // 加载任务列表并渲染
  state._taskData = await AgentLab.fetchTasks();
  AgentLab.renderAll();

  // 事件绑定
  bindEvents();

  // 检查是否有待处理决策
  AgentLab.checkDecisions();

  // 初始通知
  AgentLab.addNotification("info", "AgentLab 已就绪，当前任务: " + state.taskId);
}

function bindEvents() {
  // Tab 切换
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => AgentLab.switchTab(btn.dataset.tab));
  });

  // Agent 筛选
  document.querySelectorAll("#agentFilter .segment").forEach(btn => {
    btn.addEventListener("click", () => {
      state.filter = btn.dataset.filter;
      document.querySelectorAll("#agentFilter .segment").forEach(s => s.classList.toggle("is-selected", s===btn));
      AgentLab.renderAgentGrid();
    });
  });

  // Agent 搜索
  document.getElementById("agentSearch")?.addEventListener("input", e => { state.search = e.target.value; AgentLab.renderAgentGrid(); });

  // 日志筛选
  document.getElementById("logSearch")?.addEventListener("input", () => AgentLab.renderLogs());
  document.getElementById("logLevelFilter")?.addEventListener("change", () => AgentLab.renderLogs());
  document.getElementById("logAgentFilter")?.addEventListener("change", () => AgentLab.renderLogs());
  document.getElementById("logDateFrom")?.addEventListener("change", () => AgentLab.renderLogs());
  document.getElementById("logDateTo")?.addEventListener("change", () => AgentLab.renderLogs());

  // 项目切换
  document.getElementById("projectSelector")?.addEventListener("change", e => AgentLab.switchProject(e.target.value));

  // 任务切换
  document.getElementById("taskSelector")?.addEventListener("change", e => AgentLab.switchTask(e.target.value));

  // 命令面板输入
  document.getElementById("commandInput")?.addEventListener("input", e => {
    const q = e.target.value.toLowerCase();
    const cmds = [
      "切换项目: AgentLab", "切换项目: ExampleProject",
      "切换任务: task_0001", "切换任务: task_0002", "切换任务: task_0003", "切换任务: task_0004",
      "Tab: 总览", "Tab: Agent 面板", "Tab: 任务日志", "Tab: 成本分析", "Tab: 配置",
      "刷新数据", "新建任务", "切换主题", "导出日志", "显示快捷键"
    ].filter(c => c.toLowerCase().includes(q));
    const results = document.getElementById("cmdResults");
    if (results) results.innerHTML = cmds.map(c => `<div class="cmd-item" onclick="executeCommand('${c}')">${c}</div>`).join("");
  });

  // 键盘快捷键
  document.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key === "k") { e.preventDefault(); AgentLab.openCommandPalette(); }
    if (ctrl && e.key === "t") { e.preventDefault(); AgentLab.toggleTheme(); }
    if (ctrl && e.key === "n") { e.preventDefault(); AgentLab.openNewTask(); }
    if (ctrl && e.key === "f") { e.preventDefault(); document.getElementById("logSearch")?.focus(); }
    if (ctrl && e.key >= "1" && e.key <= "6") { e.preventDefault(); const tabs = ["dashboard","agents","logs","cost","config","about"]; AgentLab.switchTab(tabs[parseInt(e.key)-1]); }
    if (e.key === "?") { e.preventDefault(); AgentLab.showShortcuts(); }
    if (e.key === "Escape") {
      document.getElementById("commandPalette").hidden = true;
      document.getElementById("shortcutsOverlay").hidden = true;
      document.getElementById("decisionModal").hidden = true;
      document.getElementById("newTaskModal").hidden = true;
      document.getElementById("agentActionModal").hidden = true;
    }
  });

  // 点击遮罩关闭弹窗
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.hidden = true; });
  });
  document.querySelector(".shortcuts-overlay")?.addEventListener("click", e => {
    if (e.target.classList.contains("shortcuts-overlay")) e.target.hidden = true;
  });

  // 通知面板关闭（点击外部）
  document.addEventListener("click", e => {
    const panel = document.getElementById("notifPanel");
    const btn = document.getElementById("notifBtn");
    if (panel && !panel.hidden && btn && !btn.contains(e.target) && !panel.contains(e.target)) {
      panel.hidden = true;
    }
  });

  // 自然语言任务输入 — Enter 键提交
  document.getElementById("nlTaskInput")?.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); AgentLab.submitNaturalTask(); }
  });

  // Canvas resize
  window.addEventListener("resize", () => {
    if (state.activeTab === "dashboard") AgentLab.drawTokenTrend(state.snapshot.agents||[]);
  });
}

// 命令面板执行
window.executeCommand = (cmd) => {
  if (cmd.startsWith("切换项目:")) { AgentLab.switchProject(cmd.split(":")[1].trim()); }
  else if (cmd.startsWith("切换任务:")) { AgentLab.switchTask(cmd.split(":")[1].trim()); }
  else if (cmd.startsWith("Tab:")) { AgentLab.switchTab({"总览":"dashboard","Agent 面板":"agents","任务日志":"logs","成本分析":"cost","配置":"config"}[cmd.split(":")[1].trim()]||"dashboard"); }
  else if (cmd === "刷新数据") AgentLab.refresh();
  else if (cmd === "新建任务") AgentLab.openNewTask();
  else if (cmd === "切换主题") AgentLab.toggleTheme();
  else if (cmd === "导出日志") AgentLab.exportLogs();
  else if (cmd === "显示快捷键") AgentLab.showShortcuts();
  else { AgentLab.showToast("未知命令: " + cmd, "warn"); return; }
  AgentLab.closeCommandPalette();
};

// 启动
init();