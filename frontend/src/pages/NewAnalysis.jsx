import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client.js'
import { ErrorBox, Section } from '../components/common.jsx'

const PLACEHOLDER = `Example:
Changed discount calculation from purchase-history based to customer-segment based.`

export default function NewAnalysis() {
  const navigate = useNavigate()

  const [changeDescription, setChangeDescription] = useState('')
  const [repository, setRepository] = useState(null) // null = demo repo
  const [demoInfo, setDemoInfo] = useState(null)
  const [health, setHealth] = useState(null)

  const [mockLlm, setMockLlm] = useState(true)
  const [concurrency, setConcurrency] = useState(3)

  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.health().then((data) => {
      setHealth(data)
      setMockLlm(data.mock_llm)
    }).catch(() => {})
  }, [])

  const loadDemo = async () => {
    setError(null)
    try {
      const demo = await api.getDemoRepository()
      setDemoInfo(demo)
      setRepository(null)
      if (!changeDescription.trim()) {
        setChangeDescription(demo.default_change_description)
      }
    } catch (err) {
      setError(err.message)
    }
  }

  const onUpload = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const uploaded = await api.uploadRepository(file)
      setRepository(uploaded)
      setDemoInfo(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const analysis = await api.createAnalysis({
        change_description: changeDescription.trim(),
        repository_id: repository?.repository_id ?? null,
        mock_llm: mockLlm,
        concurrency_limit: Number(concurrency),
      })
      const execution = await api.executeAnalysis(analysis.id)
      navigate(`/executions/${execution.execution_id}`)
    } catch (err) {
      setError(err.message)
      setSubmitting(false)
    }
  }

  const activeRepo = repository
    ? { name: repository.repository_name, summary: repository.summary }
    : demoInfo
      ? { name: demoInfo.repository_name, summary: demoInfo.summary }
      : null

  const canSubmit = changeDescription.trim().length >= 10 && !submitting && !uploading

  return (
    <>
      <div className="page-header">
        <h1>Understand a Software Change</h1>
        <p className="subtitle mb-0">
          Analyze code impact, dependencies and documentation drift with AI agents.
        </p>
      </div>

      {error && <ErrorBox title="Could not start the analysis" message={error} />}

      <form onSubmit={submit}>
        <Section title="1 · Repository">
          <div className="option-row">
            <div
              className={`option-card${!repository ? ' selected' : ''}`}
              onClick={loadDemo}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && loadDemo()}
            >
              <h4>Use Demo Repository</h4>
              <p>
                A small Python commerce backend with pricing, checkout, an API layer, tests and
                documentation. The fastest way to see the full flow.
              </p>
              <div className="mt-16">
                <button type="button" className="btn btn-sm" onClick={loadDemo}>
                  Load Demo Repository
                </button>
              </div>
            </div>

            <div className={`option-card${repository ? ' selected' : ''}`}>
              <h4>Upload Repository ZIP</h4>
              <p>
                A Python repository as a .zip. Files are read as text and parsed — never imported
                or executed.
              </p>
              <div className="mt-16">
                <label className="btn btn-sm" style={{ cursor: 'pointer' }}>
                  {uploading ? 'Uploading…' : 'Upload ZIP'}
                  <input type="file" accept=".zip" hidden onChange={onUpload} disabled={uploading} />
                </label>
              </div>
            </div>
          </div>

          {activeRepo && (
            <div className="banner banner-info mt-16">
              <span className="repo-chip">{activeRepo.name}</span>
              <span>
                {activeRepo.summary.files.length} files ·{' '}
                {activeRepo.summary.python_modules.length} modules ·{' '}
                {activeRepo.summary.documentation_files.length} docs ·{' '}
                {activeRepo.summary.test_files.length} test files — parsed deterministically
              </span>
            </div>
          )}
        </Section>

        <Section title="2 · Change Description">
          <div className="field-hint">
            Describe what changed in plain language. Phrasing it as “changed X from A to B” gives
            the agents the most to work with.
          </div>
          <textarea
            value={changeDescription}
            onChange={(e) => setChangeDescription(e.target.value)}
            placeholder={PLACEHOLDER}
            rows={5}
            aria-label="Change description"
          />
        </Section>

        <Section title="3 · Analysis Settings">
          <div className="card">
            <div className="row-between">
              <div>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={mockLlm}
                    onChange={(e) => setMockLlm(e.target.checked)}
                  />
                  <span>
                    <strong>Mock LLM</strong>
                    <div className="field-hint mb-0">
                      Deterministic offline agents. No API calls, no credentials.
                      {health && !health.mock_llm && ' Uncheck to use the configured provider.'}
                    </div>
                  </span>
                </label>
              </div>

              <div style={{ minWidth: 190 }}>
                <span className="field-label">Concurrency limit</span>
                <select value={concurrency} onChange={(e) => setConcurrency(e.target.value)}>
                  <option value={1}>1 — run agents one at a time</option>
                  <option value={2}>2</option>
                  <option value={3}>3 — all branches in parallel (default)</option>
                  <option value={5}>5</option>
                </select>
                <div className="field-hint mb-0" style={{ marginTop: 6 }}>
                  Caps simultaneous LLM requests. Set to 1 to see the branches serialise.
                </div>
              </div>
            </div>
          </div>
        </Section>

        <button className="btn btn-primary btn-lg" type="submit" disabled={!canSubmit}>
          {submitting ? <><span className="spinner" />Starting…</> : 'Analyze Change'}
        </button>
        {changeDescription.trim().length > 0 && changeDescription.trim().length < 10 && (
          <span className="dim small" style={{ marginLeft: 12 }}>
            Add a little more detail to continue.
          </span>
        )}
      </form>
    </>
  )
}
