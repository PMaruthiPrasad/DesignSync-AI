/**
 * Impact map: the changed file and everything that reaches it.
 *
 * Built from the repository's real import graph (deterministic AST output),
 * not from model narration — so the tree is verifiable.
 */

const SEVERITY_BY_COMPONENT = (components) =>
  Object.fromEntries(components.map((c) => [c.component, c.severity]))

function Node({ path, severity }) {
  return (
    <span className={`impact-node risk-${severity || 'LOW'}`}>
      <span className="path">{path}</span>
      {severity && <span className={`badge badge-${severity}`}>{severity}</span>}
    </span>
  )
}

export default function ImpactMap({ repositorySummary, components = [] }) {
  const severities = SEVERITY_BY_COMPONENT(components)
  const root = components[0]?.component

  if (!root) {
    return <p className="dim mb-0">No impact map available.</p>
  }

  const importedBy = repositorySummary?.imported_by || {}

  // Direct consumers of the changed file, excluding package __init__ shims.
  const direct = (importedBy[root] || []).filter((f) => !f.endsWith('__init__.py'))

  // One more hop out, for consumers of those consumers.
  const indirect = {}
  direct.forEach((file) => {
    indirect[file] = (importedBy[file] || []).filter(
      (f) => !f.endsWith('__init__.py') && f !== root && !direct.includes(f),
    )
  })

  return (
    <div className="impact-map">
      <div>
        <Node path={root} severity={severities[root]} />
      </div>

      {direct.map((file, index) => {
        const isLast = index === direct.length - 1
        const children = indirect[file] || []
        return (
          <div key={file}>
            <div>
              <span className="impact-tree-line">{isLast ? '    └── ' : '    ├── '}</span>
              <Node path={file} severity={severities[file]} />
            </div>
            {children.map((child, childIndex) => (
              <div key={child}>
                <span className="impact-tree-line">
                  {isLast ? '        ' : '    │   '}
                  {childIndex === children.length - 1 ? '└── ' : '├── '}
                </span>
                <Node path={child} severity={severities[child]} />
              </div>
            ))}
          </div>
        )
      })}

      {!direct.length && (
        <div className="dim" style={{ paddingTop: 6 }}>
          Nothing in this repository imports {root}.
        </div>
      )}
    </div>
  )
}
