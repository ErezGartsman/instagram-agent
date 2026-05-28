import { useState } from 'react'

const NODES = [
  {
    id:    'source',
    title: 'Data Sources',
    sub:   'Instagram Export',
    color: '#e1306c',
    stat:  'Input Layer',
    tags:  ['JSON', 'CSV'],
    desc:  'Raw follower data and engagement CSVs exported from Instagram\'s official data portal and scrapers. Loaded once via DuckDB\'s read_json_auto — zero preprocessing required.',
    icon:  (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="2" width="20" height="20" rx="5"/>
        <circle cx="12" cy="12" r="4"/>
        <circle cx="17.5" cy="6.5" r="1.5" fill="currentColor" stroke="none"/>
      </svg>
    ),
  },
  {
    id:    'duckdb',
    title: 'DuckDB',
    sub:   'OLAP · In-Process',
    color: '#14b8a6',
    stat:  'Query Engine',
    tags:  ['SQL Engine', 'Columnar', 'read_json_auto'],
    desc:  'Embeddable OLAP engine running in-process with the API. JSON and CSV files are exposed as relational views and queried with sub-millisecond latency — no server, no ETL.',
    icon:  (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3"/>
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
      </svg>
    ),
  },
  {
    id:    'fastapi',
    title: 'FastAPI',
    sub:   'Python · Async',
    color: '#6366f1',
    stat:  'API Gateway',
    tags:  ['REST', 'Rate Limit', 'LRU Cache'],
    desc:  'Async Python backend orchestrating the NL→SQL pipeline. Validates generated SQL, enforces per-IP rate limits, and serves LRU-cached results to minimize latency on repeated queries.',
    icon:  (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
      </svg>
    ),
  },
  {
    id:    'gemini',
    title: 'Gemini 2.5',
    sub:   'Google AI · LLM',
    color: '#a855f7',
    stat:  'AI Core',
    tags:  ['NL→SQL', 'JSON Output', 'Flash'],
    desc:  'Converts natural language questions in Hebrew or English into precise DuckDB SQL via structured prompt engineering. Returns validated JSON with query, explanation, and chart config.',
    icon:  (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z"/>
      </svg>
    ),
  },
  {
    id:    'ui',
    title: 'Nexus UI',
    sub:   'React 19 + Vite',
    color: '#f59e0b',
    stat:  'Interface',
    tags:  ['Chat', 'Recharts', 'Dashboard'],
    desc:  'Premium React SPA with AI chat, live data tables, animated chart visualisations, pinned insights dashboard, and one-click CSV export. Glass-terminal aesthetic with cinematic micro-interactions.',
    icon:  (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/>
        <path d="M8 21h8M12 17v4"/>
      </svg>
    ),
  },
]

const IS_BIDIR = [false, false, true, false]

const HERO_METRICS = [
  { label: 'Pipeline Nodes', value: '5' },
  { label: 'Avg Latency',    value: '<1ms' },
  { label: 'SQL Engine',     value: 'DuckDB' },
  { label: 'AI Model',       value: 'Gemini 2.5' },
  { label: 'Transport',      value: 'REST · JSON' },
]

function Connector({ fromColor, toColor, bidir, index }) {
  const delays = bidir
    ? [0, 0.55, 1.1, 0.28, 0.83]
    : [0, 0.6, 1.2]
  return (
    <div className="arch-conn">
      <div
        className="arch-conn-line"
        style={{ background: `linear-gradient(90deg, ${fromColor}66, ${toColor}66)` }}
      />
      {[0, 1, 2].map(j => (
        <span
          key={j}
          className="arch-pulse"
          style={{ '--pc': toColor, animationDelay: `${index * 0.35 + delays[j]}s` }}
        />
      ))}
      {bidir && [0, 1].map(j => (
        <span
          key={`r${j}`}
          className="arch-pulse reverse"
          style={{ '--pc': fromColor, animationDelay: `${index * 0.35 + delays[3 + j]}s` }}
        />
      ))}
      <span className="arch-conn-arrow" style={{ color: `${toColor}bb` }}>›</span>
      {bidir && <span className="arch-conn-arrow left" style={{ color: `${fromColor}bb` }}>‹</span>}
    </div>
  )
}

function ArchNode({ node, index, isSelected, onSelect }) {
  return (
    <div
      className={`arch-node ${isSelected ? 'active' : ''}`}
      style={{ '--nc': node.color, animationDelay: `${index * 0.12}s` }}
      onClick={() => onSelect(node.id)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(node.id)}
    >
      <div className="arch-node-glow" />
      <div className="arch-node-stat">
        <span className="arch-node-stat-dot" />
        <span className="arch-node-stat-text">{node.stat}</span>
      </div>
      <div className="arch-node-orb">
        <div className="arch-node-icon">{node.icon}</div>
      </div>
      <div className="arch-node-title">{node.title}</div>
      <div className="arch-node-sub">{node.sub}</div>
      <div className="arch-node-tags">
        {node.tags.map(t => <span key={t} className="arch-tag">{t}</span>)}
      </div>
    </div>
  )
}

export default function ArchView() {
  const [selected, setSelected] = useState(null)
  const activeNode = NODES.find(n => n.id === selected)

  const handleSelect = (id) => {
    setSelected(prev => prev === id ? null : id)
  }

  return (
    <div className="arch-view">

      {/* ── Cinematic Hero ── */}
      <div className="arch-hero">
        <div className="arch-hero-eyebrow">
          <span className="arch-live-dot" />
          <span className="arch-header-label">LIVE · PIPELINE ARCHITECTURE</span>
        </div>
        <h2 className="arch-hero-title">
          Intelligence <span className="arch-hero-accent">Engine</span>
        </h2>
        <div className="arch-hero-metrics">
          {HERO_METRICS.map(m => (
            <div key={m.label} className="arch-metric-item">
              <span className="arch-metric-val">{m.value}</span>
              <span className="arch-metric-label">{m.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Pipeline ── */}
      <div className="arch-pipeline-wrap">
        <div className="arch-pipeline">
          {NODES.map((node, i) => (
            <div key={node.id} className="arch-segment">
              <ArchNode
                node={node}
                index={i}
                isSelected={selected === node.id}
                onSelect={handleSelect}
              />
              {i < NODES.length - 1 && (
                <Connector
                  fromColor={node.color}
                  toColor={NODES[i + 1].color}
                  bidir={IS_BIDIR[i]}
                  index={i}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Selected Node Detail ── */}
      {activeNode && (
        <div key={activeNode.id} className="arch-detail-panel" style={{ '--nc': activeNode.color }}>
          <div className="arch-detail-glow" />
          <div className="arch-detail-head">
            <div className="arch-detail-orb">
              <div className="arch-node-icon">{activeNode.icon}</div>
            </div>
            <div className="arch-detail-info">
              <div className="arch-detail-title">{activeNode.title}</div>
              <div className="arch-detail-sub">{activeNode.sub}</div>
            </div>
            <button
              className="arch-detail-close"
              onClick={() => setSelected(null)}
              aria-label="Close panel"
            >✕</button>
          </div>
          <p className="arch-detail-desc">{activeNode.desc}</p>
          <div className="arch-detail-tags">
            {activeNode.tags.map(t => (
              <span key={t} className="arch-detail-tag">{t}</span>
            ))}
          </div>
        </div>
      )}

    </div>
  )
}
