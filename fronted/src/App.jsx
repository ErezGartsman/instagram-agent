import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import './App.css'
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'
import StatsView from './StatsView'
import ArchView  from './ArchView'

// In dev: defaults to localhost:8000 if VITE_API_BASE / VITE_API_URL is not set.
// In production: set VITE_API_BASE=https://your-backend.vercel.app in Vercel env vars.
//
// Normalisation: some env var editors (including Vercel's dashboard) occasionally
// save "https://" as "https:/" (one slash).  A single-slash URL is treated as a
// relative path by the browser, so fetch() prepends the current origin and the
// request goes to the wrong server entirely.  The replace() below re-inserts the
// missing slash before any downstream code can observe the malformed value.
const API_BASE = (
  import.meta.env.VITE_API_BASE ??
  import.meta.env.VITE_API_URL  ??
  'http://localhost:8000'
)
  .trim()
  .replace(/\/$/, '')                          // strip accidental trailing slash
  .replace(/^(https?):\/(?!\/)/, '$1://')      // fix https:/ → https://

const FALLBACK_SESSION_ID = crypto.randomUUID()

// Pure utility — no component state needed, safe at module scope.
const getTimestamp = () =>
  new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })


// ─── Icons ────────────────────────────────────────────────────────────────────
const Icon = ({ name, size = 18 }) => {
  const icons = {
    query:    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
    analytics:<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
    arch:     <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="6" height="6" rx="1"/><rect x="16" y="3" width="6" height="6" rx="1"/><rect x="9" y="15" width="6" height="6" rx="1"/><path d="M5 9v3h14V9M12 12v3"/></svg>,
    schema:   <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
    send:     <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
    code:     <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>,
    chevron:  <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
    copy:     <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
    check:    <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
    logo:     <svg width={size} height={size} viewBox="0 0 28 28" fill="none"><rect x="2" y="2" width="11" height="11" rx="2.5" fill="currentColor"/><rect x="15" y="2" width="11" height="11" rx="2.5" fill="currentColor" opacity="0.35"/><rect x="2" y="15" width="11" height="11" rx="2.5" fill="currentColor" opacity="0.35"/><rect x="15" y="15" width="11" height="11" rx="2.5" fill="currentColor"/></svg>,
    download: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
    retry:    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>,
    trash:    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
    plus:     <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
    bar:      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="10" width="4" height="11" rx="1"/><rect x="10" y="5" width="4" height="16" rx="1"/><rect x="17" y="14" width="4" height="7" rx="1"/></svg>,
    sparkle:   <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z"/></svg>,
    dashboard: <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
    pin:       <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 17v5"/><path d="M5 17h14"/><path d="M15 5a3 3 0 0 1-6 0V3h6v2z"/><path d="M9 5H5v6l3 3h8l3-3V5h-4"/></svg>,
    pinned:    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="0.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 17v5"/><path d="M5 17h14"/><path d="M15 5a3 3 0 0 1-6 0V3h6v2z"/><path d="M9 5H5v6l3 3h8l3-3V5h-4"/></svg>,
    more:      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg>,
    menu:      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>,
    share:     <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>,
    pen:       <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  }
  return icons[name] || null
}

// ─── Living Background — 3 slow-drifting colour orbs ─────────────────────────
// loading=true: orbs accelerate + intensify, making the background a reactive
// nervous system that registers the query is in flight.
const LivingBg = ({ loading = false }) => (
  <div className={`living-bg${loading ? ' loading' : ''}`} aria-hidden="true">
    <div className="orb orb-1"/>
    <div className="orb orb-2"/>
    <div className="orb orb-3"/>
  </div>
)

// ─── Toast System ─────────────────────────────────────────────────────────────
const ToastContainer = ({ toasts }) => (
  <div className="toast-container" aria-live="polite">
    {toasts.map(t => (
      <div key={t.id} className={`toast toast-${t.type}`}>
        <span className="toast-dot"/>
        {t.msg}
      </div>
    ))}
  </div>
)

// ─── Pipeline Bar ─────────────────────────────────────────────────────────────
const PipelineBar = ({ stage, dbStatus }) => {
  const steps = [
    { id: 'nl',   label: 'NL Parse' },
    { id: 'sql',  label: 'SQL Gen'  },
    { id: 'db',   label: 'Supabase' },
    { id: 'done', label: 'Synthesis'},
  ]
  const order = ['nl', 'sql', 'db', 'done']
  const activeIdx = stage ? order.indexOf(stage) : -1

  return (
    <div className={`pipeline-bar${stage === 'done' ? ' done' : ''}`}>
      <div className="pipeline-steps">
        {steps.map((s, i) => (
          <div key={s.id} className="pipeline-item">
            <div className={`pipeline-node ${i < activeIdx ? 'done' : ''} ${i === activeIdx ? 'active' : ''}`}>
              {i < activeIdx ? <Icon name="check" size={10}/> : <span>{i + 1}</span>}
            </div>
            <span className={`pipeline-lbl ${i === activeIdx ? 'active' : i < activeIdx ? 'done' : ''}`}>{s.label}</span>
            {i < steps.length - 1 && <div className={`pipe-connector ${i < activeIdx ? 'done' : ''} ${i === activeIdx ? 'active' : ''}`}/>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── SQL Typer Hook ───────────────────────────────────────────────────────────
// Distinct from useTypewriter: resets to '' when inactive so re-opening
// always starts from the beginning rather than flashing the full text.
// Types 2 chars per tick at 2ms intervals → ~1ms/char effective speed.
const useSqlTyper = (sql, active) => {
  const [displayed, setDisplayed] = useState('')
  useEffect(() => {
    if (!active) {
      setDisplayed('')   // reset so next open starts fresh, not with stale text
      return
    }
    let i = 0
    let timer
    setDisplayed('')
    const tick = () => {
      i = Math.min(i + 2, sql.length)
      setDisplayed(sql.slice(0, i))
      if (i < sql.length) timer = setTimeout(tick, 2)
    }
    timer = setTimeout(tick, 0)
    return () => clearTimeout(timer)
  }, [sql, active])
  return displayed
}

// ─── SQL Block ────────────────────────────────────────────────────────────────
const SqlBlock = ({ sql, onRerunSql }) => {
  const [open,      setOpen]      = useState(false)
  const [copied,    setCopied]    = useState(false)
  const [editing,   setEditing]   = useState(false)
  const [editedSql, setEditedSql] = useState(sql)
  const [running,   setRunning]   = useState(false)
  const editorRef = useRef(null)

  // Typing effect only runs when open AND not in edit mode
  const displayed = useSqlTyper(sql, open && !editing)
  const isDone    = displayed.length >= sql.length

  const copy = () => {
    navigator.clipboard.writeText(editing ? editedSql : sql).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const startEdit = () => {
    setEditedSql(sql)
    setEditing(true)
    setTimeout(() => editorRef.current?.focus(), 0)
  }

  const cancelEdit = () => {
    setEditing(false)
    setEditedSql(sql)
  }

  const handleRerun = async () => {
    if (!onRerunSql || !editedSql.trim() || running) return
    setRunning(true)
    setEditing(false)
    setOpen(false)
    try {
      await onRerunSql(editedSql.trim())
    } finally {
      setRunning(false)
    }
  }

  const handleToggle = () => {
    setOpen(o => !o)
    if (editing) { setEditing(false); setEditedSql(sql) }
  }

  return (
    <div className={`sql-block ${open ? 'open' : ''}`}>
      <button className="sql-toggle" onClick={handleToggle}>
        <Icon name="code" size={12}/>
        <span>{open ? 'Hide' : 'View'} generated SQL</span>
        <span className={`sql-chevron ${open ? 'flipped' : ''}`}><Icon name="chevron"/></span>
      </button>
      {open && (
        <div className="sql-body">
          <div className="sql-toolbar">
            <button className="copy-btn" onClick={copy}>
              {copied ? <Icon name="check" size={13}/> : <Icon name="copy" size={13}/>}
              <span>{copied ? 'Copied!' : 'Copy'}</span>
            </button>
            {onRerunSql && !editing && (
              <button className="sql-edit-btn" onClick={startEdit}>
                <Icon name="pen" size={11}/>
                <span>Edit SQL</span>
              </button>
            )}
          </div>
          {editing ? (
            <div className="sql-editor-wrap">
              <textarea
                ref={editorRef}
                className="sql-editor"
                value={editedSql}
                onChange={e => setEditedSql(e.target.value)}
                spellCheck={false}
                rows={Math.max(4, editedSql.split('\n').length + 1)}
              />
              <div className="sql-editor-actions">
                <button className="sql-cancel-btn" onClick={cancelEdit}>Cancel</button>
                <button
                  className="sql-rerun-btn"
                  onClick={handleRerun}
                  disabled={running || !editedSql.trim()}
                >
                  {running
                    ? <span className="spinner" style={{ width: 12, height: 12 }}/>
                    : <Icon name="send" size={12}/>
                  }
                  <span>Re-run Query</span>
                </button>
              </div>
            </div>
          ) : (
            <pre className="sql-code">
              {displayed}
              {!isDone && <span className="sql-cursor" aria-hidden="true"/>}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Chart ────────────────────────────────────────────────────────────────────
const CHART_COLORS = ['#4F7EFF', '#00D4AA', '#9D6EFF', '#F5A742', '#FF6B9D', '#22d3ee']

const isYearKey = (key) => /year|שנה/i.test(String(key ?? ''))

const fmtNum = (v, key) => {
  if (v == null) return '—'
  const n = Number(v)
  if (!isFinite(n)) return String(v)
  if (isYearKey(key) && Number.isInteger(n) && n >= 1000 && n <= 9999) return String(n)
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

// ─── Date Normalisation ───────────────────────────────────────────────────────
// Matches ISO dates (YYYY-MM-DD) — parseFloat("2025-01-15") returns 2025, so
// dates must be identified BEFORE the isNum check to avoid numeric misclassification.
const _ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const _DMY_DATE_RE = /^\d{2}\/\d{2}\/\d{4}$/

// Returns { display, isDate } for a raw cell value, or null if it's not a date.
const tryFmtDate = (cell) => {
  if (cell == null) return null
  const s = String(cell)
  if (_ISO_DATE_RE.test(s)) {
    const [y, m, d] = s.split('-')
    return { display: `${d}/${m}/${y}`, isDate: true }
  }
  if (_DMY_DATE_RE.test(s)) return { display: s, isDate: true }
  return null
}

function detectChartData(columns, rawResults) {
  if (!columns || !rawResults || rawResults.length < 2 || columns.length < 2) return null

  const numericMask = columns.map((_, ci) => {
    const vals = rawResults.map(r => r[ci]).filter(v => v !== null && v !== undefined && v !== '')
    return vals.length > 0 && vals.every(v => !isNaN(parseFloat(v)) && isFinite(v))
  })

  const firstNonNumeric = numericMask.findIndex(n => !n)
  const labelIdx = firstNonNumeric !== -1 ? firstNonNumeric : 0

  const valueCols = columns
    .map((col, ci) => ({ col, ci }))
    .filter(({ ci }) => numericMask[ci] && ci !== labelIdx)

  if (valueCols.length === 0) return null

  const chartData = rawResults.slice(0, 20).map(row => {
    const label = String(row[labelIdx] ?? '').slice(0, 22)
    const entry = { label }
    valueCols.forEach(({ col, ci }) => {
      entry[col] = row[ci] !== null ? parseFloat(row[ci]) : null
    })
    return entry
  })

  const firstLabel = chartData[0]?.label ?? ''
  const isTimeSeries =
    (/\d{4}/.test(firstLabel) || /(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(firstLabel)) &&
    rawResults.length >= 3

  return { data: chartData, keys: valueCols.map(v => v.col), chartType: isTimeSeries ? 'line' : 'bar' }
}

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="chart-tooltip-row" style={{ color: p.color }}>
          <span>{p.name}</span>
          <strong>{fmtNum(p.value, p.name)}</strong>
        </div>
      ))}
    </div>
  )
}

const DataChart = ({ columns, rawResults, compact = false }) => {
  const cfg = useMemo(() => detectChartData(columns, rawResults), [columns, rawResults])
  if (!cfg) return null
  const { data, keys, chartType } = cfg
  const isSingleKey = keys.length === 1
  const axisStyle = { fill: '#4A5568', fontSize: compact ? 8 : 9, fontFamily: 'JetBrains Mono, monospace' }

  if (compact) {
    return (
      <div style={{ width: '100%', height: 190 }}>
        <ResponsiveContainer width="100%" height="100%">
          {chartType === 'line' ? (
            <LineChart data={data} margin={{ top: 6, right: 8, bottom: 36, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false}/>
              <XAxis dataKey="label" tick={axisStyle} angle={-30} textAnchor="end" height={36} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
              <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => fmtNum(v, keys.find(isYearKey) ?? keys[0])}/>
              <Tooltip content={<ChartTooltip/>} cursor={{ stroke: 'rgba(255,255,255,0.06)', strokeWidth: 1 }}/>
              {keys.map((key, i) => (
                <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive={true} animationDuration={700} animationEasing="ease-out"/>
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 6, right: 8, bottom: 36, left: -16 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false}/>
              <XAxis dataKey="label" tick={axisStyle} angle={-30} textAnchor="end" height={36} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
              <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => fmtNum(v, keys.find(isYearKey) ?? keys[0])}/>
              <Tooltip content={<ChartTooltip/>} cursor={{ fill: 'rgba(255,255,255,0.03)' }}/>
              {keys.map((key, i) => (
                <Bar key={key} dataKey={key} radius={[3, 3, 0, 0]} maxBarSize={40} fill={isSingleKey ? undefined : CHART_COLORS[i % CHART_COLORS.length]} isAnimationActive={true} animationDuration={500} animationEasing="ease-out">
                  {isSingleKey && data.map((_, di) => (
                    <Cell key={di} fill={CHART_COLORS[di % CHART_COLORS.length]}/>
                  ))}
                </Bar>
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    )
  }

  const chartWidth = Math.max(500, data.length * 60)
  return (
    <div className="inline-chart">
      <div className="inline-chart-label">
        <Icon name={chartType === 'line' ? 'analytics' : 'bar'} size={11}/>
        <span>
          {chartType === 'line' ? 'Trend' : 'Distribution'} · {rawResults.length} rows
          {rawResults.length > 20 ? ' (top 20 shown)' : ''}
        </span>
      </div>
      <div className="chart-scroll-wrapper">
        <div style={{ minWidth: chartWidth, height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            {chartType === 'line' ? (
              <LineChart data={data} margin={{ top: 6, right: 16, bottom: 60, left: -10 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false}/>
                <XAxis dataKey="label" tick={{ ...axisStyle, fontSize: 9 }} angle={-40} textAnchor="end" height={60} axisLine={false} tickLine={false} interval={0}/>
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={52} tickFormatter={(v) => fmtNum(v, keys.find(isYearKey) ?? keys[0])}/>
                <Tooltip content={<ChartTooltip/>} cursor={{ stroke: 'rgba(255,255,255,0.06)', strokeWidth: 1 }}/>
                {keys.map((key, i) => (
                  <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 0, fill: CHART_COLORS[i % CHART_COLORS.length] }} activeDot={{ r: 5, strokeWidth: 0 }} isAnimationActive={true} animationDuration={700} animationEasing="ease-out"/>
                ))}
              </LineChart>
            ) : (
              <BarChart data={data} margin={{ top: 6, right: 16, bottom: 60, left: -10 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false}/>
                <XAxis dataKey="label" tick={{ ...axisStyle, fontSize: 9 }} angle={-40} textAnchor="end" height={60} axisLine={false} tickLine={false} interval={0}/>
                <YAxis tick={axisStyle} axisLine={false} tickLine={false} width={52} tickFormatter={(v) => fmtNum(v, keys.find(isYearKey) ?? keys[0])}/>
                <Tooltip content={<ChartTooltip/>} cursor={{ fill: 'rgba(255,255,255,0.03)' }}/>
                {keys.map((key, i) => (
                  <Bar key={key} dataKey={key} radius={[4, 4, 0, 0]} maxBarSize={52} fill={isSingleKey ? undefined : CHART_COLORS[i % CHART_COLORS.length]} isAnimationActive={true} animationDuration={500} animationEasing="ease-out">
                    {isSingleKey && data.map((_, di) => (
                      <Cell key={di} fill={CHART_COLORS[di % CHART_COLORS.length]}/>
                    ))}
                  </Bar>
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

// ─── Data Table ───────────────────────────────────────────────────────────────
const DataTable = ({ columns, rawResults }) => {
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')

  const handleSort = (ci) => {
    if (sortCol === ci) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(ci)
      setSortDir('asc')
    }
  }

  const sorted = useMemo(() => {
    if (sortCol === null) return rawResults
    return [...rawResults].sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol]
      const an = parseFloat(av), bn = parseFloat(bv)
      if (!isNaN(an) && !isNaN(bn)) return sortDir === 'asc' ? an - bn : bn - an
      const as = String(av ?? ''), bs = String(bv ?? '')
      return sortDir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as)
    })
  }, [rawResults, sortCol, sortDir])

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col, ci) => (
              <th
                key={ci}
                className={sortCol === ci ? 'sorted' : ''}
                onClick={() => handleSort(ci)}
              >
                <span className="th-inner">
                  {col.replace(/_/g, ' ')}
                  <span className="sort-icon">
                    {sortCol === ci ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}
                  </span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, ri) => (
            <tr key={ri} className="data-row" style={{ animationDelay: `${Math.min(ri, 20) * 12}ms` }}>
              {row.map((cell, ci) => {
                // Date check must come first: parseFloat("2025-01-15") = 2025,
                // which would incorrectly pass the isNum test below.
                const dated = tryFmtDate(cell)
                const isNum = !dated && cell !== null && cell !== undefined && !isNaN(parseFloat(cell)) && isFinite(cell)
                const display = dated?.display ?? (cell != null ? (isNum ? fmtNum(cell, columns[ci]) : String(cell)) : '—')
                return (
                  <td key={ci} className={isNum ? 'num' : ''} title={cell != null ? String(cell) : ''}>
                    {display}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Data View (toggle wrapper) ────────────────────────────────────────────────
const DataView = ({ columns, rawResults, onExport, onPin, isPinned }) => {
  const hasChart = !!useMemo(() => detectChartData(columns, rawResults), [columns, rawResults])
  const [view, setView] = useState(hasChart ? 'chart' : 'table')

  return (
    <div className="data-view">
      {hasChart && (
        <div className="data-toggle">
          <button
            className={`data-toggle-btn ${view === 'chart' ? 'active' : ''}`}
            onClick={() => setView('chart')}
          >
            <Icon name="bar" size={11}/> Chart
          </button>
          <button
            className={`data-toggle-btn ${view === 'table' ? 'active' : ''}`}
            onClick={() => setView('table')}
          >
            <Icon name="schema" size={11}/> Table
          </button>
        </div>
      )}

      {(view === 'chart' && hasChart)
        ? <DataChart columns={columns} rawResults={rawResults}/>
        : <DataTable columns={columns} rawResults={rawResults}/>
      }

      <div className="data-view-foot">
        <button className="export-csv-btn" onClick={() => onExport(columns, rawResults)}>
          <Icon name="download" size={12}/> Export CSV ({rawResults.length} rows)
        </button>
        {onPin && (
          <button
            className={`pin-btn ${isPinned ? 'pinned' : ''}`}
            onClick={onPin}
            title={isPinned ? 'Already pinned to Dashboard' : 'Pin to Dashboard'}
          >
            <Icon name={isPinned ? 'pinned' : 'pin'} size={12}/>
            {isPinned ? 'Pinned' : 'Pin'}
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Typewriter ────────────────────────────────────────────────────────────────
function useTypewriter(text, active) {
  const [displayed, setDisplayed] = useState(active ? '' : (text || ''))
  useEffect(() => {
    if (!active || !text) { setDisplayed(text || ''); return }
    const speed = Math.max(6, Math.min(18, Math.floor(2800 / text.length)))
    setDisplayed('')
    let i = 0
    let timer
    const tick = () => {
      i++
      setDisplayed(text.slice(0, i))
      if (i < text.length) timer = setTimeout(tick, speed)
    }
    timer = setTimeout(tick, speed)
    return () => clearTimeout(timer)
  }, [text, active])
  return displayed
}

const TypewriterText = ({ text, active }) => {
  const displayed = useTypewriter(text, active)
  return <span style={{ whiteSpace: 'pre-wrap' }}>{displayed}</span>
}

// ─── Staged Thinking Indicator ────────────────────────────────────────────────
const THINKING_STAGES = ['Extracting entities', 'Synthesizing SQL', 'Fetching data', 'Composing answer']

const ThinkingBubble = () => {
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    const iv = setInterval(() => setIdx(i => (i + 1) % THINKING_STAGES.length), 1100)
    return () => clearInterval(iv)
  }, [])
  return (
    <div className="msg-bubble bot thinking-staged">
      <span className="thinking-stage-text">{THINKING_STAGES[idx]}</span>
      {/* 4 independent bars — each has its own keyframe, none are in sync */}
      <span className="scanner-bar-row">
        <span className="scanner-bar"/>
        <span className="scanner-bar"/>
        <span className="scanner-bar"/>
        <span className="scanner-bar"/>
      </span>
    </div>
  )
}

// ─── Message ──────────────────────────────────────────────────────────────────
const Message = ({ msg, onRetry, onExport, onPin, isPinned, onRerunSql }) => {
  if (msg.sender === 'user') {
    return (
      <div className="msg-row user">
        <div className="msg-bubble-wrapper-user">
          <div className="msg-bubble user" dir="auto">{msg.text}</div>
          {msg.timestamp && <span className="msg-timestamp">{msg.timestamp}</span>}
        </div>
      </div>
    )
  }
  if (msg.type === 'thinking') {
    return (
      <div className="msg-row bot">
        <div className="bot-avatar"><Icon name="logo" size={14}/></div>
        <ThinkingBubble/>
      </div>
    )
  }

  const showData    = !msg.isError && msg.rawResults?.length >= 1 && msg.columns?.length >= 1
  const animateText = !!msg.fresh && !msg.isError

  return (
    <div className="msg-row bot">
      <div className="bot-avatar"><Icon name="logo" size={14}/></div>
      <div className="msg-content">
        <div className={`msg-bubble bot${msg.isError ? ' error' : ''}`} dir="auto">
          <TypewriterText text={msg.text} active={animateText}/>
        </div>
        {showData && (
          <DataView
            columns={msg.columns}
            rawResults={msg.rawResults}
            onExport={onExport}
            onPin={onPin ? () => onPin({ columns: msg.columns, rawResults: msg.rawResults, question: msg.question }) : undefined}
            isPinned={isPinned}
          />
        )}
        {msg.timestamp && <span className="msg-timestamp">{msg.timestamp}</span>}
        {msg.isError && msg.originalQuestion && (
          <button className="retry-btn" onClick={() => onRetry(msg.originalQuestion)}>
            <Icon name="retry" size={12}/> Try again
          </button>
        )}
        {msg.sql && <SqlBlock sql={msg.sql} onRerunSql={onRerunSql}/>}
      </div>
    </div>
  )
}

// ─── Empty Chat ────────────────────────────────────────────────────────────────
// Suggested-prompt sets are mode-specific: Instagram analytics (English data
// questions) vs. "Ask Erez" consulting (Hebrew, business-facing). The whole
// empty state — headline, subtitle, cards — swaps with the active mode so the
// RAG experience reads like talking to a representative, not a database.
const DATA_SUGGESTIONS = [
  { label: 'Engagement',     icon: 'analytics', color: '79, 126, 255',  q: 'What is the average number of comments per post?' },
  { label: 'Top Commenters', icon: 'query',     color: '0, 212, 170',   q: 'Who are the top 5 users that commented the most?' },
  { label: 'Monthly Likes',  icon: 'bar',       color: '157, 110, 255', q: 'How many likes did we get in February 2026?' },
  { label: 'Post Frequency', icon: 'analytics', color: '245, 167, 66',  q: 'How many posts were published each month?' },
  { label: 'Most Liked',     icon: 'sparkle',   color: '255, 107, 157', q: 'Which post has the most likes?' },
]

const RAG_SUGGESTIONS = [
  { label: 'שירותים', icon: 'schema',  color: '79, 126, 255',  q: 'מה השירותים שלכם?' },
  { label: 'היכרות',  icon: 'sparkle', color: '0, 212, 170',   q: 'מי זה ארז גרצמן?' },
  { label: 'פגישה',   icon: 'query',   color: '157, 110, 255', q: 'איך קובעים פגישת ייעוץ?' },
]

const EmptyChat = ({ onSelect, ragMode }) => {
  const suggestions = ragMode ? RAG_SUGGESTIONS : DATA_SUGGESTIONS
  return (
    <div className="empty-chat">
      <div className="empty-glyph"><Icon name="logo" size={48}/></div>
      {ragMode ? (
        <>
          <h2 className="empty-title" dir="rtl">
            כאן כדי <span className="empty-title-line2">לעזור.</span>
          </h2>
          <p className="empty-sub" dir="rtl">
            שאלו על השירותים, על ארז גרצמן, או על קביעת פגישת ייעוץ — ואשיב לכם ישירות.
          </p>
        </>
      ) : (
        <>
          <h2 className="empty-title">
            Your Instagram data,<br/>
            <span className="empty-title-line2">answered.</span>
          </h2>
          <p className="empty-sub">
            Ask in plain language. Get SQL-precision answers, charts, and exportable data — in seconds.
          </p>
        </>
      )}
      <div className="suggestion-list">
        {suggestions.map((s, i) => (
          <button
            key={i}
            className={`suggestion-card${ragMode ? ' rtl' : ''}`}
            dir={ragMode ? 'rtl' : 'ltr'}
            onClick={() => onSelect(s.q)}
            style={{ '--card-rgb': s.color, animationDelay: `${i * 0.07}s` }}
          >
            <div className="sug-card-top">
              <span className="sug-icon-wrap" style={{ color: `rgb(${s.color})` }}>
                <Icon name={s.icon} size={13}/>
              </span>
              <span className="sug-label">{s.label}</span>
            </div>
            <div className="sug-q">{s.q}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Analytics View ───────────────────────────────────────────────────────────
// Cinematic hero + "containment frame" that makes the Power BI iframe look
// like a live data portal inside a sci-fi command center.
const ANALYTICS_METRICS = [
  { label: 'Engine',    value: 'Power BI'    },
  { label: 'Feed',      value: 'Real-time'   },
  { label: 'Source',    value: 'Instagram'   },
  { label: 'Mode',      value: 'Interactive' },
]

const AnalyticsView = () => {
  const [loaded, setLoaded] = useState(false)
  return (
    <div className="analytics-view">

      {/* ── Cinematic Hero — reuses arch-hero CSS ── */}
      <div className="arch-hero">
        <div className="arch-hero-eyebrow">
          <span className="arch-live-dot"/>
          <span className="arch-header-label">LIVE · POWER BI ANALYTICS</span>
        </div>
        <h2 className="arch-hero-title">
          Data <span className="arch-hero-accent">Observatory</span>
        </h2>
        <div className="arch-hero-metrics">
          {ANALYTICS_METRICS.map(m => (
            <div key={m.label} className="arch-metric-item">
              <span className="arch-metric-val">{m.value}</span>
              <span className="arch-metric-label">{m.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Containment Frame ── */}
      <div className="powerbi-containment">
        <div className="powerbi-frame-glow"/>

        {/* frame header strip */}
        <div className="powerbi-frame-header">
          <span className="powerbi-frame-dot"/>
          <span className="powerbi-frame-label">ANALYTICS PORTAL · LIVE</span>
          <div className="powerbi-frame-status">
            <span
              className="powerbi-status-orb"
              style={{ background: loaded ? '#22c55e' : '#f59e0b',
                       boxShadow: loaded ? '0 0 6px rgba(34,197,94,0.7)' : '0 0 6px rgba(245,158,11,0.6)' }}
            />
            <span>{loaded ? 'Connected' : 'Establishing connection…'}</span>
          </div>
        </div>

        {/* iframe + glass loading overlay */}
        <div className="powerbi-inner">
          {!loaded && (
            <div className="powerbi-loading">
              <span className="scanner-bar-row">
                <span className="scanner-bar"/>
                <span className="scanner-bar"/>
                <span className="scanner-bar"/>
                <span className="scanner-bar"/>
              </span>
              <span className="powerbi-loading-text">Initialising analytics stream…</span>
            </div>
          )}
          <iframe
            title="full_instagram_scraper"
            width="100%"
            height="100%"
            src="https://app.powerbi.com/reportEmbed?reportId=9285f391-757c-46a5-9c5f-e1b3a7c8f8b2&autoAuth=true&ctid=90c49fc4-c9e6-4529-a15a-033c041d510a"
            frameBorder="0"
            allowFullScreen
            onLoad={() => setLoaded(true)}
            style={{ opacity: loaded ? 1 : 0, transition: 'opacity 0.7s ease', display: 'block' }}
          />
        </div>
      </div>

    </div>
  )
}


// ─── Pin Card ─────────────────────────────────────────────────────────────────
// Isolated into its own component so useMemo can cache detectChartData per card.
// Without this, detectChartData ran on every DashboardView re-render for EVERY
// pinned card in the map callback — hooks cannot be called inside .map().
const PinCard = ({ pin, pinIdx, onUnpin, onExport }) => {
  const accent = CARD_ACCENTS[pinIdx % CARD_ACCENTS.length]
  // detectChartData iterates rawResults — memoize so it only re-runs when the
  // underlying data reference changes, not on every parent render cycle.
  const hasChart = !!useMemo(
    () => detectChartData(pin.columns, pin.rawResults),
    [pin.columns, pin.rawResults],
  )
  return (
    <div
      className="pin-card"
      style={{ '--ca': accent, animationDelay: `${pinIdx * 0.06}s` }}
    >
      <div className="pin-card-glow"/>
      <button
        className="pin-unpin-btn"
        onClick={() => onUnpin(pin.id)}
        title="Remove from Dashboard"
        aria-label="Remove from Dashboard"
      >
        <Icon name="trash" size={13}/>
      </button>
      <div className="pin-card-header">
        <span className="pin-card-accent-dot"/>
        <span className="pin-card-title" title={pin.question}>{pin.question}</span>
      </div>
      <div className="pin-card-body">
        {hasChart
          ? <DataChart columns={pin.columns} rawResults={pin.rawResults} compact/>
          : <DataTable columns={pin.columns} rawResults={pin.rawResults}/>
        }
      </div>
      <div className="pin-card-footer">
        <span className="pin-card-meta">
          {pin.rawResults.length} rows · {pin.columns.length} cols
        </span>
        <button className="export-csv-btn pin-csv" onClick={() => onExport(pin.columns, pin.rawResults)}>
          <Icon name="download" size={11}/> CSV
        </button>
      </div>
    </div>
  )
}

// ─── Dashboard View ───────────────────────────────────────────────────────────
// RGB triplets used as CSS custom property --ca so rgba(var(--ca), alpha) works
const CARD_ACCENTS = [
  '79, 126, 255',   // accent blue
  '0, 212, 170',    // teal
  '157, 110, 255',  // purple
  '245, 167, 66',   // amber
  '255, 107, 157',  // pink
  '34, 211, 238',   // cyan
]

const DashboardView = ({ pinnedItems, onUnpin, onExport }) => {
  if (pinnedItems.length === 0) {
    return (
      <div className="view-page">
        {/* Cinematic hero */}
        <div className="arch-hero" style={{ marginBottom: 0 }}>
          <div className="arch-hero-eyebrow">
            <span className="arch-live-dot"/>
            <span className="arch-header-label">PERSONAL WORKSPACE</span>
          </div>
          <h2 className="arch-hero-title">
            Insight <span className="arch-hero-accent">Matrix</span>
          </h2>
        </div>

        {/* Cinematic empty state */}
        <div className="dash-empty">
          <div className="dash-empty-glyph">
            <Icon name="dashboard" size={38}/>
          </div>
          <h3 className="dash-empty-title">
            Nothing pinned <span className="dash-empty-accent">yet</span>
          </h3>
          <p className="dash-empty-sub">
            Pin insights from your conversations to surface them here permanently — as live charts, sortable tables, or both.
          </p>
          <div className="dash-empty-steps">
            <div className="dash-step">
              <div className="dash-step-num">1</div>
              <div className="dash-step-text">Run any query in the <strong>Query</strong> view</div>
            </div>
            <span className="dash-step-arrow">→</span>
            <div className="dash-step">
              <div className="dash-step-num">2</div>
              <div className="dash-step-text">
                Click <span className="dash-empty-hint"><Icon name="pin" size={10}/> Pin</span> on any result
              </div>
            </div>
            <span className="dash-step-arrow">→</span>
            <div className="dash-step">
              <div className="dash-step-num">3</div>
              <div className="dash-step-text">It lives here, persists across sessions</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="view-page">
      <div className="arch-hero" style={{ marginBottom: 4 }}>
        <div className="arch-hero-eyebrow">
          <span className="arch-live-dot"/>
          <span className="arch-header-label">PERSONAL WORKSPACE · LIVE</span>
        </div>
        <h2 className="arch-hero-title">
          Insight <span className="arch-hero-accent">Matrix</span>
        </h2>
        <div className="arch-hero-metrics">
          <div className="arch-metric-item">
            <span className="arch-metric-val">{pinnedItems.length}</span>
            <span className="arch-metric-label">Pinned Insights</span>
          </div>
          <div className="arch-metric-item">
            <span className="arch-metric-val">
              {pinnedItems.reduce((s, p) => s + p.rawResults.length, 0).toLocaleString()}
            </span>
            <span className="arch-metric-label">Total Rows</span>
          </div>
          <div className="arch-metric-item">
            <span className="arch-metric-val">Persistent</span>
            <span className="arch-metric-label">Storage</span>
          </div>
        </div>
      </div>

      <div className="pin-grid">
        {pinnedItems.map((pin, pinIdx) => (
          <PinCard
            key={pin.id}
            pin={pin}
            pinIdx={pinIdx}
            onUnpin={onUnpin}
            onExport={onExport}
          />
        ))}
      </div>
    </div>
  )
}

// ─── Session Context Menu ─────────────────────────────────────────────────────
const SessionContextMenu = ({ onRename, onDelete, onClose }) => {
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div className="session-menu" ref={ref}>
      <button className="session-menu-item" onClick={onRename}>
        <Icon name="pen" size={12}/> Rename
      </button>
      <button className="session-menu-item danger" onClick={onDelete}>
        <Icon name="trash" size={12}/> Delete
      </button>
    </div>
  )
}

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [sessions, setSessions] = useState(() => {
    try {
      const saved = localStorage.getItem('nexus_sessions')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) return parsed
      }
    } catch {}
    return [{ id: FALLBACK_SESSION_ID, title: 'New Chat', messages: [], backendSessionId: null }]
  })

  const [activeSessionId, setActiveSessionId] = useState(() => {
    try {
      const savedId      = localStorage.getItem('nexus_active_session')
      const rawSessions  = localStorage.getItem('nexus_sessions')
      if (savedId && rawSessions) {
        const parsed = JSON.parse(rawSessions)
        // Only honour the saved ID if it still exists in the sessions list
        if (Array.isArray(parsed) && parsed.some(s => s.id === savedId)) return savedId
        // Active session was deleted / corrupted — fall back to the first real session
        if (Array.isArray(parsed) && parsed.length > 0) return parsed[0].id
      }
      if (savedId) return savedId   // sessions list missing but ID exists — keep it
    } catch {}
    return FALLBACK_SESSION_ID
  })
  const [pinnedItems, setPinnedItems] = useState(() => {
    try {
      const saved = localStorage.getItem('nexus_dashboard_pins')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed)) return parsed
      }
    } catch {}
    return []
  })

  // On mobile (≤768px) the sidebar starts hidden so it doesn't block the chat.
  // On desktop it starts open. We read window.innerWidth once at mount — no
  // event listener needed because the sidebar-toggle handles all subsequent changes.
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth > 768)
  const [currentView, setCurrentView]     = useState('query')
  const [ragMode, setRagMode]             = useState(false)   // false=Analytics, true=Knowledge Base
  const [stats, setStats]                 = useState({ posts: '—', comments: '—', likers: '—', followers: '—' })
  const [input, setInput]                 = useState('')
  const [loading, setLoading]             = useState(false)
  const [pipelineStage, setPipelineStage] = useState(null)
  const [dbStatus, setDbStatus]           = useState('connecting')
  const [toasts, setToasts]               = useState([])
  const [openMenuId, setOpenMenuId]       = useState(null)
  const [shareClicked, setShareClicked]   = useState(false)
  const [renamingId, setRenamingId]       = useState(null)
  const [renameValue, setRenameValue]     = useState('')
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false)

  const bottomRef           = useRef(null)
  const inputRef            = useRef(null)
  const pipelineTimerRef    = useRef(null)
  const renameInputRef      = useRef(null)
  // Tracks which frontend session IDs have already had their DB history restored,
  // so switching back to a session doesn't re-fetch what's already in state.
  const restoredSessionsRef = useRef(new Set())

  const messages         = sessions.find(s => s.id === activeSessionId)?.messages ?? []
  const recentSessions   = sessions.filter(s => s.messages.some(m => m.sender === 'user'))
  const pinnedQuestions  = useMemo(() => new Set(pinnedItems.map(p => p.question)), [pinnedItems])

  // Stable string/boolean primitives derived from sessions — used as deps for
  // the document.title + favicon useEffect so it fires only when the title or
  // presence of user messages actually changes, not on every sessions reference
  // update (which would fire on every query token, thinking-append, etc.).
  const activeSession   = sessions.find(s => s.id === activeSessionId)
  const sessionTitle    = activeSession?.title ?? ''
  const hasUserMessages = activeSession?.messages?.some(m => m.sender === 'user') ?? false

  const addToast = useCallback((msg, type = 'info') => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }, [])

  const handleNewChat = useCallback(() => {
    const newSession = { id: crypto.randomUUID(), title: 'New Chat', messages: [], backendSessionId: null }
    setSessions(prev => [newSession, ...prev])
    setActiveSessionId(newSession.id)
    setCurrentView('query')
    setInput('')
    setHeaderMenuOpen(false)
    // On mobile, collapse the sidebar after navigating so the chat is visible
    if (window.innerWidth <= 768) setIsSidebarOpen(false)
  }, [])

  const handleLoadSession = useCallback((id) => {
    setActiveSessionId(id)
    setCurrentView('query')
    setOpenMenuId(null)
    setHeaderMenuOpen(false)
    if (window.innerWidth <= 768) setIsSidebarOpen(false)
  }, [])

  const handleDeleteSession = useCallback((id) => {
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id)
      const remaining = next.length > 0 ? next : [{ id: crypto.randomUUID(), title: 'New Chat', messages: [], backendSessionId: null }]
      if (id === activeSessionId) setActiveSessionId(remaining[0].id)
      return remaining
    })
    setOpenMenuId(null)
    addToast('Chat deleted', 'info')
  }, [activeSessionId, addToast])

  const handleRenameSession = useCallback((id, currentTitle) => {
    setRenameValue(currentTitle)
    setRenamingId(id)
    setOpenMenuId(null)
    setTimeout(() => renameInputRef.current?.focus(), 0)
  }, [])

  const commitRename = useCallback((id) => {
    const trimmed = renameValue.trim()
    if (trimmed) {
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title: trimmed } : s))
    }
    setRenamingId(null)
  }, [renameValue])

  // ── Backend session creation ───────────────────────────────────────────────
  // Called lazily on the first message of each frontend session.
  // Hits POST /api/sessions, gets a DB UUID, stores it on the session object
  // (which the existing localStorage persistence effect then saves automatically).
  // Returns the backendSessionId string, or null if the call fails (graceful
  // degradation — chat still works, messages just won't be persisted to DB).
  const createBackendSession = useCallback(async (frontendSessionId) => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions`, {
        method: 'POST',
        headers: {
          // No Authorization header — auth is handled by Vercel password
          // protection on the frontend deployment. The NEXUS_API_KEY must be
          // set to "" in the Vercel backend env vars after this change.
          // See: https://vercel.com/docs/security/deployment-protection
          'Content-Type': 'application/json',
        },
        // Pass the frontend UUID as contact_id so the backend can enforce
        // session ownership on GET /api/sessions/{id}/history (R4 fix).
        body: JSON.stringify({ channel: 'web', contact_id: frontendSessionId }),
      })
      if (!res.ok) return null
      const data = await res.json()
      const backendSessionId = data.session_id
      // Write backendSessionId into the frontend session so it's persisted
      // to localStorage via the existing nexus_sessions effect.
      setSessions(prev => prev.map(s =>
        s.id === frontendSessionId ? { ...s, backendSessionId } : s
      ))
      return backendSessionId
    } catch {
      return null   // non-fatal — chat works without persistence
    }
  }, [])   // no deps: API_BASE is a build-time constant

  const handleShare = useCallback(() => {
    const url = window.location.href

    const onSuccess = () => {
      setShareClicked(true)
      addToast('Link copied to clipboard', 'success')
      setTimeout(() => setShareClicked(false), 2000)
    }

    // Modern Clipboard API — requires HTTPS (or localhost).
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(onSuccess).catch(() => {
        addToast('Could not copy link — please copy the URL manually', 'error')
      })
      return
    }

    // Fallback for HTTP / older browsers via deprecated execCommand.
    try {
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (ok) onSuccess()
      else addToast('Could not copy link — please copy the URL manually', 'error')
    } catch {
      addToast('Could not copy link — please copy the URL manually', 'error')
    }
  }, [addToast])

  const handlePin = useCallback(({ columns, rawResults, question }) => {
    const pin = { id: crypto.randomUUID(), question, columns, rawResults, pinnedAt: Date.now() }
    setPinnedItems(prev => [pin, ...prev])
    addToast('Insight pinned to Dashboard', 'success')
  }, [addToast])

  const handleUnpin = useCallback((id) => {
    setPinnedItems(prev => prev.filter(p => p.id !== id))
    addToast('Insight removed from Dashboard', 'info')
  }, [addToast])

  // ── CSV Export ─────────────────────────────────────────────────────────────
  const handleExportCSV = useCallback((columns, rawResults) => {
    if (!columns?.length || !rawResults?.length) return
    const escape = cell => {
      if (cell === null || cell === undefined) return ''
      const s = String(cell)
      return (s.includes(',') || s.includes('"') || s.includes('\n'))
        ? `"${s.replace(/"/g, '""')}"` : s
    }
    const lines = [columns.join(','), ...rawResults.map(row => row.map(escape).join(','))]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `nexus_export_${Date.now()}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    addToast(`Exported ${rawResults.length} rows as CSV`, 'success')
  }, [addToast])

  // ── Effects ────────────────────────────────────────────────────────────────
  useEffect(() => {
    // AbortController prevents a state update on an unmounted component:
    // if the view unmounts before the fetch resolves (fast navigation, HMR,
    // React Strict Mode double-invoke), the .catch sees AbortError and bails
    // out cleanly instead of calling setStats / setDbStatus on stale state.
    const controller = new AbortController()
    fetch(`${API_BASE}/api/stats`, {
      headers: {},
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          setStats({
            posts:     data.posts.toLocaleString(),
            comments:  data.comments.toLocaleString(),
            likers:    data.likers.toLocaleString(),
            followers: data.total_followers?.toLocaleString() ?? '—',
          })
          setDbStatus('ok')
        } else {
          setDbStatus('error')
          addToast('Database degraded — some features may be unavailable', 'error')
        }
      })
      .catch(err => {
        if (err?.name === 'AbortError') return  // unmounted — discard silently
        setDbStatus('error')
        addToast('Backend is offline — check that the server is running', 'error')
      })
    return () => controller.abort()
  }, [addToast])

  useEffect(() => {
    // Also fires when currentView becomes 'query' (tab switch back to chat).
    // setTimeout(0) gives React one tick to reattach bottomRef after the
    // conditional render before we try to scroll.
    if (currentView !== 'query') return
    const t = setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 0)
    return () => clearTimeout(t)
  }, [messages, currentView])

  useEffect(() => {
    // Strip rawResults before persisting — large result payloads (up to 500 rows)
    // can push the full sessions object past localStorage's 5–10 MB limit.
    // In-memory state is untouched so the active chat view keeps its full data.
    try {
      const lean = sessions.map(s => ({
        ...s,
        messages: s.messages.map(({ rawResults: _dropped, ...rest }) => rest),
      }))
      localStorage.setItem('nexus_sessions', JSON.stringify(lean))
    } catch (e) {
      if (e?.name === 'QuotaExceededError') {
        addToast('Storage full — chat history won\'t persist across reloads', 'error')
      }
    }
  }, [sessions, addToast])

  useEffect(() => {
    try { localStorage.setItem('nexus_active_session', activeSessionId) } catch {}
  }, [activeSessionId])

  useEffect(() => {
    try { localStorage.setItem('nexus_dashboard_pins', JSON.stringify(pinnedItems)) } catch {}
  }, [pinnedItems])

  // Context-aware document title + favicon.
  //
  // Title priority (highest → lowest):
  //   1. loading            → '⟳ Nexus — thinking…'
  //   2. hasUserMessages    → 'Nexus — [session title]'
  //   3. new / empty session → 'Nexus — Instagram Intelligence'
  //
  // Favicon: Nexus logo SVG at rest, two-arc spinner while a query runs.
  //
  // Deps: primitive strings/booleans (loading, sessionTitle, hasUserMessages)
  // rather than the raw `sessions` array. This prevents the effect from firing
  // on every internal sessions mutation (thinking-append, token streaming, etc.)
  // — it now fires only when the tab-visible state actually changes.
  useEffect(() => {
    document.title = loading
      ? '⟳ Nexus — thinking…'
      : hasUserMessages
        ? `Nexus — ${sessionTitle}`
        : 'Nexus — Instagram Intelligence'

    const idleSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28"><rect x="2" y="2" width="11" height="11" rx="2.5" fill="#4F7EFF"/><rect x="15" y="2" width="11" height="11" rx="2.5" fill="#4F7EFF" opacity="0.4"/><rect x="2" y="15" width="11" height="11" rx="2.5" fill="#4F7EFF" opacity="0.4"/><rect x="15" y="15" width="11" height="11" rx="2.5" fill="#4F7EFF"/></svg>`
    const busySvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28"><circle cx="14" cy="14" r="11" fill="none" stroke="#4F7EFF" stroke-width="3" stroke-dasharray="26 18" stroke-linecap="round"/><circle cx="14" cy="14" r="11" fill="none" stroke="#00D4AA" stroke-width="3" stroke-dasharray="10 34" stroke-linecap="round" stroke-dashoffset="-18"/></svg>`

    const href = `data:image/svg+xml,${encodeURIComponent(loading ? busySvg : idleSvg)}`
    let link = document.querySelector("link[rel~='icon']")
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.head.appendChild(link)
    }
    link.href = href
  }, [loading, sessionTitle, hasUserMessages])

  useEffect(() => {
    const handler = e => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setCurrentView('query')
        setTimeout(() => inputRef.current?.focus(), 50)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Pipeline Timer Cleanup ─────────────────────────────────────────────────
  // Both runPipeline and runRawSql schedule a setTimeout via pipelineTimerRef
  // to clear the pipeline stage indicator 1.5 s after a response. Without this
  // cleanup, if the component unmounts while that timer is pending (e.g. fast
  // navigation or React Strict Mode double-invoke), the callback fires against
  // a stale closure and calls setPipelineStage on an unmounted component.
  useEffect(() => {
    return () => {
      if (pipelineTimerRef.current) {
        clearTimeout(pipelineTimerRef.current)
        pipelineTimerRef.current = null
      }
    }
  }, [])

  // ── DB History Restoration ─────────────────────────────────────────────────
  // Fires whenever the active session changes. If the session has a
  // backendSessionId (it was previously created in the DB) but its local
  // message cache is empty (localStorage was cleared or the user opened a
  // different browser), we fetch the full history from the backend and
  // repopulate the chat UI. The restoredSessionsRef prevents double-fetching
  // when the user switches back to a session whose messages are already loaded.
  useEffect(() => {
    const session = sessions.find(s => s.id === activeSessionId)

    // Nothing to restore: no backend session, already has local messages,
    // or we already fetched for this session in this page-load.
    if (
      !session?.backendSessionId ||
      session.messages.length > 0 ||
      restoredSessionsRef.current.has(activeSessionId)
    ) return

    // Mark as in-progress immediately to prevent concurrent fetches.
    restoredSessionsRef.current.add(activeSessionId)

    const controller = new AbortController()

    fetch(`${API_BASE}/api/sessions/${session.backendSessionId}/history`, {
      headers: {
        // Echo the frontend session UUID so the backend can verify ownership
        // of the session (R4: IDOR fix). Matches the contact_id stored at
        // session creation time in createBackendSession above.
        'X-Session-Contact': session.id,
      },
      signal: controller.signal,
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.messages?.length) return
        // Map backend MessageOut objects → frontend message shape
        const restored = data.messages.map(m => ({
          id:        crypto.randomUUID(),
          sender:    m.role === 'user' ? 'user' : 'bot',
          text:      m.content,
          sql:       m.sql_used    || null,
          columns:   null,   // not stored in DB — only available during live session
          rawResults:null,
          timestamp: (() => {
            try { return new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
            catch { return '' }
          })(),
          isError:   false,
          fresh:     false,  // do not animate — this is restored, not a new response
        }))
        setSessions(prev => prev.map(s =>
          s.id === activeSessionId ? { ...s, messages: restored } : s
        ))
      })
      .catch(() => {
        // On failure, remove from the "restored" set so the next visit retries.
        restoredSessionsRef.current.delete(activeSessionId)
      })

    return () => controller.abort()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId])  // sessions deliberately omitted: checking it would cause
                         // re-fetch on every message added, which is the opposite
                         // of what we want. restoredSessionsRef guards correctness.

  // ── Pipeline ───────────────────────────────────────────────────────────────
  // useCallback avoids a new function reference on every unrelated render.
  // Deps: the four values read from component scope (setters/refs are stable).
  const runPipeline = useCallback(async (question) => {
    // Callers (handleSend, onRetry) pass already-trimmed strings —
    // the extra .trim() here was redundant. Guard on falsy is sufficient.
    if (!question || loading) return

    // Cancel any pending pipeline-clear from a previous response
    if (pipelineTimerRef.current) {
      clearTimeout(pipelineTimerRef.current)
      pipelineTimerRef.current = null
    }

    const sessionId = activeSessionId

    // Guard: if the active session was somehow lost, abort rather than silently no-op
    if (!sessions.some(s => s.id === sessionId)) {
      const recovered = { id: sessionId, title: 'New Chat', messages: [] }
      setSessions(prev => [recovered, ...prev])
    }

    const updateSession = (updater) => {
      setSessions(prev => prev.map(s => {
        if (s.id !== sessionId) return s
        const newMessages = typeof updater === 'function' ? updater(s.messages) : updater
        return { ...s, messages: newMessages }
      }))
    }

    const currentSession  = sessions.find(s => s.id === sessionId)
    const currentMessages = currentSession?.messages ?? []
    const historyPayload  = currentMessages
      .filter(m => m.type !== 'thinking' && m.text)
      .slice(-6)
      .map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }))

    const isFirstUserMsg = !currentMessages.some(m => m.sender === 'user')
    if (isFirstUserMsg) {
      const words = question.trim().split(/\s+/)
      const title = words.slice(0, 7).join(' ') + (words.length > 7 ? '…' : '')
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s))
    }

    // ── Backend session (Analytics mode only) ────────────────────────────────
    // RAG queries are stateless — no session creation or message persistence.
    let backendSid = null
    if (!ragMode) {
      backendSid = currentSession?.backendSessionId ?? null
      if (!backendSid) {
        backendSid = await createBackendSession(sessionId)
      }
    }

    setLoading(true)
    updateSession(prev => [
      ...prev,
      { id: crypto.randomUUID(), sender: 'user', text: question, timestamp: getTimestamp() },
      { id: crypto.randomUUID(), sender: 'bot',  type: 'thinking' },
    ])
    setPipelineStage('sql')

    // Build request — RAG uses a simple {message} body; Analytics passes history + session
    const endpoint  = ragMode ? '/api/rag_query' : '/api/chat'
    const reqBody   = ragMode
      ? { message: question }
      : { message: question, history: historyPayload, ...(backendSid ? { session_id: backendSid } : {}) }

    try {
      // 38 s gives the backend's 30 s LLM timeout full room before we give up.
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(reqBody),
        signal: AbortSignal.timeout(38_000)
      });
      const data = await res.json()
      setPipelineStage('done')

      if (data.status === 'success') {
        updateSession(prev => [
          ...prev.filter(m => m.type !== 'thinking'),
          {
            id:         crypto.randomUUID(),
            sender:     'bot',
            text:       data.reply,
            sql:        data.sql_used    || null,
            rawResults: data.raw_results || null,
            columns:    data.columns     || null,
            sources:    data.sources     || null,   // RAG source filenames
            timestamp:  getTimestamp(),
            isError:    false,
            fresh:      true,
            question,
          },
        ])
      } else {
        if (data.error_code === 'rate_limit_error') addToast('Rate limit reached — please wait a moment', 'error')
        if (data.error_code === 'llm_error')        addToast('AI service is temporarily unavailable', 'error')
        updateSession(prev => [
          ...prev.filter(m => m.type !== 'thinking'),
          { id: crypto.randomUUID(), sender: 'bot', text: data.reply, isError: true, originalQuestion: question, timestamp: getTimestamp() },
        ])
      }
    } catch (err) {
      const isTimeout = err?.name === 'TimeoutError' || err?.name === 'AbortError'
      updateSession(prev => [
        ...prev.filter(m => m.type !== 'thinking'),
        {
          id:               crypto.randomUUID(),
          sender:           'bot',
          text:             isTimeout
            ? 'The request timed out — the AI is taking too long. Please try again.'
            : 'Could not reach the backend. Please check that the server is running.',
          isError:          true,
          originalQuestion: question,
          timestamp:        getTimestamp(),
        },
      ])
      addToast(
        isTimeout
          ? 'Request timed out after 38 s — please try again'
          : 'Connection failed — backend unreachable',
        'error',
      )
    } finally {
      setLoading(false)
      pipelineTimerRef.current = setTimeout(() => {
        setPipelineStage(null)
        pipelineTimerRef.current = null
      }, 1500)
    }
  }, [loading, activeSessionId, sessions, addToast, createBackendSession, ragMode])

  // ── Raw SQL Execution (bypasses LLM — used by SQL Editor mode) ────────────
  const runRawSql = useCallback(async (sql) => {
    if (!sql.trim() || loading) return
    const sessionId = activeSessionId

    setLoading(true)
    setSessions(prev => prev.map(s => s.id !== sessionId ? s : {
      ...s,
      messages: [
        ...s.messages,
        { id: crypto.randomUUID(), sender: 'user', text: '▶ Custom SQL re-run', timestamp: getTimestamp() },
        { id: crypto.randomUUID(), sender: 'bot',  type: 'thinking' },
      ],
    }))
    setPipelineStage('db')

    try {
      const res = await fetch(`${API_BASE}/api/raw_query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ sql }),
        signal: AbortSignal.timeout(30_000),
      })
      const data = await res.json()
      setPipelineStage('done')

      const n = data.row_count ?? 0
      setSessions(prev => prev.map(s => s.id !== sessionId ? s : {
        ...s,
        messages: [
          ...s.messages.filter(m => m.type !== 'thinking'),
          {
            id:         crypto.randomUUID(),
            sender:     'bot',
            text:       data.status === 'success'
              ? `Query returned ${n} row${n !== 1 ? 's' : ''}.`
              : (data.reply || 'Query failed.'),
            sql,
            rawResults: data.raw_results || null,
            columns:    data.columns    || null,
            timestamp:  getTimestamp(),
            isError:    data.status !== 'success',
            fresh:      true,
          },
        ],
      }))
    } catch (err) {
      // Log the real error object so developers can distinguish network failures,
      // JSON parse errors, and AbortError timeouts — not just see a generic toast.
      console.error('[runRawSql] Execution error:', err)
      const isTimeout = err?.name === 'TimeoutError' || err?.name === 'AbortError'
      const userMsg = isTimeout
        ? 'SQL query timed out after 30 s — try a simpler query or reduce the result set.'
        : 'SQL execution failed — could not reach the backend. Check that the server is running.'
      setSessions(prev => prev.map(s => s.id !== sessionId ? s : {
        ...s,
        messages: [
          ...s.messages.filter(m => m.type !== 'thinking'),
          { id: crypto.randomUUID(), sender: 'bot', text: userMsg, isError: true, timestamp: getTimestamp() },
        ],
      }))
      addToast(
        isTimeout
          ? 'SQL query timed out after 30 s'
          : 'SQL execution failed — backend unreachable',
        'error',
      )
    } finally {
      setLoading(false)
      pipelineTimerRef.current = setTimeout(() => {
        setPipelineStage(null)
        pipelineTimerRef.current = null
      }, 1500)
    }
  }, [loading, activeSessionId, addToast])

  const handleSend = () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    runPipeline(q)
  }

  const handleSuggestion = (q) => {
    // Fire immediately — matches the expectation set by every major AI product.
    // No need to populate the input first; runPipeline handles the full cycle.
    runPipeline(q)
  }

  const charCount = input.length
  const charClass = charCount > 475 ? 'red' : charCount > 400 ? 'amber' : ''

  const navItems = [
    { id: 'query',     icon: 'query',     label: 'Query'          },
    { id: 'dashboard', icon: 'dashboard', label: 'Dashboard', badge: pinnedItems.length || null },
    { id: 'analytics', icon: 'analytics', label: 'Analytics'      },
    { id: 'arch',      icon: 'arch',      label: 'Architecture'   },
    { id: 'schema',    icon: 'schema',    label: 'Schema & Stats' },
  ]

  return (
    <div className="app-shell">
      <LivingBg loading={loading}/>
      <ToastContainer toasts={toasts}/>

      {/* Mobile backdrop — semi-opaque overlay behind the sidebar when open.
          Only becomes visible via CSS at ≤768px; zero cost on desktop. */}
      <div
        className={`sidebar-backdrop${isSidebarOpen ? ' visible' : ''}`}
        onClick={() => setIsSidebarOpen(false)}
        aria-hidden="true"
      />

      <aside className={`sidebar${isSidebarOpen ? '' : ' collapsed'}`}>
        <div className="sidebar-inner">
          <div className="brand">
            <div className="brand-icon"><Icon name="logo" size={20}/></div>
            <div>
              <div className="brand-name">Nexus</div>
              <div className="brand-sub">Social Data Intelligence</div>
            </div>
          </div>

          <button className="sidebar-new-chat" onClick={handleNewChat}>
            <Icon name="plus" size={14}/>
            <span>New Chat</span>
          </button>

          <nav className="sidebar-nav">
            {navItems.map(item => (
              <button
                key={item.id}
                className={`nav-btn ${currentView === item.id ? 'active' : ''}`}
                onClick={() => {
                  setCurrentView(item.id)
                  // On mobile, dismiss the sidebar overlay after navigating
                  if (window.innerWidth <= 768) setIsSidebarOpen(false)
                }}
              >
                <span className="nav-icon"><Icon name={item.icon} size={16}/></span>
                <span className="nav-label">{item.label}</span>
                {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
                {currentView === item.id && <span className="active-pill"/>}
              </button>
            ))}
          </nav>

          <div className="sidebar-recents">
            {recentSessions.length > 0 && (
              <>
                <div className="recents-label">Recents</div>
                <div className="recents-list">
                  {recentSessions.map(s => (
                    <div
                      key={s.id}
                      className={`session-item ${s.id === activeSessionId ? 'active' : ''} ${openMenuId === s.id ? 'menu-open' : ''} ${renamingId === s.id ? 'renaming' : ''}`}
                      style={{ '--depth': (Math.min(s.messages.length, 24) / 24).toFixed(2) }}
                    >
                      {renamingId === s.id ? (
                        <input
                          ref={renameInputRef}
                          className="session-rename-input"
                          value={renameValue}
                          onChange={e => setRenameValue(e.target.value)}
                          onBlur={() => commitRename(s.id)}
                          onKeyDown={e => {
                            if (e.key === 'Enter')  { e.preventDefault(); commitRename(s.id) }
                            if (e.key === 'Escape') { setRenamingId(null) }
                          }}
                          maxLength={60}
                        />
                      ) : (
                        <button
                          className="session-item-btn"
                          onClick={() => handleLoadSession(s.id)}
                          title={s.title}
                        >
                          <span className="session-title">{s.title}</span>
                        </button>
                      )}
                      {renamingId !== s.id && (
                        <button
                          className="session-more-btn"
                          onClick={e => { e.stopPropagation(); setOpenMenuId(openMenuId === s.id ? null : s.id) }}
                          title="More options"
                          aria-label="More options"
                        >
                          <Icon name="more" size={13}/>
                        </button>
                      )}
                      {openMenuId === s.id && (
                        <SessionContextMenu
                          onRename={() => handleRenameSession(s.id, s.title)}
                          onDelete={() => handleDeleteSession(s.id)}
                          onClose={() => setOpenMenuId(null)}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </aside>

      <main className="main-content">
        <button
          className="sidebar-toggle-btn"
          onClick={() => setIsSidebarOpen(o => !o)}
          title={isSidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          aria-label={isSidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          <Icon name="menu" size={16}/>
        </button>

        {/* key=currentView forces remount on tab switch → view-enter animation replays */}
        <div key={currentView} className="view-anim-wrapper">
        {currentView === 'query' && (
          <div className="query-view">
            <PipelineBar stage={pipelineStage} dbStatus={dbStatus}/>

              {messages.length > 0 && (
              <div className="chat-header">
                <div className="chat-header-center">
                  <span className="chat-header-title">
                    {sessions.find(s => s.id === activeSessionId)?.title ?? 'New Chat'}
                  </span>
                </div>
                <div className="chat-header-actions">
                  <button className="chat-header-btn" onClick={handleShare} title="Copy link" aria-label="Copy link">
                    <Icon name={shareClicked ? 'check' : 'share'} size={15}/>
                  </button>
                  {/* "More options" — now wired to a full SessionContextMenu anchored below */}
                  <div className="chat-header-more-wrap">
                    <button
                      className={`chat-header-btn${headerMenuOpen ? ' active' : ''}`}
                      onClick={() => setHeaderMenuOpen(o => !o)}
                      title="Session options"
                      aria-label="Session options"
                    >
                      <Icon name="more" size={15}/>
                    </button>
                    {headerMenuOpen && (
                      <SessionContextMenu
                        onRename={() => {
                          setHeaderMenuOpen(false)
                          // On mobile, open the sidebar so the rename input is reachable
                          if (window.innerWidth <= 768) setIsSidebarOpen(true)
                          handleRenameSession(activeSessionId, sessionTitle)
                        }}
                        onDelete={() => {
                          setHeaderMenuOpen(false)
                          handleDeleteSession(activeSessionId)
                        }}
                        onClose={() => setHeaderMenuOpen(false)}
                      />
                    )}
                  </div>
                </div>
              </div>
            )}

          <div className="chat-area">
              {messages.length === 0
                ? <EmptyChat onSelect={handleSuggestion} ragMode={ragMode}/>
                : (
                  <div className="messages-scroll">
                    {messages.map((msg, i) => (
                      <Message
                        key={msg.id ?? i}
                        msg={msg}
                        onRetry={runPipeline}
                        onExport={handleExportCSV}
                        onPin={handlePin}
                        isPinned={pinnedQuestions.has(msg.question)}
                        onRerunSql={runRawSql}
                      />
                    ))}
                    <div ref={bottomRef}/>
                  </div>
                )
              }
            </div>

            <div className="input-dock">
              {/* ── Mode toggle — switches between Analytics and Knowledge Base ── */}
              <div className="mode-toggle" role="group" aria-label="Chat mode">
                <button
                  className={`mode-btn${!ragMode ? ' active' : ''}`}
                  onClick={() => setRagMode(false)}
                  title="Query your Instagram analytics data"
                >
                  <Icon name="schema" size={12}/> Instagram Data
                </button>
                <button
                  className={`mode-btn${ragMode ? ' active' : ''}`}
                  onClick={() => setRagMode(true)}
                  title="Ask questions about your business"
                >
                  <Icon name="sparkle" size={12}/> Ask Erez
                </button>
              </div>

              <div className="input-wrapper">
                <input
                  ref={inputRef}
                  className="chat-input"
                  type="text"
                  placeholder={ragMode
                    ? 'שאל על השירותים שלנו… (⌘K)'
                    : 'Ask anything about your Instagram data… (⌘K)'}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSend()}
                  disabled={loading}
                  dir="auto"
                  maxLength={500}
                />
                {charCount > 0 && (
                  <span className={`char-count ${charClass}`}>{charCount}/500</span>
                )}
              </div>
              <button
                className={`send-btn ${loading ? 'loading' : ''}`}
                onClick={handleSend}
                disabled={loading}
                title="Send (Enter)"
                aria-label={loading ? 'Sending…' : 'Send message'}
              >
                {loading ? <span className="spinner"/> : <Icon name="send" size={16}/>}
              </button>
            </div>
          </div>
        )}

        {currentView === 'dashboard' && (
          <DashboardView pinnedItems={pinnedItems} onUnpin={handleUnpin} onExport={handleExportCSV}/>
        )}
        {currentView === 'analytics' && <AnalyticsView/>}
        {currentView === 'arch'      && <ArchView/>}
        {currentView === 'schema'    && (
          <StatsView
            stats={stats}
            onQuerySuggestion={q => {
              setInput(q)
              setCurrentView('query')
              setTimeout(() => inputRef.current?.focus(), 50)
            }}
          />
        )}
        </div>{/* end .view-anim-wrapper */}
      </main>
    </div>
  )
}
