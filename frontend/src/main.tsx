import React, { useCallback, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ReactFlow, { Background, Controls, MiniMap, type Edge, type Node } from 'reactflow'
import 'reactflow/dist/style.css'
import './styles.css'

type SymbolInfo = { name: string; kind: string; line: number; summary: string }
type AnalysisNode = {
  id: string
  label: string
  kind: 'file' | 'module' | 'external'
  parent: string | null
  language: string
  summary: string
  symbols: SymbolInfo[]
  file_count: number
  children_ids: string[]
}
type AnalyzeStats = {
  file_count: number
  module_count: number
  external_count: number
  symbol_count: number
  edge_count: number
}
type Result = {
  nodes: AnalysisNode[]
  edges: { source: string; target: string; kind: string }[]
  overview: string
  insights: string[]
  stats: AnalyzeStats
}

const IGNORE_PATTERNS = [
  '/node_modules/', '/.venv/', '/venv/', '/env/', '/.env/', '/.git/',
  '/dist/', '/build/', '/__pycache__/', '/.pytest_cache/', '/.next/', '/out/', '/coverage/'
]

function isIgnoredPath(path: string): boolean {
  const norm = '/' + path.replace(/\\/g, '/').toLowerCase().replace(/^\/+/, '') + '/'
  return IGNORE_PATTERNS.some(pat => norm.includes(pat))
}

const demoFiles = [
  { path: 'src/main.py', content: 'import fastapi\nfrom services.report import build_report\n\ndef run():\n    return build_report()\n' },
  { path: 'src/services/report.py', content: 'import react\nfrom models.user import User\n\ndef build_report():\n    return User()\n' },
  { path: 'src/models/user.py', content: 'import pydantic\n\nclass User:\n    def __init__(self):\n        self.name = "Visitor"\n' },
]

function App() {
  const [result, setResult] = useState<Result | null>(null)
  const [selected, setSelected] = useState<AnalysisNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  
  // State for expanded module directory IDs
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedLanguage, setSelectedLanguage] = useState<string>('All')
  const [excludeExternal, setExcludeExternal] = useState<boolean>(true)
  const [showOverview, setShowOverview] = useState<boolean>(false)

  const analyze = useCallback(async (files: { path: string; content: string }[]) => {
    setLoading(true); setError(''); setSelected(null)
    try {
      const response = await fetch('http://localhost:8000/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files })
      })
      if (!response.ok) throw new Error((await response.json()).detail || 'Analysis failed')
      const data: Result = await response.json()
      setResult(data)
      
      // Auto-expand top-level module directories
      const rootModules = data.nodes.filter(n => n.kind === 'module' && !n.parent).map(n => n.id)
      setExpandedModules(new Set(rootModules))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach the analysis service.')
    } finally {
      setLoading(false)
    }
  }, [])

  const onPick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const rawFiles = Array.from(event.target.files || [])
    const filteredFiles = rawFiles.filter(f => {
      const path = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name
      const isGitIgnore = f.name.toLowerCase() === '.gitignore'
      return (/\.(py|js|jsx|ts|tsx|json)$/i.test(f.name) || isGitIgnore) && !isIgnoredPath(path)
    })

    if (!filteredFiles.length) {
      setError('No valid source files found in the selected folder.')
      return
    }

    const files = await Promise.all(filteredFiles.map(async f => ({
      path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name,
      content: await f.text()
    })))

    analyze(files)
  }

  const toggleModule = useCallback((modId: string, event: React.MouseEvent) => {
    event.stopPropagation()
    setExpandedModules(prev => {
      const next = new Set(prev)
      if (next.has(modId)) {
        next.delete(modId)
      } else {
        next.add(modId)
      }
      return next
    })
  }, [])

  const expandAll = useCallback(() => {
    if (!result) return
    const allModIds = result.nodes.filter(n => n.kind === 'module').map(n => n.id)
    setExpandedModules(new Set(allModIds))
  }, [result])

  const collapseAll = useCallback(() => {
    setExpandedModules(new Set())
  }, [])

  // Map of nodes by ID
  const nodeMap = useMemo(() => {
    const map = new Map<string, AnalysisNode>()
    result?.nodes.forEach(n => map.set(n.id, n))
    return map
  }, [result])

  // Check node visibility based on parent hierarchy and expanded state
  const isNodeVisible = useCallback((node: AnalysisNode): boolean => {
    if (!node.parent) return true
    let currParentId: string | null = node.parent
    while (currParentId) {
      if (!expandedModules.has(currParentId)) return false
      const parentNode = nodeMap.get(currParentId)
      currParentId = parentNode?.parent || null
    }
    return true
  }, [expandedModules, nodeMap])

  // Determine available languages for filtering (source files only)
  const availableLanguages = useMemo(() => {
    if (!result) return ['All']
    const fileLangs = result.nodes.filter(n => n.kind === 'file').map(n => n.language)
    const set = new Set(fileLangs)
    return ['All', ...Array.from(set)]
  }, [result])

  // Filtered & Visible Nodes for ReactFlow
  const flowNodes: Node[] = useMemo(() => {
    if (!result) return []

    const visibleNodes = result.nodes.filter(node => {
      if (!isNodeVisible(node)) return false

      // Checkbox filter to exclude external packages
      if (excludeExternal && node.kind === 'external') return false

      // Language Filter
      if (selectedLanguage !== 'All') {
        if (node.kind === 'file') {
          if (node.language !== selectedLanguage) return false
        } else if (node.kind === 'module') {
          const hasMatchingChild = result.nodes.some(
            n => n.kind === 'file' && n.language === selectedLanguage && n.id.startsWith(node.id + '/')
          )
          if (!hasMatchingChild) return false
        }
      }

      // Search Query Filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase()
        const matches = node.label.toLowerCase().includes(query) || node.id.toLowerCase().includes(query)
        if (node.kind === 'module') {
          const hasMatchingChild = result.nodes.some(
            n => (n.label.toLowerCase().includes(query) || n.id.toLowerCase().includes(query)) && n.id.startsWith(node.id + '/')
          )
          if (!matches && !hasMatchingChild) return false
        } else if (!matches) {
          return false
        }
      }

      return true
    })

    return visibleNodes.map((node, i) => {
      const isExpanded = expandedModules.has(node.id)
      const isModule = node.kind === 'module'
      const isExternal = node.kind === 'external'

      const icon = isExternal ? '📦' : isModule ? '📁' : '📄'
      const cardClass = isExternal ? 'node-external' : isModule ? 'node-module' : 'node-file'
      const subText = isExternal ? 'External Package' : isModule ? `${node.file_count} files` : `${node.symbols.length} symbols`

      return {
        id: node.id,
        data: {
          label: (
            <div className={`node-card ${cardClass}`}>
              <div className="node-header">
                <span className="node-icon">{icon}</span>
                <strong className="node-title">{node.label}</strong>
              </div>
              <div className="node-body">
                <small>{node.language} · {subText}</small>
                {isModule && (
                  <button className="expand-btn" onClick={(e) => toggleModule(node.id, e)}>
                    {isExpanded ? '[-] Collapse' : '[+] Expand'}
                  </button>
                )}
                {isExternal && (
                  <span className="node-external-badge">Pkg</span>
                )}
              </div>
            </div>
          )
        },
        position: { x: 80 + (i % 3) * 290, y: 80 + Math.floor(i / 3) * 180 },
        style: {
          border: isExternal ? '1px solid #9b51e0' : isModule ? '1px solid #4a7bb0' : '1px solid #31517d',
          borderRadius: 10,
          background: isExternal ? 'linear-gradient(135deg, #2b1d40 0%, #17152b 100%)' : isModule ? '#182f4d' : '#13233b',
          color: '#eaf2ff',
          padding: 10,
          minWidth: 210
        }
      }
    })
  }, [result, isNodeVisible, selectedLanguage, searchQuery, excludeExternal, expandedModules, toggleModule])

  // Compute visible ancestor for edge resolution when nodes are collapsed
  const getVisibleAncestorId = useCallback((nodeId: string, visibleSet: Set<string>): string => {
    if (visibleSet.has(nodeId)) return nodeId
    let curr = nodeMap.get(nodeId)
    while (curr && curr.parent) {
      if (visibleSet.has(curr.parent)) return curr.parent
      curr = nodeMap.get(curr.parent)
    }
    return nodeId
  }, [nodeMap])

  // Compute visible Edges
  const flowEdges: Edge[] = useMemo(() => {
    if (!result) return []

    const visibleNodeIds = new Set(flowNodes.map(n => n.id))
    const edgeSet = new Set<string>()
    const edgesList: Edge[] = []

    result.edges.forEach((edge, i) => {
      const srcVisible = getVisibleAncestorId(edge.source, visibleNodeIds)
      const tgtVisible = getVisibleAncestorId(edge.target, visibleNodeIds)

      if (srcVisible && tgtVisible && srcVisible !== tgtVisible && visibleNodeIds.has(srcVisible) && visibleNodeIds.has(tgtVisible)) {
        const edgeKey = `${srcVisible}->${tgtVisible}`
        if (!edgeSet.has(edgeKey)) {
          edgeSet.add(edgeKey)
          const isExternalEdge = edge.kind === 'external_import' || tgtVisible.startsWith('pkg:')
          edgesList.push({
            id: `edge-${edgeKey}-${i}`,
            source: srcVisible,
            target: tgtVisible,
            animated: true,
            style: { stroke: isExternalEdge ? '#b388ff' : '#65b8ff', strokeWidth: isExternalEdge ? 1.5 : 1.8, strokeDasharray: isExternalEdge ? '4 3' : undefined }
          })
        }
      }
    })

    return edgesList
  }, [result, flowNodes, getVisibleAncestorId])

  const closeProject = useCallback(() => {
    setResult(null)
    setSelected(null)
    setSearchQuery('')
    setSelectedLanguage('All')
    setError('')
  }, [])

  return (
    <main>
      <header>
        <div>
          <span className="eyebrow">CODE INTELLIGENCE</span>
          <h1>Architecture at a glance.</h1>
          <p>Map dependencies and turn unfamiliar source into an expandable, hierarchical system.</p>
        </div>
        {result ? (
          <button className="close-project-btn" onClick={closeProject}>
            ✕ Close Project
          </button>
        ) : (
          <button onClick={() => analyze(demoFiles)} disabled={loading}>
            {loading ? 'Analyzing…' : 'Try demo'}
          </button>
        )}
      </header>

      {!result && (
        <section className="dropzone-hero">
          <div className="dropzone-hero-content">
            <div className="dropzone-icon">📁</div>
            <h2>Select a Codebase to Analyze</h2>
            <p>Choose any local project folder to extract top-level functions, classes, modules, and dependencies.</p>

            <label className="hero-upload-btn">
              <input type="file" ref={input => input?.setAttribute('webkitdirectory', '')} multiple onChange={onPick} />
              <span>Choose a project folder</span>
            </label>

            <div className="hero-or-divider">
              <span>OR</span>
            </div>

            <button className="hero-demo-btn" onClick={() => analyze(demoFiles)} disabled={loading}>
              {loading ? 'Analyzing Demo…' : '⚡ Try Live Demo'}
            </button>

            {error && <p className="error">{error}</p>}
          </div>
        </section>
      )}

      {result && (
        <>
          <section className="overview-accordion">
            <button className="overview-toggle-btn" onClick={() => setShowOverview(prev => !prev)}>
              <div className="overview-toggle-left">
                <span className="toggle-icon">{showOverview ? '▼' : '►'}</span>
                <strong>📊 Codebase Summary & Architectural Insights</strong>
              </div>
              {result.stats && (
                <div className="overview-toggle-right">
                  <span className="toggle-chip">{result.stats.file_count} Files</span>
                  <span className="toggle-chip">{result.stats.module_count} Modules</span>
                  <span className="toggle-chip">{result.stats.edge_count} Links</span>
                  <span className="toggle-chip">{result.stats.external_count} Packages</span>
                  <span className="toggle-action">{showOverview ? 'Hide Details' : 'Show Details'}</span>
                </div>
              )}
            </button>

            {showOverview && (
              <div className="overview-content">
                <div className="overview-header">
                  <span className="eyebrow">PROJECT OVERVIEW</span>
                  <h2>{result.overview}</h2>
                </div>

                {result.stats && (
                  <div className="stats-grid">
                    <div className="stat-card">
                      <span className="stat-value">{result.stats.file_count}</span>
                      <span className="stat-label">Source Files</span>
                    </div>
                    <div className="stat-card">
                      <span className="stat-value">{result.stats.module_count}</span>
                      <span className="stat-label">Modules</span>
                    </div>
                    <div className="stat-card">
                      <span className="stat-value">{result.stats.symbol_count}</span>
                      <span className="stat-label">Symbols</span>
                    </div>
                    <div className="stat-card">
                      <span className="stat-value">{result.stats.edge_count}</span>
                      <span className="stat-label">Dependencies</span>
                    </div>
                    <div className="stat-card">
                      <span className="stat-value">{result.stats.external_count}</span>
                      <span className="stat-label">Packages</span>
                    </div>
                  </div>
                )}

                <div className="insights-panel">
                  <span className="eyebrow">ARCHITECTURAL INSIGHTS</span>
                  <ul className="insights-list">
                    {result.insights.map((item, idx) => (
                      <li key={idx}>
                        <span className="insight-bullet">✦</span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </section>

          <section className="toolbar">
            <div className="search-box">
              <span className="search-icon">🔍</span>
              <input
                type="text"
                placeholder="Search modules & files..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>

            <div className="filter-group">
              <span className="filter-label">Language:</span>
              {availableLanguages.map(lang => (
                <button
                  key={lang}
                  className={`chip ${selectedLanguage === lang ? 'active' : ''}`}
                  onClick={() => setSelectedLanguage(lang)}
                >
                  {lang}
                </button>
              ))}
            </div>

            <div className="filter-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={excludeExternal}
                  onChange={e => setExcludeExternal(e.target.checked)}
                />
                <span>Exclude External Packages</span>
              </label>
            </div>

            <div className="action-group">
              <button className="action-btn" onClick={expandAll}>Expand All</button>
              <button className="action-btn" onClick={collapseAll}>Collapse All</button>
            </div>
          </section>


          <section className="workspace">
            <div className="graph">
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodeClick={(_, node) => setSelected(result.nodes.find(item => item.id === node.id) || null)}
                fitView
              >
                <Background color="#294466" gap={20} />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </div>
            <aside>
              <span className="eyebrow">{selected ? selected.language : 'INSPECTOR'}</span>
              <h2>{selected?.label || 'Select a file or module'}</h2>
              <p>{selected?.summary || 'Click any module or file in the graph to inspect its structure and top-level symbols.'}</p>
              {selected?.symbols.map(symbol => (
                <article key={`${symbol.name}-${symbol.line}`}>
                  <b>{symbol.kind}</b>
                  <code>{symbol.name}</code>
                  <small>Line {symbol.line} · {symbol.summary}</small>
                </article>
              ))}
            </aside>
          </section>
        </>
      )}
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<App />)

