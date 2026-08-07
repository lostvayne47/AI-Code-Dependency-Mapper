import React, { useCallback, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ReactFlow, { Background, Controls, MiniMap, type Edge, type Node } from 'reactflow'
import 'reactflow/dist/style.css'
import './styles.css'

type SymbolInfo = { name: string; kind: string; line: number; summary: string }
type AnalysisNode = { id: string; label: string; language: string; summary: string; symbols: SymbolInfo[] }
type Result = { nodes: AnalysisNode[]; edges: { source: string; target: string; kind: string }[]; overview: string; insights: string[] }

const demoFiles = [
  { path: 'src/main.py', content: 'from services.report import build_report\n\ndef run():\n    return build_report()\n' },
  { path: 'src/services/report.py', content: 'from models.user import User\n\ndef build_report():\n    return User()\n' },
  { path: 'src/models/user.py', content: 'class User:\n    def __init__(self):\n        self.name = "Visitor"\n' },
]

function App() {
  const [result, setResult] = useState<Result | null>(null)
  const [selected, setSelected] = useState<AnalysisNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const analyze = useCallback(async (files: { path: string; content: string }[]) => {
    setLoading(true); setError(''); setSelected(null)
    try {
      const response = await fetch('http://localhost:8000/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files }) })
      if (!response.ok) throw new Error((await response.json()).detail || 'Analysis failed')
      setResult(await response.json())
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not reach the analysis service.') }
    finally { setLoading(false) }
  }, [])
  const onPick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = await Promise.all(Array.from(event.target.files || []).filter(f => /\.(py|js|jsx|ts|tsx|json)$/i.test(f.name)).map(async f => ({ path: (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name, content: await f.text() })))
    if (files.length) analyze(files); else setError('Choose a folder containing Python, JavaScript, TypeScript, or JSON files.')
  }
  const flowNodes: Node[] = useMemo(() => (result?.nodes || []).map((node, i) => ({ id: node.id, data: { label: <><strong>{node.label}</strong><small>{node.language} · {node.symbols.length} symbols</small></> }, position: { x: 80 + (i % 3) * 270, y: 80 + Math.floor(i / 3) * 160 }, style: { border: '1px solid #31517d', borderRadius: 10, background: '#13233b', color: '#eaf2ff', padding: 12, minWidth: 180 } })), [result])
  const flowEdges: Edge[] = useMemo(() => (result?.edges || []).map((edge, i) => ({ id: `${edge.source}-${edge.target}-${i}`, source: edge.source, target: edge.target, animated: true, style: { stroke: '#65b8ff' } })), [result])
  return <main>
    <header><div><span className="eyebrow">CODE INTELLIGENCE</span><h1>Architecture at a glance.</h1><p>Map dependencies and turn unfamiliar source into an understandable system.</p></div><button onClick={() => analyze(demoFiles)} disabled={loading}>{loading ? 'Analyzing…' : 'Try demo'}</button></header>
    <section className="dropzone"><label><input type="file" ref={input => input?.setAttribute('webkitdirectory', '')} multiple onChange={onPick} /><span>Choose a project folder</span><small>Source stays in your browser until you start analysis.</small></label>{error && <p className="error">{error}</p>}</section>
    {result && <><section className="overview"><div><span className="eyebrow">PROJECT OVERVIEW</span><h2>{result.overview}</h2></div><ul>{result.insights.map(item => <li key={item}>{item}</li>)}</ul></section>
    <section className="workspace"><div className="graph"><ReactFlow nodes={flowNodes} edges={flowEdges} onNodeClick={(_, node) => setSelected(result.nodes.find(item => item.id === node.id) || null)} fitView><Background color="#294466" gap={20}/><MiniMap /><Controls /></ReactFlow></div><aside><span className="eyebrow">{selected ? selected.language : 'FILE EXPLORER'}</span><h2>{selected?.label || 'Select a file'}</h2><p>{selected?.summary || 'Click a module in the dependency map to inspect its public structure.'}</p>{selected?.symbols.map(symbol => <article key={`${symbol.name}-${symbol.line}`}><b>{symbol.kind}</b><code>{symbol.name}</code><small>Line {symbol.line} · {symbol.summary}</small></article>)}</aside></section></>}
  </main>
}
createRoot(document.getElementById('root')!).render(<App />)
