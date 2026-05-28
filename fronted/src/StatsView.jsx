import { useState, useEffect } from 'react'

const META = {
  followers: {
    table:  'followers (VIEW)',
    desc:   'Official Instagram follower export — every account currently following this profile, with exact follow timestamp.',
    fields: ['username VARCHAR', 'followed_at TIMESTAMP'],
    joins:  ['JOIN likers ON username', 'JOIN comments ON username'],
    query:  'Who followed me and also commented on my posts?',
  },
  posts: {
    table:  'posts',
    desc:   'Deduplicated post metadata — shortcode, caption, media type, and ISO posting date normalised to a queryable TIMESTAMP.',
    fields: ['post_shortcode VARCHAR (PK)', 'posted_at VARCHAR', 'posted_at_ts TIMESTAMP'],
    joins:  ['JOIN likers ON post_shortcode', 'JOIN comments ON post_shortcode'],
    query:  'Which posts got the most engagement in 2025?',
  },
  likers: {
    table:  'likers',
    desc:   'Every like interaction — maps posts to the users who liked them. Join with followers to measure follower engagement rate.',
    fields: ['post_shortcode VARCHAR (FK)', 'username VARCHAR'],
    joins:  ['JOIN posts ON post_shortcode', 'JOIN followers ON username'],
    query:  'What percentage of my followers have liked at least one post?',
  },
  comments: {
    table:  'comments',
    desc:   'All comments with full text, author handle, and normalised timestamp ready for date-range filtering.',
    fields: ['post_shortcode VARCHAR (FK)', 'username VARCHAR', 'comment TEXT', 'commented_at TIMESTAMP'],
    joins:  ['JOIN posts ON post_shortcode', 'JOIN followers ON username'],
    query:  'Who are my top 10 most active commenters?',
  },
}

function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const n = typeof target === 'number' && target > 0 ? target : null
    if (n === null) return
    let start = null
    let raf
    const step = (ts) => {
      if (!start) start = ts
      const p = Math.min((ts - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3) // ease-out-cubic
      setDisplay(Math.floor(eased * n))
      if (p < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return typeof target === 'number' ? display : target
}

function TotalCount({ value }) {
  const counted = useCountUp(value, 1400)
  return <span className="stats-total-val">{counted.toLocaleString()}</span>
}

function BentoCard({ k, i, isOpen, onToggle }) {
  const counted = useCountUp(
    typeof k.value === 'number' ? k.value : 0,
    900 + i * 180
  )
  const displayVal = typeof k.value === 'number'
    ? counted.toLocaleString()
    : (k.value ?? '—')

  return (
    <div
      className={`bento-card ${isOpen ? 'open' : ''}`}
      style={{ '--ba': k.accent, animationDelay: `${i * 0.08}s` }}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onToggle()}
    >
      <div className="bento-glow" />
      <div className="bento-inner">
        <div className="bento-row-top">
          <span className="bento-label">{k.label}</span>
          <span className={`bento-arrow ${isOpen ? 'up' : ''}`}>↗</span>
        </div>
        <div className="bento-val">{displayVal}</div>
      </div>
    </div>
  )
}

export default function StatsView({ stats, onQuerySuggestion }) {
  const [expanded, setExpanded] = useState(null)

  const kpis = [
    { id: 'followers', label: 'Total Followers', value: stats.followers ?? '—', accent: '#6366f1' },
    { id: 'posts',     label: 'Indexed Posts',   value: stats.posts     ?? '—', accent: '#14b8a6' },
    { id: 'likers',    label: 'Active Likers',   value: stats.likers    ?? '—', accent: '#a855f7' },
    { id: 'comments',  label: 'Comments',        value: stats.comments  ?? '—', accent: '#f59e0b' },
  ]

  const allNumeric = kpis.every(k => typeof k.value === 'number')
  const total = allNumeric ? kpis.reduce((sum, k) => sum + k.value, 0) : null

  const active = kpis.find(k => k.id === expanded)
  const meta   = expanded ? META[expanded] : null

  return (
    <div className="stats-view">

      {/* ── Cinematic Hero ── */}
      <div className="stats-hero">
        <div className="stats-hero-eyebrow">
          <span className="stats-hero-dot" />
          <span>DATA INTELLIGENCE · LIVE SCHEMA</span>
        </div>
        <h2 className="stats-hero-title">
          Your Data,{' '}
          <span className="stats-hero-gradient">Decoded</span>
        </h2>
        {total !== null && (
          <div className="stats-total-row">
            <TotalCount value={total} />
            <span className="stats-total-label">total indexed records across all tables</span>
          </div>
        )}
        <p className="stats-hero-sub">
          Live metrics from your DuckDB instance · click any card to inspect the schema
        </p>
      </div>

      {/* ── KPI Grid ── */}
      <div className="bento-grid">
        {kpis.map((k, i) => (
          <BentoCard
            key={k.id}
            k={k}
            i={i}
            isOpen={expanded === k.id}
            onToggle={() => setExpanded(prev => prev === k.id ? null : k.id)}
          />
        ))}
      </div>

      {/* ── Expanded Schema Panel ── */}
      {active && meta && (
        <div key={active.id} className="bento-panel" style={{ '--ba': active.accent }}>
          <div className="bento-panel-glow" />
          <div className="bento-panel-head">
            <div>
              <span className="bento-panel-table">{meta.table}</span>
              <p className="bento-panel-desc">{meta.desc}</p>
            </div>
            <button className="bento-panel-close" onClick={() => setExpanded(null)}>✕</button>
          </div>

          <div className="bento-panel-body">
            <div className="bento-panel-col">
              <div className="bento-panel-col-label">Schema</div>
              <div className="bento-chip-list">
                {meta.fields.map(f => <span key={f} className="schema-chip">{f}</span>)}
              </div>
            </div>
            <div className="bento-panel-col">
              <div className="bento-panel-col-label">Join Relationships</div>
              <div className="bento-chip-list">
                {meta.joins.map(j => <span key={j} className="join-chip">{j}</span>)}
              </div>
            </div>
          </div>

          {onQuerySuggestion && (
            <button
              className="bento-query-btn"
              onClick={() => { onQuerySuggestion(meta.query); setExpanded(null) }}
            >
              <span>Try: "{meta.query}"</span>
              <span className="bqb-arrow">→</span>
            </button>
          )}
        </div>
      )}

    </div>
  )
}
