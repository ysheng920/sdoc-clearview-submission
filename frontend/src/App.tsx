import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { Icon } from './components/Icon'
import { RunPanel } from './components/RunPanel'
import { Dashboard } from './pages/Dashboard'
import { Benchmark } from './pages/Benchmark'
import { Inbox } from './pages/Inbox'
import { Settings } from './pages/Settings'
import type { AppConfig, Dashboard as DashboardData, Run } from './types'

type View = 'queue' | 'review' | 'analytics' | 'benchmark' | 'settings' | 'case'
const nav: { view: View; label: string; icon: string; separated?: boolean }[] = [
  { view: 'queue', label: 'Work Queue', icon: 'queue' },
  { view: 'review', label: 'Human Review', icon: 'review' },
  { view: 'analytics', label: 'Analytics', icon: 'analytics' },
  { view: 'benchmark', label: 'Benchmark', icon: 'chart', separated: true },
  { view: 'settings', label: 'Settings', icon: 'settings' },
]

const VIEW_HEADINGS: Record<View, { eyebrow: string; title: string; sub?: string }> = {
  queue: {
    eyebrow: 'OPERATIONS / INBOX',
    title: 'Work Queue',
    sub: 'Your shipping document cases, in one clear view.',
  },
  review: {
    eyebrow: 'OPERATIONS / DECISIONS',
    title: 'Human Review Queue',
    sub: 'Cases requiring your judgement or manual verification.',
  },
  case: {
    eyebrow: 'OPERATIONS / CASE',
    title: 'Case Workspace',
    sub: 'Inspect documents, discrepancy details, and policy actions.',
  },
  analytics: {
    eyebrow: 'INSIGHTS / LATEST RUN',
    title: 'Analytics & Performance',
    sub: 'Track document verification, model behaviour and review workload.',
  },
  benchmark: {
    eyebrow: 'QUALITY / GROUND TRUTH',
    title: 'Model Benchmark',
    sub: 'How each model scores against the labelled corpus.',
  },
  settings: {
    eyebrow: 'PREFERENCES / SYSTEM',
    title: 'Workspace Settings',
    sub: 'View processing configuration and adjust your workspace appearance.',
  },
}

/** The address bar is the only place this state lives, so read it in one place. */
function parseHash(): { view: View; caseId: string | null } {
  const hash = window.location.hash.slice(1)
  // Any case id, not just email_*: a simulated email is sim_001, and matching
  // the corpus prefix bounced it straight back to the queue.
  if (hash.startsWith('case-')) return { view: 'case', caseId: hash.slice(5) }
  if (nav.some((n) => n.view === hash)) return { view: hash as View, caseId: null }
  return { view: 'queue', caseId: null }
}

export default function App() {
  const [view, setView] = useState<View>(() => parseHash().view)
  const [caseId, setCaseId] = useState<string | null>(() => parseHash().caseId)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [summary, setSummary] = useState<DashboardData | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [runError, setRunError] = useState('')
  const [showRunPanel, setShowRunPanel] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [resetToast, setResetToast] = useState<string | null>(null)
  // Which model's results the queue and the case view show. Kept here so that
  // opening a case from a filtered queue does not silently switch model.
  const [model, setModel] = useState('')
  const poll = useRef<number | null>(null)
  // Which run we have already refreshed for, so a terminal state fires once.
  const settled = useRef<number | null>(null)
  const runId = run?.id
  const runStatus = run?.status

  useEffect(() => { window.location.hash = view === 'case' ? `case-${caseId}` : view }, [view, caseId])

  // The hash was written but never read again, so Back, Forward and a pasted
  // deep link all did nothing once the page had loaded. Setting the same value
  // is a no-op in React, so this cannot loop against the effect above.
  useEffect(() => {
    const sync = () => {
      const next = parseHash()
      setView(next.view)
      setCaseId(next.caseId)
    }
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null))
    api.runs().then((rows) => setRun(rows[0] ?? null)).catch(() => {})
  }, [])
  useEffect(() => { api.dashboard().then(setSummary).catch(() => setSummary(null)) }, [reloadKey])
  useEffect(() => {
    if (!runId) return

    if (runStatus !== 'running') {
      // Refresh here, not only inside the poller. A one-email run can already
      // be finished the first time its status is fetched, and a run that fails
      // immediately never polls at all -- in both cases the poller never runs,
      // so every view sat stale until the page was reloaded by hand.
      if (settled.current !== runId) {
        settled.current = runId
        setReloadKey((n) => n + 1)
      }
      return
    }

    poll.current = window.setInterval(async () => {
      try {
        setRun(await api.run(runId))
      } catch (e) {
        // Stop rather than retry. A deleted run 404s forever otherwise, at
        // 700ms, which is what filled the log with GET /api/runs/9 404.
        if (poll.current) { window.clearInterval(poll.current); poll.current = null }
        setRunError(String(e))
        setRun(null)
      }
    }, 700)
    return () => { if (poll.current) window.clearInterval(poll.current) }
  }, [runId, runStatus])

  function openCase(id: string) { setCaseId(id); setView('case') }
  // Refresh sidebar badge counts when case status changes
  const handleStatusChange = () => {
    setReloadKey((n) => n + 1);
    api.dashboard().then(setSummary).catch(() => {});
  };

  const handleResetDemo = async () => {
    if (!window.confirm('Reset demo environment to baseline?\n\n• Approved Mappings: Reset to predefined examples\n• Batch & Edge Cases: Restored to 526 frozen demo cases\n• Work Queue: Restored to baseline state')) {
      return
    }
    setResetting(true)
    try {
      await api.resetDemo()
      if (view === 'case') {
        setView('queue')
        setCaseId(null)
      }
      const runs = await api.runs()
      setRun(runs[0] ?? null)
      setReloadKey((n) => n + 1)
      setResetToast('Demo environment reset: 526 results loaded, predefined mappings active.')
      setTimeout(() => setResetToast(null), 4500)
    } catch (e) {
      alert(`Reset failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setResetting(false)
    }
  }

  const activeNav = view === 'case' ? 'queue' : view
  const running = run?.status === 'running'
  const progress = run?.total ? Math.round(run.done / run.total * 100) : 0
  const reviewCount = summary?.workflow?.needs_judgement ?? summary?.headline?.needs_judgement ?? 0
  const queueCount = summary?.workflow?.action_required ?? (
    summary?.headline?.needs_approval != null
      ? Math.max(0, summary.headline.needs_approval - (summary.workflow?.handled ?? 0))
      : summary?.workflow?.open ?? summary?.count ?? 0
  )
  const currentHeading = VIEW_HEADINGS[view] ?? VIEW_HEADINGS.queue

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup" onClick={() => setView('queue')} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setView('queue')}>
        <div className="brand-icon"><Icon name="ship" size={31} /></div>
        <div><strong>SDOC Clearview</strong><small>Shipping Documents, Clearer Decisions</small></div>
      </div>
      <nav className="side-nav" aria-label="Main navigation">
        {nav.map((item) => <button key={item.view} className={`${activeNav === item.view ? 'active' : ''} ${item.separated ? 'nav-separated' : ''}`} onClick={() => setView(item.view)}>
          <Icon name={item.icon} size={21}/><span>{item.label}</span>
          {item.view === 'queue' && queueCount > 0 && <em>{queueCount}</em>}
          {item.view === 'review' && reviewCount > 0 && <em>{reviewCount}</em>}
        </button>)}
      </nav>
      <div className="sidebar-footer">
        <p>Smarter document<br/>verification for<br/>smoother shipments.</p>
      </div>
    </aside>

    <div className="app-body">
      <header className="global-topbar">
        <div className="topbar-heading">
          <span className="eyebrow">{currentHeading.eyebrow}</span>
          <div className="topbar-title-line">
            <h1>{currentHeading.title}</h1>
            {currentHeading.sub && <span className="topbar-sub">{currentHeading.sub}</span>}
          </div>
        </div>
        <div className="global-topbar-right">
          {running && <div className="run-progress"><span>Processing {run.done}/{run.total}</span><div><i style={{ width: `${progress}%` }}/></div></div>}
          <button
            className="demo-reset-btn"
            onClick={handleResetDemo}
            disabled={resetting || running}
            title="Reset to clean baseline demo: 526 results, predefined mappings"
          >
            <Icon name="rotate" size={15}/>
            <span>{resetting ? 'Resetting…' : 'Reset Demo'}</span>
          </button>
          <button
            className="primary-action"
            onClick={() => setShowRunPanel(true)}
            disabled={running}
            title="Simulate processing a single email with custom attachments"
          >
            <Icon name="mail" size={16}/>
            <span>Simulate Email</span>
          </button>
          {config && <div className="runtime-pill" title={config.has_model ? `Active backend: ${config.backend}${config.model ? ` · ${config.model}` : ''}` : 'No model is configured. Documents are still parsed and compared; emails are not classified.'}><span className={`runtime-dot ${config.has_model ? '' : 'rules-only'}`}/>{config.has_model ? config.backend : 'Rules only'}</div>}
          <div className="operator-avatar" aria-hidden="true">OP</div><div className="operator-label"><strong>Operator</strong><small>Workspace</small></div>
        </div>
      </header>
      {showRunPanel && (
        <div className="run-modal-backdrop" onClick={() => setShowRunPanel(false)}>
          <div className="run-modal" role="dialog" aria-modal="true" aria-label="Run the pipeline"
               onClick={(event) => event.stopPropagation()}>
            <RunPanel
              onClose={() => setShowRunPanel(false)}
              // A simulated email is one email and is already finished when the
              // call returns, so there is no run to poll -- refresh and open it.
              onSimulated={(id) => { setReloadKey((n) => n + 1); openCase(id) }}
            />
          </div>
        </div>
      )}
      {resetToast && (
        <div className="demo-reset-toast">
          <Icon name="check" size={16} />
          <span>{resetToast}</span>
          <button onClick={() => setResetToast(null)} aria-label="Dismiss notification">✕</button>
        </div>
      )}
      {runError && <div className="app-error">{runError}<button onClick={() => setRunError('')}>Dismiss</button></div>}
      <div className="page-scroll">
        {view === 'queue' && <Inbox model={model} onModel={setModel} mode="queue" reloadKey={reloadKey} onOpenCase={openCase} onStatusChange={handleStatusChange} />}
        {view === 'review' && <Inbox model={model} onModel={setModel} mode="review" reloadKey={reloadKey} onOpenCase={openCase} onStatusChange={handleStatusChange} />}
        {view === 'case' && caseId && <Inbox model={model} mode="case" caseId={caseId} reloadKey={reloadKey} onBack={() => setView('queue')} onStatusChange={handleStatusChange} />}
        {view === 'analytics' && <Dashboard reloadKey={reloadKey} onOpenEmail={openCase} />}
        {view === 'benchmark' && <Benchmark />}
        {view === 'settings' && <Settings onOpenCase={openCase} />}
      </div>
    </div>
  </div>
}
