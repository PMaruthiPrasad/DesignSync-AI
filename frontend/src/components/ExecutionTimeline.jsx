import { AGENT_LABELS, formatDuration } from './common.jsx'

/**
 * Gantt view of the run, positioned by each agent's real start/end timestamps.
 *
 * This is the honest evidence of concurrency: the three analyst bars visibly
 * overlap. Set the concurrency limit to 1 and the same chart shows them
 * stacked end to end.
 */

const ORDER = [
  'planner',
  'code_analyst',
  'documentation_analyst',
  'dependency_analyst',
  'impact_reviewer',
]

function toMs(value) {
  if (!value) return null
  const iso = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Date(iso).getTime()
}

export default function ExecutionTimeline({ agents = [] }) {
  const timed = agents.filter((a) => a.started_at)
  if (!timed.length) {
    return <p className="dim small mb-0">Timing appears once the first agent starts.</p>
  }

  const starts = timed.map((a) => toMs(a.started_at))
  const ends = timed.map((a) => toMs(a.completed_at) ?? toMs(a.started_at) + (a.duration_ms || 0))
  const t0 = Math.min(...starts)
  const t1 = Math.max(...ends, t0 + 1)
  const span = Math.max(t1 - t0, 1)

  const ordered = [...agents].sort(
    (a, b) => ORDER.indexOf(a.agent_name) - ORDER.indexOf(b.agent_name),
  )

  return (
    <div>
      <div className="timeline">
        {ordered.map((agent) => {
          const start = toMs(agent.started_at)
          const end = toMs(agent.completed_at) ?? (start ? start + (agent.duration_ms || 0) : null)
          const left = start ? ((start - t0) / span) * 100 : 0
          const width = start && end ? Math.max(((end - start) / span) * 100, 1.5) : 0

          return (
            <div className="timeline-row" key={agent.agent_name}>
              <span className="timeline-name">
                {AGENT_LABELS[agent.agent_name] || agent.agent_name}
              </span>
              <div className="timeline-track">
                {start && (
                  <div
                    className={`timeline-bar status-${agent.status}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                )}
              </div>
              <span className="timeline-duration">{formatDuration(agent.duration_ms)}</span>
            </div>
          )
        })}
      </div>
      <p className="timeline-caption mb-0">
        Bars are positioned by measured start and end times. Overlapping bars are concurrent
        agents.
      </p>
    </div>
  )
}
