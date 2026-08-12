/** Small shared presentational pieces. */

export function Badge({ value, pulse = false }) {
  if (!value) return null
  return (
    <span className={`badge badge-${value}`}>
      {pulse && <span className="dot pulse" />}
      {String(value).replace(/_/g, ' ')}
    </span>
  )
}

export function Stat({ label, value, hint, severity }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${severity ? ` sev-${severity}` : ''}`}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function Loading({ message = 'Loading…' }) {
  return (
    <div className="loading">
      <span className="spinner" />
      {message}
    </div>
  )
}

export function ErrorBox({ title = 'Something went wrong', message, onRetry }) {
  return (
    <div className="error-box">
      <strong>{title}</strong>
      <span>{message}</span>
      {onRetry && (
        <div className="mt-16">
          <button className="btn btn-sm" onClick={onRetry}>Try again</button>
        </div>
      )}
    </div>
  )
}

export function Empty({ title, message, action }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{message}</p>
      {action}
    </div>
  )
}

export function Section({ title, count, children }) {
  return (
    <section className="section">
      <div className="section-title">
        <h2>{title}</h2>
        {count != null && <span className="count">{count}</span>}
      </div>
      {children}
    </section>
  )
}

/** Milliseconds as a human duration. */
export function formatDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function formatDate(value) {
  if (!value) return '—'
  const iso = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatConfidence(value) {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

export function formatCost(value) {
  if (value == null) return '—'
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`
}

export function formatTokens(value) {
  if (value == null) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

export const AGENT_LABELS = {
  planner: 'Planner',
  code_analyst: 'Code Analyst',
  documentation_analyst: 'Documentation Analyst',
  dependency_analyst: 'Dependency Analyst',
  impact_reviewer: 'Impact Reviewer',
}
