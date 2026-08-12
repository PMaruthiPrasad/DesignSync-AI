import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import AgentDetails from '../components/AgentDetails.jsx'
import ImpactMap from '../components/ImpactMap.jsx'
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

export default function Result() {
  const { analysisId } = useParams()
  const [analysis, setAnalysis] = useState(null)
  const [agents, setAgents] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    api
      .getAnalysis(analysisId)
      .then((data) => {
        setAnalysis(data)
        if (data.latest_execution_id) {
          return api
            .getExecutionAgents(data.latest_execution_id)
            .then(setAgents)
            .catch(() => {})
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [analysisId])

  if (loading) return <Loading message="Loading report…" />
  if (error) return <ErrorBox title="Could not load the report" message={error} onRetry={load} />
  if (!analysis) return null

  const report = analysis.report

  if (!report) {
    return (
      <Empty
        title="No report yet"
        message="This analysis has not produced a report. Run it to generate one."
        action={
          analysis.latest_execution_id ? (
            <Link className="btn" to={`/executions/${analysis.latest_execution_id}`}>
              View execution
            </Link>
          ) : null
        }
      />
    )
  }

  const tests = report.recommended_tests || []
  const documents = report.documentation_updates || []
  const components = report.affected_components || []

  return (
    <>
      <div className="page-header">
        <div className="row-between">
          <div>
            <h1>Software Change Impact Report</h1>
            <p className="subtitle mb-0">
              {analysis.repository_name} · {formatDate(analysis.created_at)} ·{' '}
              {formatDuration(analysis.duration_ms)}
            </p>
          </div>
          <div className="row">
            <Badge value={analysis.status} />
            {analysis.latest_execution_id && (
              <Link className="btn btn-sm" to={`/executions/${analysis.latest_execution_id}`}>
                Execution details
              </Link>
            )}
          </div>
        </div>
      </div>

      <div className="card section">
        <div className="kv-label">Change analysed</div>
        <div className="change-quote">{analysis.change_description}</div>
      </div>

      <div className="stat-grid section">
        <Stat label="Overall Impact" value={report.overall_severity} severity={report.overall_severity} />
        <Stat
          label="Affected Components"
          value={components.length}
          hint={components.length === 1 ? 'component' : 'components'}
        />
        <Stat
          label="Documentation Updates"
          value={documents.length}
          hint={documents.length === 1 ? 'document' : 'documents'}
        />
        <Stat
          label="Recommended Tests"
          value={tests.length}
          hint={tests.length === 1 ? 'test area' : 'test areas'}
        />
      </div>

      {report.degraded && (
        <div className="banner banner-warn">
          This report is degraded — the synthesis agent did not complete. Treat the findings as
          partial.
        </div>
      )}

      <Section title="1 · Executive Summary">
        <div className="card">
          <p className="mb-0">{report.summary}</p>
        </div>
      </Section>

      <Section title="2 · Impact Map">
        <ImpactMap
          repositorySummary={analysis.repository_summary}
          components={components}
        />
      </Section>

      <Section title="3 · Affected Components" count={components.length}>
        {components.length === 0 ? (
          <p className="dim">No components identified.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Impact</th>
                  <th>Severity</th>
                  <th>Evidence</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {components.map((component) => (
                  <tr key={component.component}>
                    <td className="nowrap"><span className="path">{component.component}</span></td>
                    <td>{component.impact}</td>
                    <td><Badge value={component.severity} /></td>
                    <td><span className="evidence">{component.evidence}</span></td>
                    <td className="nowrap mono dim">
                      {Math.round((component.confidence || 0) * 100)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="4 · Documentation Drift" count={documents.length}>
        {documents.length === 0 ? (
          <p className="dim">No documentation appears to be affected.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Status</th>
                  <th>Reason</th>
                  <th>Recommended Action</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.document}>
                    <td className="nowrap"><span className="path">{document.document}</span></td>
                    <td><Badge value={document.status} /></td>
                    <td>{document.reason}</td>
                    <td>{document.recommended_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="5 · Recommended Tests" count={tests.length}>
        {tests.length === 0 ? (
          <p className="dim">No test changes recommended.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Reason</th>
                  <th>Affected Component</th>
                  <th>Priority</th>
                </tr>
              </thead>
              <tbody>
                {tests.map((test, index) => (
                  <tr key={`${test.test_name}-${index}`}>
                    <td className="nowrap"><span className="path">{test.test_name}</span></td>
                    <td>{test.reason}</td>
                    <td className="nowrap"><span className="path">{test.affected_component}</span></td>
                    <td><Badge value={test.priority} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="6 · Recommended Engineering Actions">
        <div className="card">
          <ol className="actions">
            {(report.recommended_actions || []).map((action, index) => (
              <li key={index}>{action}</li>
            ))}
          </ol>
        </div>
      </Section>

      <Section title="7 · Confidence & Evidence">
        <p className="dim small">
          Findings are separated by how well the evidence supports them. Confirmed findings are
          backed by the repository's parsed import graph; the rest are model inference and are
          labelled as such.
        </p>
        <div className="evidence-grid">
          <EvidenceColumn
            kind="confirmed"
            title="Confirmed"
            hint="Backed by hard evidence"
            items={report.confirmed_findings}
          />
          <EvidenceColumn
            kind="likely"
            title="Likely"
            hint="Well-supported inference"
            items={report.likely_findings}
          />
          <EvidenceColumn
            kind="uncertain"
            title="Uncertain"
            hint="Unverified or evidence missing"
            items={report.uncertain_findings}
          />
        </div>

        {(report.contradictions?.length > 0 || report.unsupported_claims?.length > 0) && (
          <div className="card mt-16">
            {report.contradictions?.length > 0 && (
              <>
                <div className="kv-label">Contradictions detected</div>
                <ul className="risks">
                  {report.contradictions.map((item, index) => <li key={index}>{item}</li>)}
                </ul>
              </>
            )}
            {report.unsupported_claims?.length > 0 && (
              <>
                <div className="kv-label mt-16">Unsupported claims</div>
                <ul className="risks">
                  {report.unsupported_claims.map((item, index) => <li key={index}>{item}</li>)}
                </ul>
              </>
            )}
          </div>
        )}
      </Section>

      {report.risks?.length > 0 && (
        <Section title="Risks" count={report.risks.length}>
          <div className="card">
            <ul className="risks">
              {report.risks.map((risk, index) => <li key={index}>{risk}</li>)}
            </ul>
          </div>
        </Section>
      )}

      {agents.length > 0 && (
        <Section title="Agent Execution Details" count={agents.length}>
          {agents.map((agent) => (
            <AgentDetails key={agent.id || agent.agent_name} agent={agent} />
          ))}
        </Section>
      )}
    </>
  )
}

function EvidenceColumn({ kind, title, hint, items = [] }) {
  return (
    <div className={`evidence-col ${kind}`}>
      <h4>{title}</h4>
      <div className="tier-hint">{hint}</div>
      {items.length === 0 ? (
        <span className="dim small">None</span>
      ) : (
        <ul>
          {items.map((item, index) => <li key={index}>{item}</li>)}
        </ul>
      )}
    </div>
  )
}
