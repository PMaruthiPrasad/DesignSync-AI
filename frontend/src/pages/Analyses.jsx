import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  formatDate,
  formatDuration,
} from '../components/common.jsx'

export default function Analyses() {
  const [analyses, setAnalyses] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .listAnalyses()
      .then(setAnalyses)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <>
      <div className="page-header">
        <h1>Analyses</h1>
        <p className="subtitle mb-0">Every change-impact analysis you have run.</p>
      </div>

      {loading && <Loading message="Loading analyses…" />}
      {error && <ErrorBox message={error} onRetry={load} />}

      {analyses && !loading && analyses.length === 0 && (
        <Empty
          title="No analyses yet"
          message="Run your first software change analysis."
          action={
            <button className="btn btn-primary" onClick={() => navigate('/new')}>
              Start Analysis
            </button>
          }
        />
      )}

      {analyses && analyses.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Analysis</th>
                <th>Change</th>
                <th>Repository</th>
                <th>Status</th>
                <th>Severity</th>
                <th>Components</th>
                <th>Docs</th>
                <th>Duration</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {analyses.map((analysis) => (
                <tr key={analysis.id}>
                  <td><Link to={`/analyses/${analysis.id}`}>{analysis.name}</Link></td>
                  <td className="muted small" style={{ maxWidth: 320 }}>
                    {analysis.change_description}
                  </td>
                  <td className="nowrap"><span className="path mono">{analysis.repository_name}</span></td>
                  <td><Badge value={analysis.status} /></td>
                  <td><Badge value={analysis.overall_severity} /></td>
                  <td className="mono dim">{analysis.affected_component_count}</td>
                  <td className="mono dim">{analysis.documentation_update_count}</td>
                  <td className="nowrap mono dim">{formatDuration(analysis.duration_ms)}</td>
                  <td className="nowrap dim">{formatDate(analysis.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
