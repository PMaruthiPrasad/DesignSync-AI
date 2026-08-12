import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import AgentGraph from '../components/AgentGraph.jsx'
import AgentDetails from '../components/AgentDetails.jsx'
import ExecutionTimeline from '../components/ExecutionTimeline.jsx'
import {
  Badge,
  ErrorBox,
  Loading,
  Section,
  Stat,
  formatCost,
  formatDuration,
  formatTokens,
} from '../components/common.jsx'

const POLL_MS = 500
const TERMINAL = ['SUCCESS', 'PARTIAL', 'FAILED']

export default function Execution() {
  const { executionId } = useParams()
  const navigate = useNavigate()

  const [execution, setExecution] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)

  const lastSeq = useRef(0)
  const timer = useRef(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const [current, newEvents] = await Promise.all([
          api.getExecution(executionId),
          api.getExecutionEvents(executionId, lastSeq.current),
        ])
        if (cancelled) return

        setExecution(current)
        if (newEvents.length) {
          lastSeq.current = newEvents[newEvents.length - 1].seq
          setEvents((previous) => [...previous, ...newEvents])
        }

        if (!analysis) {
          api.getAnalysis(current.analysis_id).then(setAnalysis).catch(() => {})
        }

        if (TERMINAL.includes(current.status)) {
          // Refresh the analysis once so the "View report" link has the final data.
          api.getAnalysis(current.analysis_id).then(setAnalysis).catch(() => {})
          return
        }
        timer.current = setTimeout(poll, POLL_MS)
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    poll()
    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executionId])

  if (error) return <ErrorBox title="Could not load the execution" message={error} />
  if (!execution) return <Loading message="Starting analysis…" />

  const { metrics, agents, status } = execution
  const finished = TERMINAL.includes(status)
  const speedup = metrics.estimated_speedup

  return (
    <>
      <div className="page-header">
        <div className="row-between">
          <div>
            <h1>Analyzing Software Change</h1>
            <p className="subtitle mb-0">
              {finished
                ? 'Execution finished. Metrics below are measured from this run.'
                : 'Agents are running. This page updates as they progress.'}
            </p>
          </div>
          <Badge value={status} pulse={!finished} />
        </div>
      </div>

      {analysis && (
        <div className="card section">
          <div className="meta-list">
            <div className="meta-item">
              <div className="kv-label">Analysis</div>
              <div>{analysis.name}</div>
            </div>
            <div className="meta-item">
              <div className="kv-label">Repository</div>
              <div><span className="repo-chip">{analysis.repository_name}</span></div>
            </div>
            <div className="meta-item">
              <div className="kv-label">Concurrency limit</div>
              <div className="mono">{metrics.concurrency_limit}</div>
            </div>
          </div>
          <div className="mt-16">
            <div className="kv-label">Change description</div>
            <div className="change-quote">{analysis.change_description}</div>
          </div>
        </div>
      )}

      <Section title="Agent Workflow">
        <AgentGraph agents={agents} concurrencyLimit={metrics.concurrency_limit} />
      </Section>

      <Section title="Execution Metrics">
        <div className="stat-grid">
          <Stat
            label="Actual Duration"
            value={formatDuration(metrics.duration_ms)}
            hint="measured wall clock"
          />
          <Stat
            label="Est. Sequential Duration"
            value={formatDuration(metrics.estimated_sequential_duration_ms)}
            hint="estimate — sum of agent durations"
          />
          <Stat
            label="Est. Time Saved"
            value={formatDuration(metrics.estimated_time_saved_ms)}
            hint="estimate"
          />
          <Stat
            label="Est. Speedup"
            value={speedup ? `${speedup.toFixed(2)}x` : '—'}
            hint={`estimate — ${metrics.parallel_agent_count} parallel agents`}
          />
          <Stat label="Total Tokens" value={formatTokens(metrics.total_tokens)} />
          <Stat label="Estimated Cost" value={formatCost(metrics.estimated_cost)} />
        </div>
      </Section>

      <Section title="Execution Timeline">
        <div className="card">
          <ExecutionTimeline agents={agents} />
        </div>
      </Section>

      <Section title="Progress Log" count={events.length}>
        <div className="card" style={{ maxHeight: 240, overflow: 'auto' }}>
          {events.map((event) => (
            <div key={event.seq} className="row small" style={{ padding: '2px 0' }}>
              <span className="dim mono" style={{ width: 34 }}>{event.seq}</span>
              <span
                className={
                  event.event_type.includes('failed') ? 'badge badge-FAILED' : 'dim mono small'
                }
                style={{ minWidth: 150 }}
              >
                {event.event_type}
              </span>
              <span className="muted">{event.message}</span>
            </div>
          ))}
          {!events.length && <span className="dim small">Waiting for the first event…</span>}
        </div>
      </Section>

      <Section title="Agent Details" count={agents.length}>
        {agents.map((agent) => (
          <AgentDetails key={agent.id || agent.agent_name} agent={agent} />
        ))}
      </Section>

      {finished && (
        <button
          className="btn btn-primary btn-lg"
          onClick={() => navigate(`/analyses/${execution.analysis_id}`)}
        >
          View Impact Report →
        </button>
      )}
    </>
  )
}
