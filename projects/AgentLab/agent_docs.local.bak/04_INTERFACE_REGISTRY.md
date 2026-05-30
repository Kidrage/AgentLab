# Interface Registry

## Agent Status Snapshot

Producer:

- Current: `web_ui/app.js` embedded fallback and `web_ui/agent_status.sample.json`.
- Future: AgentLab CLI or local service endpoint.

Consumer:

- `web_ui/index.html`
- `web_ui/app.js`

Shape:

- `generatedAt`: ISO timestamp.
- `project`: Project name.
- `taskId`: Active task id.
- `taskStatus`: Human-readable task status.
- `stage`: Current stage.
- `route`: Ordered list of agents in the active route.
- `agents`: Agent status records.
- `events`: Recent run events.

Agent record:

- `name`
- `role`
- `status`
- `provider`
- `model`
- `owner`
- `canEdit`
- `budgetTokens`
- `usedTokens`
