import { AGENT_LABELS, Badge, formatConfidence, formatDuration } from './common.jsx'

/**
 * The five-agent workflow, rendered in the same shape the backend executes:
 * Planner, then three concurrent branches, then the Impact Reviewer.
 *
 * Node status comes from real agent records, so a WAITING reviewer beside
 * three RUNNING analysts is the actual execution state, not an animation.
 */

const PARALLEL = ['code_analyst', 'documentation_analyst', 'dependency_analyst']

function Node({ agent }) {
  const status = agent?.status || 'WAITING'
  return (
    <div className={`node status-${status}`}>
      <div className="node-head">
        <span className="node-name">{AGENT_LABELS[agent?.agent_name] || agent?.agent_name}</span>
        <Badge value={status} pulse={status === 'RUNNING'} />
      </div>
      <div className="node-meta">
        <span>{formatDuration(agent?.duration_ms)}</span>
        <span>{agent?.confidence != null ? formatConfidence(agent.confidence) : '—'}</span>
      </div>
    </div>
  )
}

function FanOut() {
  return (
    <div className="graph-connector">
      <svg width="440" height="26" viewBox="0 0 440 26" fill="none" aria-hidden="true">
        <path
          d="M220 0 v9 M60 26 v-8 h320 v8 M220 9 h-160 M220 9 h160"
          stroke="currentColor"
          strokeWidth="1"
        />
      </svg>
    </div>
  )
}

function Arrow() {
  return (
    <div className="graph-connector">
      <svg width="12" height="26" viewBox="0 0 12 26" fill="none" aria-hidden="true">
        <path d="M6 0 v20 M2 16 l4 5 l4 -5" stroke="currentColor" strokeWidth="1" />
      </svg>
    </div>
  )
}

export default function AgentGraph({ agents = [], concurrencyLimit = 3 }) {
  const byName = Object.fromEntries(agents.map((a) => [a.agent_name, a]))

  // Tell the truth about what is actually happening: with a limit of 1 these
  // branches are independent in the graph but still execute one at a time.
  const branchLabel =
    concurrencyLimit <= 1
      ? 'independent branches — serialised by concurrency limit 1'
      : concurrencyLimit < PARALLEL.length
        ? `independent branches — up to ${concurrencyLimit} at a time`
        : 'running concurrently'

  return (
    <div className="graph">
      <div className="graph-row">
        <Node agent={byName.planner || { agent_name: 'planner' }} />
      </div>

      <FanOut />
      <div className="graph-parallel-label">{branchLabel}</div>

      <div className="graph-row">
        {PARALLEL.map((name) => (
          <Node key={name} agent={byName[name] || { agent_name: name }} />
        ))}
      </div>

      <Arrow />

      <div className="graph-row">
        <Node agent={byName.impact_reviewer || { agent_name: 'impact_reviewer' }} />
      </div>
    </div>
  )
}
