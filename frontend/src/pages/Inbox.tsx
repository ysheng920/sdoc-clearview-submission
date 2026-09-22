import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ActionBadge, CategoryBadge, StatusBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { CaseWorkspace } from '../components/CaseWorkspace'
import type { EmailSummary } from '../types'

type Props = {
  mode: 'queue' | 'review' | 'case'
  search?: string
  reloadKey?: number
  caseId?: string
  onOpenCase?: (id: string) => void
  onBack?: () => void
  onStatusChange?: () => void
  /** Which model's results to show. Empty means the latest for each email. */
  model?: string
  onModel?: (key: string) => void
}

export type Filter =
  | 'all'
  | 'mismatch'
  | 'needs_review'
  | 'low_confidence'

type QueueStage = 'action_required' | 'no_action' | 'handled'
type WorkView = 'all' | 'decision' | 'approval'
type CaseType = 'all' | 'mismatch' | 'blocker' | 'auto_clear' | 'inquiry' | 'low_confidence' | 'general' | 'spam'

export const label = (id: string) => `#${id.replace('email_', '')}`

export const getCustomer = (e: { email_id?: string; from?: string; customer?: string | null; customer_email?: string }) => {
  const email = (e.customer_email || e.from || '').trim()
  const name = e.customer?.trim() || null
  return { name, email }
}

const shipment = (subject: string) => subject.match(/\b[A-Z0-9]{4}-\d{5}\b/)?.[0] ?? 'Sample shipment'

const routingConfidence = (email: EmailSummary) =>
  email.classification_routing?.fallback_used
    ? (email.classification_routing.primary_confidence ?? email.confidence)
    : email.confidence

export function Inbox({ mode, search = '', reloadKey = 0, caseId, onOpenCase, onBack, onStatusChange,
                       model = '' }: Props) {
  const [emails, setEmails] = useState<EmailSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [queueStage, setQueueStage] = useState<QueueStage>('action_required')
  const [workView, setWorkView] = useState<WorkView>('all')
  const [caseType, setCaseType] = useState<CaseType>('all')
  const [sort, setSort] = useState(mode === 'queue' ? 'latest' : 'priority')
  const [page, setPage] = useState(1)
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [localSearch, setLocalSearch] = useState('')
  const [statusVersion, setStatusVersion] = useState(0)
  const pageSize = mode === 'review' ? 9 : 12

  useEffect(() => {
    if (mode === 'case') return
    let active = true
    setLoading(true)
    api.emails(model ? { model } : {}).then((res) => {
      if (!active) return
      setEmails(res.emails)
      setLoading(false)
    }).catch((e) => { if (active) { setError(String(e)); setLoading(false) } })
    return () => { active = false }
  }, [reloadKey, statusVersion, mode, model])

  const counts = useMemo(() => {
    const isAutoClear = (e: EmailSummary) => e.comparison_status === 'OK' || e.action === 'AUTO_CLEAR'
    const active = emails.filter((e) => !e.resolved)
    const handled = emails.filter((e) => Boolean(e.resolved))
    const isRev = (e: EmailSummary) => !e.resolved && Boolean(e.needs_judgement)
    const isBlocked = (e: EmailSummary) =>
      e.action === 'HUMAN_REVIEW' ||
      e.comparison_status === 'NEEDS_REVIEW' ||
      (Boolean(e.needs_judgement) && e.comparison_status !== 'MISMATCH')

    return {
      all: emails.length,
      handled: handled.length,
      actionRequired: active.filter((e) => Boolean(e.needs_approval) || Boolean(e.needs_judgement)).length,
      noAction: active.filter((e) => !e.needs_approval && !e.needs_judgement).length,
      needsDecision: active.filter((e) => Boolean(e.needs_judgement)).length,
      readyApproval: active.filter((e) => Boolean(e.needs_approval) && !e.needs_judgement).length,
      reviewAll: active.filter(isRev).length,
      mismatch: active.filter((e) => Boolean(e.needs_judgement) && e.comparison_status === 'MISMATCH').length,
      reviewMismatch: emails.filter((e) => isRev(e) && e.comparison_status === 'MISMATCH').length,
      needs_review: active.filter(isBlocked).length,
      reviewNeedsReview: emails.filter((e) => isRev(e) && isBlocked(e)).length,
      ok: active.filter((e) => Boolean(e.needs_approval) && !e.needs_judgement && isAutoClear(e)).length,
      acknowledge: active.filter((e) => Boolean(e.needs_approval) && !e.needs_judgement && e.action === 'ACKNOWLEDGE').length,
      reviewApproval: emails.filter((e) => isRev(e) && Boolean(e.needs_approval)).length,
      lowConf: active.filter((e) => (routingConfidence(e) ?? 1) < 0.8).length,
      actionRequiredLowConf: active.filter((e) => (Boolean(e.needs_approval) || Boolean(e.needs_judgement)) && (routingConfidence(e) ?? 1) < 0.8).length,
      decisionLowConf: active.filter((e) => Boolean(e.needs_judgement) && (routingConfidence(e) ?? 1) < 0.8).length,
      approvalLowConf: active.filter((e) => Boolean(e.needs_approval) && !e.needs_judgement && (routingConfidence(e) ?? 1) < 0.8).length,
      noActionLowConf: active.filter((e) => !e.needs_approval && !e.needs_judgement && (routingConfidence(e) ?? 1) < 0.8).length,
      noActionGeneral: active.filter((e) => !e.needs_approval && !e.needs_judgement && e.category === 'GENERAL').length,
      noActionSpam: active.filter((e) => !e.needs_approval && !e.needs_judgement && e.category === 'SPAM').length,
      reviewLowConf: emails.filter((e) => isRev(e) && (routingConfidence(e) ?? 1) < 0.8).length,
    }
  }, [emails])

  const filterList = useMemo(() => {
    if (mode === 'review') {
      const list: { key: Filter; label: string; count: number }[] = [
        { key: 'all', label: 'All review', count: counts.reviewAll },
        { key: 'mismatch', label: 'Mismatches', count: counts.reviewMismatch },
        { key: 'needs_review', label: 'Needs review / Blockers', count: counts.reviewNeedsReview },
      ]
      if (counts.reviewLowConf > 0) {
        list.push({ key: 'low_confidence', label: 'Low confidence', count: counts.reviewLowConf })
      }
      return list
    }
    return []
  }, [mode, counts])

  const visible = useMemo(() => {
    const q = `${search} ${localSearch}`.trim().toLowerCase()
    const source = mode === 'review'
      ? emails.filter((e) => !e.resolved && Boolean(e.needs_judgement))
      : emails
    return source.filter((e) => {
      if (mode === 'queue') {
        const actionRequired = Boolean(e.needs_approval) || Boolean(e.needs_judgement)
        const needsDecision = Boolean(e.needs_judgement)
        const readyApproval = Boolean(e.needs_approval) && !needsDecision
        const isBlocker = e.action === 'HUMAN_REVIEW' ||
          e.comparison_status === 'NEEDS_REVIEW' ||
          (needsDecision && e.comparison_status !== 'MISMATCH')
        const isAutoClear = readyApproval && (e.comparison_status === 'OK' || e.action === 'AUTO_CLEAR')

        if (queueStage === 'handled' && !e.resolved) return false
        if (queueStage !== 'handled' && e.resolved) return false
        if (queueStage === 'action_required' && !actionRequired) return false
        if (queueStage === 'no_action' && actionRequired) return false

        if (queueStage === 'action_required') {
          if (workView === 'decision' && !needsDecision) return false
          if (workView === 'approval' && !readyApproval) return false
          if (caseType === 'mismatch' && (!needsDecision || e.comparison_status !== 'MISMATCH')) return false
          if (caseType === 'blocker' && !isBlocker) return false
          if (caseType === 'auto_clear' && !isAutoClear) return false
          if (caseType === 'inquiry' && (!readyApproval || e.action !== 'ACKNOWLEDGE')) return false
          if (caseType === 'low_confidence' && (routingConfidence(e) ?? 1) >= 0.8) return false
        }

        if (queueStage === 'no_action') {
          if (caseType === 'general' && e.category !== 'GENERAL') return false
          if (caseType === 'spam' && e.category !== 'SPAM') return false
          if (caseType === 'low_confidence' && (routingConfidence(e) ?? 1) >= 0.8) return false
        }
      }
      if (mode === 'review' && filter === 'mismatch' && e.comparison_status !== 'MISMATCH') return false
      if (mode === 'review' && filter === 'needs_review') {
        const isBlocked = e.action === 'HUMAN_REVIEW' ||
          e.comparison_status === 'NEEDS_REVIEW' ||
          (Boolean(e.needs_judgement) && e.comparison_status !== 'MISMATCH')
        if (!isBlocked) return false
      }
      if (mode === 'review' && filter === 'low_confidence' && (routingConfidence(e) ?? 1) >= 0.8) return false

      const cust = getCustomer(e)
      return !q || [
        e.email_id,
        label(e.email_id),
        cust.name,
        cust.email,
        e.subject,
        e.category,
        e.action,
        ...(e.blockers ?? []),
        e.why,
      ].some((v) => v?.toLowerCase().includes(q))
    }).sort((a, b) => {
      if (sort === 'latest') return b.email_id.localeCompare(a.email_id, undefined, { numeric: true })
      if (sort === 'oldest' || sort === 'case') return a.email_id.localeCompare(b.email_id, undefined, { numeric: true })
      if (sort === 'customer') {
        const nameA = getCustomer(a).name || getCustomer(a).email
        const nameB = getCustomer(b).name || getCustomer(b).email
        return nameA.localeCompare(nameB)
      }
      if (sort === 'confidence') return routingConfidence(a) - routingConfidence(b)
      return Number(Boolean(b.needs_judgement)) - Number(Boolean(a.needs_judgement)) ||
             Number(b.comparison_status === 'MISMATCH') - Number(a.comparison_status === 'MISMATCH') ||
             b.email_id.localeCompare(a.email_id, undefined, { numeric: true })
    })
  }, [emails, search, localSearch, mode, filter, queueStage, workView, caseType, sort])

  const pages = Math.max(1, Math.ceil(visible.length / pageSize))
  const currentPage = Math.min(page, pages)
  const rows = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return visible.slice(start, start + pageSize)
  }, [visible, currentPage, pageSize])

  useEffect(() => {
    if (mode !== 'review') return
    if (!rows.length) {
      setReviewId(null)
      return
    }
    setReviewId((current) => {
      if (current && rows.some((e) => e.email_id === current)) {
        return current
      }
      return rows[0].email_id
    })
  }, [mode, rows])

  function caseStatusChanged() {
    setReviewId(null)
    setStatusVersion((n) => n + 1)
    // Notify parent (App) to refresh sidebar badge counts
    if (onStatusChange) onStatusChange()
  }

  const lowConfCount =
    workView === 'decision'
      ? counts.decisionLowConf
      : workView === 'approval'
        ? counts.approvalLowConf
        : counts.actionRequiredLowConf

  if (mode === 'case') return caseId ? <CaseWorkspace emailId={caseId} model={model} onBack={onBack} onResolvedChange={caseStatusChanged} /> : null

  return <div className={`workspace-page ${mode === 'review' ? 'review-page' : ''}`}>
    {mode === 'queue' ? <>
      <div className="metric-grid four queue-summary-grid">
        <Metric icon="file" tone="blue" label="Processed cases" value={counts.all} sub="Across completed runs"/>
        <Metric icon="alert" tone="amber" label="Action required" value={counts.actionRequired} sub={`${counts.needsDecision} decisions · ${counts.readyApproval} approvals`}/>
        <Metric icon="check" tone="green" label="No action needed" value={counts.noAction} sub="Settled automatically by the system"/>
        <Metric icon="check" tone="violet" label="Handled" value={counts.handled} sub="Completed by operators"/>
      </div>
    </> : <>
      <div className="metric-grid three">
        <Metric icon="alert" tone="red" label="Needs judgement" value={counts.reviewAll} sub="Total cases requiring review"/>
        <Metric icon="x" tone="amber" label="Field mismatches" value={counts.reviewMismatch} sub="SI and BL document discrepancies"/>
        <Metric icon="file" tone="violet" label="Blockers / Incomplete" value={counts.reviewNeedsReview} sub="Missing attachments, unreadable, or blank"/>
      </div>
    </>}

    {mode === 'queue' && (
      <div className="queue-status-panel">
        <div className="queue-stage-tabs" role="tablist" aria-label="Case status">
          {([
            { key: 'action_required', label: 'Action required', count: counts.actionRequired, note: 'Waiting for your team', icon: 'alert' },
            { key: 'no_action', label: 'No action needed', count: counts.noAction, note: 'Settled by the system', icon: 'check' },
            { key: 'handled', label: 'Handled', count: counts.handled, note: 'Closed by operators', icon: 'user' },
          ] as const).map((item) => (
            <button
              key={item.key}
              role="tab"
              aria-selected={queueStage === item.key}
              className={`queue-stage-tab stage-${item.key} ${queueStage === item.key ? 'active' : ''}`}
              onClick={() => { setQueueStage(item.key); setWorkView('all'); setCaseType('all'); setPage(1) }}
            >
              <div className="queue-stage-left">
                <div className={`queue-stage-icon stage-icon-${item.key}`}>
                  <Icon name={item.icon} size={15} />
                </div>
                <div className="queue-stage-copy">
                  <strong className="queue-stage-title">{item.label}</strong>
                  <small className="queue-stage-note">{item.note}</small>
                </div>
              </div>
              <b className="queue-stage-count">{item.count.toLocaleString()}</b>
            </button>
          ))}
        </div>

        {queueStage === 'action_required' && (
          <div className="queue-work-bar">
            <div className="queue-work-left">
              <span className="queue-work-label">
                <Icon name="sliders" size={13} />
                <span>Work stream</span>
              </span>
              <div className="queue-work-pills" role="tablist" aria-label="Required work">
                {([
                  { key: 'all', label: 'All work', count: counts.actionRequired, tone: 'default' },
                  { key: 'decision', label: 'Needs decision', count: counts.needsDecision, tone: 'decision' },
                  { key: 'approval', label: 'Ready to approve', count: counts.readyApproval, tone: 'approval' },
                ] as const).map((item) => (
                  <button
                    key={item.key}
                    role="tab"
                    aria-selected={workView === item.key}
                    className={`queue-work-pill pill-${item.tone} ${workView === item.key ? 'active' : ''}`}
                    onClick={() => { setWorkView(item.key); setCaseType('all'); setPage(1) }}
                  >
                    <span className="pill-title">{item.label}</span>
                    <span className="pill-count">{item.count.toLocaleString()}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="queue-work-meta">
              {workView === 'all' && (
                <span className="work-meta-text">
                  <Icon name="info" size={13} />
                  <span>Showing all <strong>{counts.actionRequired}</strong> pending cases waiting for review</span>
                </span>
              )}
              {workView === 'decision' && (
                <span className="work-meta-text">
                  <Icon name="alert" size={13} />
                  <span><strong>{counts.mismatch}</strong> discrepancies · <strong>{counts.needs_review}</strong> blockers needing review</span>
                </span>
              )}
              {workView === 'approval' && (
                <span className="work-meta-text">
                  <Icon name="check" size={13} />
                  <span><strong>{counts.ok}</strong> AI auto-cleared · <strong>{counts.acknowledge}</strong> draft inquiries</span>
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    )}

    <div className={`queue-toolbar ${mode === 'queue' ? 'queue-controls' : ''}`}>
      {mode === 'review' ? <div className="filter-pills">
        {filterList.map((item) => (
          <button key={item.key} className={filter === item.key ? 'active' : ''} onClick={() => { setFilter(item.key); setPage(1) }}>
            {item.label} <span>{item.count}</span>
          </button>
        ))}
      </div> : <div className="queue-refine">
        <span>Showing <strong>{queueStage === 'action_required' ? 'cases that need action' : queueStage === 'no_action' ? 'cases needing no action' : 'handled cases'}</strong></span>
        {queueStage === 'action_required' && <label className="queue-type-filter">
          <span>Case type</span>
          <div className="select-wrap">
            <select value={caseType} onChange={(e) => { setCaseType(e.target.value as CaseType); setPage(1) }} aria-label="Filter by case type">
              <option value="all">All types</option>
              {workView !== 'approval' && <option value="mismatch">Mismatch ({counts.mismatch})</option>}
              {workView !== 'approval' && <option value="blocker">Blocker / incomplete ({counts.needs_review})</option>}
              {workView !== 'decision' && <option value="auto_clear">AI auto-cleared ({counts.ok})</option>}
              {workView !== 'decision' && <option value="inquiry">Inquiry / request ({counts.acknowledge})</option>}
              {lowConfCount > 0 && <option value="low_confidence">Low confidence ({lowConfCount})</option>}
            </select>
            <Icon name="chevron" size={13} className="select-chevron"/>
          </div>
        </label>}
        {queueStage === 'no_action' && <label className="queue-type-filter">
          <span>Category</span>
          <div className="select-wrap">
            <select value={caseType} onChange={(e) => { setCaseType(e.target.value as CaseType); setPage(1) }} aria-label="Filter by category">
              <option value="all">All types</option>
              <option value="general">General notices ({counts.noActionGeneral})</option>
              <option value="spam">Spam / noise ({counts.noActionSpam})</option>
              {counts.noActionLowConf > 0 && <option value="low_confidence">Low confidence ({counts.noActionLowConf})</option>}
            </select>
            <Icon name="chevron" size={13} className="select-chevron"/>
          </div>
        </label>}
      </div>}
      <div className="queue-tools">
        <label className="compact-search">
          <Icon name="search" size={15}/>
          <input
            value={localSearch}
            onChange={(e) => { setLocalSearch(e.target.value); setPage(1) }}
            placeholder="Search cases or customer..."
            aria-label="Search queue"
          />
        </label>
        <div className="select-wrap">
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }} aria-label="Sort cases">
            <option value="latest">Latest case ID</option>
            <option value="oldest">Oldest case ID</option>
            <option value="priority">Priority</option>
            <option value="customer">Customer</option>
            <option value="confidence">Lowest classification confidence</option>
          </select>
          <Icon name="chevron" size={13} className="select-chevron"/>
        </div>
      </div>
    </div>

    {error ? <div className="empty-panel"><Icon name="alert" size={28}/><h3>Could not load cases</h3><p>{error}</p></div> : loading ? <div className="empty-panel"><div className="loading-ring"/><p>Loading cases…</p></div> : emails.length === 0 ? <div className="empty-panel"><Icon name="queue" size={32}/><h3>No cases yet</h3><p>New processed emails will appear here automatically.</p></div> : mode === 'review' ? <div className="review-layout"><div className="review-list panel-card"><ReviewList rows={rows} onSelect={setReviewId} selectedId={reviewId}/><Pagination page={currentPage} pages={pages} count={visible.length} size={pageSize} setPage={setPage}/></div><div className="review-detail panel-card">{reviewId ? <CaseWorkspace emailId={reviewId} model={model} compact onOpenFull={() => onOpenCase?.(reviewId)} onResolvedChange={caseStatusChanged} /> : <div className="empty-panel">Select a case to review</div>}</div></div> : <div className="panel-card queue-table-wrap"><QueueTable rows={rows} mode="queue" onSelect={(id) => onOpenCase?.(id)} onSort={(key) => {
      setPage(1)
      if (key === 'case') {
        setSort((prev) => (prev === 'latest' ? 'oldest' : 'latest'))
      } else {
        setSort(key)
      }
    }} currentSort={sort}/><Pagination page={currentPage} pages={pages} count={visible.length} size={pageSize} setPage={setPage}/></div>}
  </div>
}

function Metric({ icon, tone, label: name, value, sub }: { icon: string; tone: string; label: string; value: number; sub: string }) {
  return (
    <div className={`metric-card tone-${tone}`}>
      <div className="metric-avatar">
        <Icon name={icon} size={20}/>
      </div>
      <div className="metric-info">
        <strong className="metric-val">{value.toLocaleString()}</strong>
        <span className="metric-label">{name}</span>
        <small className="metric-sub">{sub}</small>
      </div>
    </div>
  )
}

function QueueTable({ rows, mode, onSelect, onSort, currentSort }: { rows: EmailSummary[]; mode: 'queue' | 'review'; onSelect: (id: string) => void; onSort?: (key: string) => void; currentSort?: string }) {
  if (!rows.length) return <div className="empty-panel"><Icon name="search" size={28}/><h3>No matching cases</h3><p>Try a different search or filter.</p></div>
  return <div className="table-scroll"><table className="case-table"><thead><tr>
    <th
      className="col-case-id"
      onClick={() => onSort?.('case')}
      style={{ cursor: onSort ? 'pointer' : 'default', userSelect: 'none' }}
      title={currentSort === 'latest' ? 'Sorted by newest first (click for oldest)' : currentSort === 'oldest' ? 'Sorted by oldest first (click for newest)' : 'Sort by Case ID'}
    >
      Case ID <span className="sort-arrows">{currentSort === 'latest' ? '↓' : currentSort === 'oldest' ? '↑' : '↑↓'}</span>
    </th>
    <th
      onClick={() => onSort?.('customer')}
      style={{ cursor: onSort ? 'pointer' : 'default', userSelect: 'none' }}
      title="Sort by Customer"
    >
      Customer <span className="sort-arrows">{currentSort === 'customer' ? '↓' : '↑↓'}</span>
    </th>
    <th>Latest email</th>
    {mode === 'queue' && <th>Attachments</th>}
    {mode === 'queue' && <th>Task / intent</th>}
    <th>AI result</th>
    <th>Next step</th>
    <th>Classification</th>
    <th aria-label="Open"/>
  </tr></thead><tbody>{rows.map((e) => {
    const cust = getCustomer(e)
    return <tr key={e.email_id} onClick={() => onSelect(e.email_id)}>
      <td className="col-case-id"><span className="case-link">{label(e.email_id)}</span></td>
      <td>
        <div className="customer-cell">
          {cust.name ? (
            <>
              <span className="customer-name" title={cust.name}>{cust.name}</span>
              <small className="customer-email" title={cust.email}>{cust.email}</small>
            </>
          ) : (
            <span className="customer-email single" title={cust.email}>{cust.email || '—'}</span>
          )}
        </div>
      </td>
      <td><span className="email-subject" title={e.subject}>{e.subject}</span><small className="table-sub">{shipment(e.subject)} · {formatTime(e.total_ms)}</small></td>
      {mode === 'queue' && (
        <td>
          <div className="table-attachments">
            {e.attachments && e.attachments.length > 0 ? (
              e.attachments.map((a) => (
                <span key={a} className="table-att-pill" title={a}>
                  <Icon name="file" size={12}/>
                  <span className="att-name">{a}</span>
                </span>
              ))
            ) : (
              <span className="muted table-att-none">—</span>
            )}
          </div>
        </td>
      )}
      {mode === 'queue' && <td><CategoryBadge value={e.category}/></td>}
      <td>{e.comparison_status ? <StatusBadge value={e.comparison_status}/> : <span className="muted">—</span>}</td>
      <td>{e.resolved ? <span className="handled-status"><Icon name="check" size={12}/>Handled</span> : <ActionBadge value={e.action}/>}</td>
      <td><ClassificationSignal email={e}/></td>
      <td><Icon name="right" size={17}/></td>
    </tr>
  })}</tbody></table></div>
}

function ClassificationSignal({ email }: { email: EmailSummary }) {
  const routing = email.classification_routing
  const usedFallback = Boolean(routing?.fallback_used || email.escalated)
  const finalPercent = Math.round((email.confidence ?? 0) * 100)

  if (usedFallback) {
    const jevPercent = routing?.primary_confidence == null
      ? null
      : Math.round(routing.primary_confidence * 100)
    const routeLabel = jevPercent == null
      ? 'Jev uncertain → Gemini reviewed'
      : `Jev ${jevPercent}% → Gemini reviewed`

    return (
      <span
        className="classification-signal fallback"
        title={`Jev routed this classification to Gemini. Gemini self-reported ${finalPercent}% confidence.`}
      >
        <strong>Gemini fallback</strong>
        <small>{routeLabel}</small>
      </span>
    )
  }

  const source = routing?.primary === 'gemini' ? 'Gemini' : 'Jev'
  return (
    <span
      className="classification-signal direct"
      title={`${source} classified the email directly. This score describes the email category, not the complete case.`}
    >
      <strong>{source} · {finalPercent}%</strong>
      <small>Direct classification</small>
    </span>
  )
}

function formatBlockerTag(blocker: string) {
  const b = blocker.toLowerCase()
  if (b.includes('wrong_doc_type') || b.includes('wrong document')) return 'Wrong Document'
  if (b.includes('missing_attachment') || b.includes('attachment')) return 'Missing Attachment'
  if (b.includes('unreadable') || b.includes('scan')) return 'Unreadable Scan'
  if (b.includes('missing_value') || b.includes('blank')) return 'Blank Fields'
  return 'Needs Review'
}

function ReviewList({ rows, onSelect, selectedId }: { rows: EmailSummary[]; onSelect: (id: string) => void; selectedId: string | null }) {
  if (!rows.length) return <div className="empty-panel">No matching review cases.</div>
  return <div className="review-case-list">
    <div className="review-list-head">
      <span>Case</span>
      <span>Company</span>
      <span style={{ textAlign: 'right' }}>Result</span>
    </div>
    {rows.map((e) => {
      const cust = getCustomer(e)
      const companyName = cust.name || cust.email || 'Unknown Customer'
      const companySub = cust.name ? (cust.email || e.subject) : e.subject
      const isMismatch = e.comparison_status === 'MISMATCH'
      const issueTag = isMismatch ? 'SI & BL Disagree' : (e.blockers && e.blockers[0] ? formatBlockerTag(e.blockers[0]) : 'Needs Review')

      return <button
        key={e.email_id}
        className={selectedId === e.email_id ? 'selected' : ''}
        onClick={() => onSelect(e.email_id)}
        title={`Case ${label(e.email_id)} · ${companyName} · Subject: ${e.subject}`}
      >
        <span className="review-case-cell">
          <strong className="case-link">{label(e.email_id)}</strong>
        </span>
        <span className="review-company-cell">
          <strong className="company-name" title={companyName}>{companyName}</strong>
          <small className="company-sub" title={companySub}>{companySub}</small>
        </span>
        <span className="review-result-cell">
          <StatusBadge value={e.comparison_status ?? 'NEEDS_REVIEW'}/>
          <span className={`issue-tag ${isMismatch ? 'mismatch-tag' : 'blocker-tag'}`}>
            {issueTag}
          </span>
        </span>
      </button>
    })}
  </div>
}

function Pagination({ page, pages, count, size, setPage }: { page: number; pages: number; count: number; size: number; setPage: (value: number) => void }) {
  return <div className="table-footer"><span>Showing {count ? (page - 1) * size + 1 : 0}–{Math.min(page * size, count)} of {count} cases</span><div><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} aria-label="Previous page"><Icon name="left" size={16}/></button><span>Page {page} of {pages}</span><button onClick={() => setPage(Math.min(pages, page + 1))} disabled={page === pages} aria-label="Next page"><Icon name="right" size={16}/></button></div></div>
}

function formatTime(ms: number) { return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms` }
