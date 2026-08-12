import {
  AGENT_LABELS,
  Badge,
  formatConfidence,
  formatCost,
  formatDuration,
  formatTokens,
} from './common.jsx'

/**
 * Expandable observability panel for one agent.
 *
 * Shows only what the agent deliberately produced: its prompts, its structured
 * output, and its usage. Model chain-of-thought is never requested, never
 * stored and never displayed — the `reasoning` field is an intentional output
 * field of the Planner's schema, not hidden reasoning.
 */

function Row({ label, value }) {
  return (
    <div>
      <div className="kv-label">{label}</div>
      <div className="kv-value">{value}</div>
    </div>
  )
}

export default function AgentDetails({ agent, defaultOpen = false }) {
  const label = AGENT_LABELS[agent.agent_name] || agent.agent_name

  return (
    <details className="agent-panel" open={defaultOpen}>
      <summary>
        <span className="summary-caret">▶</span>
        <span className="summary-name">{label}</span>
        <span className="summary-metrics">
          <span>{formatDuration(agent.duration_ms)}</span>
          <span>{formatTokens(agent.total_tokens)} tok</span>
          <span>{formatConfidence(agent.confidence)}</span>
        </span>
        <Badge value={agent.status} />
      </summary>

      <div className="panel-body">
        <div className="kv-grid">
          <Row label="Model" value={agent.model || '—'} />
          <Row label="Provider" value={agent.provider || '—'} />
          <Row label="Prompt tokens" value={formatTokens(agent.prompt_tokens)} />
          <Row label="Completion tokens" value={formatTokens(agent.completion_tokens)} />
          <Row label="Total tokens" value={formatTokens(agent.total_tokens)} />
          <Row label="Estimated cost" value={formatCost(agent.estimated_cost)} />
          <Row label="Duration" value={formatDuration(agent.duration_ms)} />
          <Row label="Confidence" value={formatConfidence(agent.confidence)} />
        </div>

        {agent.error && (
          <div className="error-box" style={{ marginBottom: 12 }}>
            <strong>Agent failed</strong>
            <span className="mono">{agent.error}</span>
          </div>
        )}

        {agent.output_data?.reasoning && (
          <>
            <div className="block-label">Reasoning summary</div>
            <div className="prompt-block">{agent.output_data.reasoning}</div>
          </>
        )}

        <div className="block-label">System prompt</div>
        <div className="prompt-block">{agent.system_prompt || '—'}</div>

        <div className="block-label">User prompt (evidence supplied to the agent)</div>
        <div className="prompt-block">{agent.user_prompt || '—'}</div>

        <div className="block-label">Structured output</div>
        <div className="prompt-block">
          {agent.output_data ? JSON.stringify(agent.output_data, null, 2) : 'No output produced.'}
        </div>
      </div>
    </details>
  )
}
