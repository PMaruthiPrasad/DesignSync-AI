import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import Overview from './pages/Overview.jsx'
import NewAnalysis from './pages/NewAnalysis.jsx'
import Analyses from './pages/Analyses.jsx'
import Execution from './pages/Execution.jsx'
import Result from './pages/Result.jsx'

export default function App() {
  const navigate = useNavigate()

  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">DS</span>
          DesignSync AI
          <span className="brand-tag">AI-powered software change impact analysis</span>
        </NavLink>

        <nav className="nav">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/new">New Analysis</NavLink>
          <NavLink to="/analyses">Analyses</NavLink>
        </nav>

        <button className="btn btn-primary btn-sm" onClick={() => navigate('/new')}>
          New Analysis
        </button>
      </header>

      <main className="page">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/new" element={<NewAnalysis />} />
          <Route path="/analyses" element={<Analyses />} />
          <Route path="/executions/:executionId" element={<Execution />} />
          <Route path="/analyses/:analysisId" element={<Result />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
