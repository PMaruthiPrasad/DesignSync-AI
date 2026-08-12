import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  Section,
  Stat,
  formatDate,
  formatDuration,
} from '../components/common.jsx'

export default function Overview() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .getDashboardStats()
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <>
      <div className="page-header">
        <h1>Overview</h1>
        <p className="subtitle mb-0">
          Change-impact analyses across your repositories.
        </p>
      </div>

      {loading && <Loading message="Loading dashboard…" />}
      {error && <ErrorBox message={error} onRetry={load} />}

      {stats && !loading && (
        <>
          <div className="stat-grid section">
            <Stat label="Total Analyses" value={stats.total_analyses} />
            <Stat label="Successful" value={stats.successful_analyses} />
            <Stat
              label="High Impact Changes"
              value={stats.high_impact_changes}
              severity={stats.high_impact_changes > 0 ? 'HIGH' : null}
            />
            <Stat label="Documentation Updates" value={stats.documentation_updates} />
            <Stat
              label="Avg Duration"
              value={formatDuration(stats.average_duration_ms)}
              hint="measured wall clock"
            />
            <Stat
              label="Avg Speedup"
              value={stats.average_speedup ? `${stats.average_speedup.toFixed(2)}x` : '—'}
              hint="vs estimated sequential"
            />
          </div>

          <Section title="Recent Analyses" count={stats.recent_analyses.length || null}>
            {stats.recent_analyses.length === 0 ? (
              <Empty
                title="No analyses yet"
                message="Run your first software change analysis."
                action={
                  <button className="btn btn-primary" onClick={() => navigate('/new')}>
                    Start Analysis
                  </button>
                }
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Analysis</th>
                      <th>Repository</th>
                      <th>Status</th>
                      <th>Severity</th>
                      <th>Duration</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.recent_analyses.map((analysis) => (
                      <tr key={analysis.id}>
                        <td>
                          <Link to={`/analyses/${analysis.id}`}>{analysis.name}</Link>
                        </td>
                        <td className="nowrap">
                          <span className="path mono">{analysis.repository_name}</span>
                        </td>
                        <td><Badge value={analysis.status} /></td>
                        <td><Badge value={analysis.overall_severity} /></td>
                        <td className="nowrap mono dim">{formatDuration(analysis.duration_ms)}</td>
                        <td className="nowrap dim">{formatDate(analysis.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </>
  )
}
