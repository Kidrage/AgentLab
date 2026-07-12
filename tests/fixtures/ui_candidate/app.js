const fallbackData = {
  productionPacks: [
    { id: 'code_factory', name: 'Code Factory', status: 'configured', domain: 'coding' },
    { id: 'narrative_longform', name: 'Narrative Longform', status: 'candidate', domain: 'creative_writing' },
    { id: 'media_series_production', name: 'Media Series Production', status: 'blocked', domain: 'media_generation' }
  ],
  lifecycle: [
    { node: 'INIT_TASK', status: 'complete', owner: 'Supervisor' },
    { node: 'SUPERVISOR_PLAN', status: 'complete', owner: 'Supervisor' },
    { node: 'ARTIFACT_PRODUCTION', status: 'candidate', owner: 'ArtifactProducer' },
    { node: 'VALIDATION', status: 'pending', owner: 'TesterAuditor' }
  ],
  evidenceLedger: [
    { gate: 'implementation_report', status: 'pass' },
    { gate: 'ui_interaction_workflow', status: 'candidate' },
    { gate: 'grok_media_live', status: 'blocked' }
  ],
  providerHealth: { deepseek: 'healthy', codex: 'healthy' },
  projectMemory: ['07_DEVELOPMENT_LOG.md', '08_CODEX_DIALOGUE_LOG.md']
};

const dashboardState = {
  data: fallbackData,
  packFilter: 'all',
  selectedNode: 'INIT_TASK',
  visiblePackIds: [],
  openEvidenceGates: [],
  lastActionStatus: 'idle'
};

async function renderDashboard() {
  try {
    const response = await fetch('./status.sample.json');
    dashboardState.data = await response.json();
  } catch (e) {
    console.warn('Fetch failed, using fallback:', e);
    dashboardState.data = fallbackData;
  }
  dashboardState.selectedNode = (dashboardState.data.lifecycle || fallbackData.lifecycle)[0].node;
  renderAll();
}

function renderAll() {
  renderWorkflowActions();
  renderActionLedger();
  renderProductionPacks();
  renderLifecycle();
  renderSelectedDetail();
  renderEvidenceLedger();
  renderProviderHealth(dashboardState.data.providerHealth || fallbackData.providerHealth);
  renderProjectMemory(dashboardState.data.projectMemory || fallbackData.projectMemory);
}

function setPackFilter(filter) {
  dashboardState.packFilter = filter;
  renderWorkflowActions();
  renderProductionPacks();
  return getDashboardInteractionState();
}

function selectLifecycleNode(node) {
  dashboardState.selectedNode = node;
  renderLifecycle();
  renderSelectedDetail();
  return getDashboardInteractionState();
}

function renderWorkflowActions() {
  const section = document.getElementById('workflow-actions');
  const packs = dashboardState.data.productionPacks || fallbackData.productionPacks;
  const counts = packs.reduce((acc, pack) => {
    acc[pack.status] = (acc[pack.status] || 0) + 1;
    return acc;
  }, {});
  section.innerHTML = `
    <h2>Workflow Actions</h2>
    <div class="toolbar" role="toolbar" aria-label="Production pack filters">
      ${['all', 'configured', 'candidate', 'blocked'].map((filter) => `
        <button type="button" data-filter="${filter}" aria-pressed="${dashboardState.packFilter === filter}">
          ${filter} ${filter === 'all' ? packs.length : (counts[filter] || 0)}
        </button>
      `).join('')}
    </div>
    <button type="button" onclick="AgentLabDashboard.submitWorkflowAction('record_validation_review')">
      Record validation review
    </button>
  `;
}

function renderActionLedger() {
  const section = document.getElementById('action-ledger');
  section.innerHTML = `
    <h2>Action Ledger</h2>
    <p data-action-status="${dashboardState.lastActionStatus}">${dashboardState.lastActionStatus}</p>
  `;
}

function renderProductionPacks() {
  const section = document.getElementById('production-packs');
  const packs = dashboardState.data.productionPacks || fallbackData.productionPacks;
  const visible = dashboardState.packFilter === 'all'
    ? packs
    : packs.filter((pack) => pack.status === dashboardState.packFilter);
  dashboardState.visiblePackIds = visible.map((pack) => pack.id);
  section.innerHTML = `
    <h2>Production Packs</h2>
    <ul>
      ${visible.map((pack) => `
        <li data-pack-id="${pack.id}">
          <strong>${pack.name}</strong>
          <code>${pack.id}</code>
          <span>${pack.status}</span>
          <small>${pack.domain || 'unknown'}</small>
        </li>
      `).join('')}
    </ul>
  `;
}

function renderLifecycle() {
  const section = document.getElementById('lifecycle');
  const nodes = dashboardState.data.lifecycle || fallbackData.lifecycle;
  section.innerHTML = `
    <h2>Lifecycle</h2>
    <ol>
      ${nodes.map((item) => `
        <li data-node="${item.node}" aria-current="${dashboardState.selectedNode === item.node}">
          <button type="button" onclick="AgentLabDashboard.selectLifecycleNode('${item.node}')">${item.node}</button>
          <span>${item.status}</span>
          <small>${item.owner || 'unassigned'}</small>
        </li>
      `).join('')}
    </ol>
  `;
}

function renderSelectedDetail() {
  const section = document.getElementById('selected-detail');
  const nodes = dashboardState.data.lifecycle || fallbackData.lifecycle;
  const selected = nodes.find((item) => item.node === dashboardState.selectedNode) || nodes[0];
  section.innerHTML = `
    <h2>Selected Node</h2>
    <dl>
      <dt>Node</dt><dd>${selected.node}</dd>
      <dt>Status</dt><dd>${selected.status}</dd>
      <dt>Owner</dt><dd>${selected.owner || 'unassigned'}</dd>
    </dl>
  `;
}

function renderEvidenceLedger() {
  const section = document.getElementById('evidence-ledger');
  const ledger = dashboardState.data.evidenceLedger || fallbackData.evidenceLedger;
  dashboardState.openEvidenceGates = ledger
    .filter((item) => item.status !== 'pass')
    .map((item) => item.gate);
  section.innerHTML = `
    <h2>Evidence Ledger</h2>
    <ul>${ledger.map((item) => `<li><code>${item.gate}</code>: ${item.status}</li>`).join('')}</ul>
  `;
}

function renderProviderHealth(health) {
  const section = document.getElementById('provider-health');
  section.innerHTML = `<h2>Provider Health</h2><ul>${Object.entries(health).map(([k, v]) => `<li>${k}: ${v}</li>`).join('')}</ul>`;
}

function renderProjectMemory(memory) {
  const section = document.getElementById('project-memory');
  section.innerHTML = `<h2>Project Memory</h2><ul>${memory.map((item) => `<li>${item}</li>`).join('')}</ul>`;
}

function getDashboardInteractionState() {
  return {
    packFilter: dashboardState.packFilter,
    selectedNode: dashboardState.selectedNode,
    visiblePackIds: dashboardState.visiblePackIds,
    openEvidenceGates: dashboardState.openEvidenceGates,
    lastActionStatus: dashboardState.lastActionStatus
  };
}

async function submitWorkflowAction(actionType) {
  const payload = {
    actionType,
    selectedNode: dashboardState.selectedNode,
    packFilter: dashboardState.packFilter,
    visiblePackIds: dashboardState.visiblePackIds,
    openEvidenceGates: dashboardState.openEvidenceGates
  };
  try {
    const response = await fetch('/api/actions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    dashboardState.lastActionStatus = result.status === 'recorded' ? 'recorded' : 'failed';
  } catch (e) {
    console.warn('Action submit failed:', e);
    dashboardState.lastActionStatus = 'failed';
  }
  renderActionLedger();
  return getDashboardInteractionState();
}

globalThis.AgentLabDashboard = {
  setPackFilter,
  selectLifecycleNode,
  submitWorkflowAction,
  getDashboardInteractionState
};

document.addEventListener('DOMContentLoaded', renderDashboard);
