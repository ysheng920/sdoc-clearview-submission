import { useEffect, useState } from 'react'
import { api } from '../api'
import type { EmailRecord, FieldVerdict } from '../types'
import { CategoryBadge, StatusBadge } from './Badges'
import { EvidenceHighlight, DualDocComparison } from './EvidenceHighlight'
import { FieldCorrection } from './FieldCorrection'
import { CategoryCorrection, ResolveControl } from './CaseCorrections'
import { Icon } from './Icon'
import { PipelineTimeline } from './PipelineTimeline'
import { label, getCustomer } from '../pages/Inbox'
import { formatFriendlyBlocker, formatFriendlyRule, formatMalaysiaTime } from '../formatters'

type Tab = 'overview' | 'documents' | 'history'
const fieldName = (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function CaseWorkspace({ emailId, onBack, compact = false, onOpenFull, model, onResolvedChange }: { emailId: string; onBack?: () => void; compact?: boolean; onOpenFull?: () => void; model?: string; onResolvedChange?: (resolved: boolean) => void }) {
  const [record, setRecord] = useState<EmailRecord | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('overview')
  const [field, setField] = useState<string | null>(null)
  const [docFilter, setDocFilter] = useState<'all' | 'si' | 'bl'>('all')
  const [docLayout, setDocLayout] = useState<'split' | 'stacked'>('split')

  useEffect(() => {
    let active = true
    setRecord(null); setError(''); setTab('overview')
    api.email(emailId, model).then((r) => { if (active) { setRecord(r); setField(r.comparison?.defect_fields[0] ?? r.comparison?.missing_fields[0] ?? Object.keys(r.comparison?.detail ?? {})[0] ?? null) } }).catch((e) => active && setError(String(e)))
    return () => { active = false }
  }, [emailId, model])

  if (error) return <div className="empty-panel"><Icon name="alert" size={30}/><h3>Could not open case</h3><p>{error}</p></div>
  if (!record) return <div className="empty-panel"><div className="loading-ring"/><p>Loading case…</p></div>
  const comparison = record.comparison
  const selected = field ? comparison?.detail[field] : null
  const caseId = label(record.email_id)
  const title = `Case ${caseId}`
  const cust = getCustomer(record)

  return <div className={`case-workspace ${compact ? 'compact-case' : ''}`}>
    <div className="case-header">
      {!compact && <button className="text-link back-link" onClick={onBack}><Icon name="arrow" size={16}/>Back to Work Queue</button>}
      <div className="case-heading-line">
        <h1>{title}</h1>
        <div className="case-heading-badges"><CategoryBadge value={record.classification.category}/><StatusBadge value={comparison?.status ?? null}/>{!compact && <CategoryCorrection record={record} onRecord={setRecord}/>}</div>
        <div className="case-heading-actions">
          <ResolveControl record={record} onRecord={setRecord} onResolvedChange={onResolvedChange}/>
          {compact && <button className="secondary-action open-case" onClick={onOpenFull}>Open workspace <Icon name="right" size={15}/></button>}
        </div>
      </div>
      {!compact && (
        <div className="case-meta">
          <div className="case-meta-item">
            <span className="case-meta-icon"><Icon name="user" size={21}/></span>
            <div className="case-meta-content">
              <span className="case-meta-label">Customer</span>
              <strong className="case-meta-value">{cust.name || cust.email || '—'}</strong>
            </div>
          </div>
          <div className="case-meta-item">
            <span className="case-meta-icon"><Icon name="mail" size={21}/></span>
            <div className="case-meta-content">
              <span className="case-meta-label">From</span>
              <strong className="case-meta-value">{cust.email || record.from || '—'}</strong>
            </div>
          </div>
          <div className="case-meta-item">
            <span className="case-meta-icon"><Icon name="layers" size={21}/></span>
            <div className="case-meta-content">
              <span className="case-meta-label">Attachments</span>
              <strong className="case-meta-value">{record.attachments.length} file{record.attachments.length === 1 ? '' : 's'}</strong>
            </div>
          </div>
          <div className="case-meta-item">
            <span className="case-meta-icon"><Icon name="clock" size={21}/></span>
            <div className="case-meta-content">
              <span className="case-meta-label">Processing</span>
              <strong className="case-meta-value">{record.total_ms.toFixed(0)} ms</strong>
            </div>
          </div>
          <div className="case-meta-item">
            <span className="case-meta-icon"><Icon name="user" size={21}/></span>
            <div className="case-meta-content">
              <span className="case-meta-label">Human approval</span>
              <strong className="case-meta-value">{record.decision.needs_approval ? 'Required: Yes' : 'No'}</strong>
            </div>
          </div>
        </div>
      )}
    </div>
    <div className="page-tabs">{(['overview','documents','history'] as Tab[]).map((name) => <button key={name} className={tab === name ? 'active' : ''} onClick={() => setTab(name)}>{name === 'overview' ? (compact ? 'Review' : 'Overview') : name === 'documents' ? 'Documents & evidence' : 'Decision trace'}</button>)}</div>

    {tab === 'overview' && <div className="case-columns">
      <div className="case-col-left">
        {record.blockers.length > 0 && (
          <div className="notice amber case-blocker-banner">
            <Icon name="alert" size={18}/>
            <div>
              <strong>Manual verification needed</strong>
              <p>{record.blockers.map(formatFriendlyBlocker).join(' ')}</p>
            </div>
          </div>
        )}
        <section className="panel-card email-context">
          <div className="panel-heading">
            <Icon name="mail" size={20}/>
            <h2>Email & context</h2>
            <span className="email-meta-pill" style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--text-dim)' }}>
              {record.attachments.length} attachment(s)
            </span>
          </div>
          <div className="email-paper">
            <div className="email-paper-top">
              <strong>Original email</strong>
              <span>{record.from}</span>
            </div>
            <dl>
              <dt>Customer</dt><dd>{cust.name || '—'}</dd>
              <dt>From</dt><dd>{record.from}</dd>
              <dt>Subject</dt><dd>{record.subject}</dd>
            </dl>
            <pre>{record.body}</pre>
          </div>
          {record.attachments.length > 0 && (
            <div className="attachment-list">
              <h3>Attachments ({record.attachments.length})</h3>
              <div className="attachment-items">
                {record.attachments.map((a) => (
                  <span key={a} className="attachment-chip"><Icon name="file" size={15}/>{a}</span>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      <section className="panel-card verification-panel"><div className="panel-heading"><Icon name="file" size={21}/><h2>{compact ? 'Field review' : 'Verification workspace'}</h2></div>
        {comparison ? <>
          <div className="verification-table-wrap"><table className="verification-table"><thead><tr><th>Field</th><th>Shipping Instruction</th><th>Bill of Lading</th><th>Result</th></tr></thead><tbody>{Object.entries(comparison.detail).map(([name, item]) => <tr key={name} className={`${item.status === 'MISMATCH' ? 'mismatch-row' : item.status === 'MISSING' ? 'missing-row' : ''} ${field === name ? 'focused-row' : ''}`} onClick={() => setField(name)}><th>{fieldName(name)}</th><td title={item.si.raw ?? undefined}>{item.si.raw?.trim() ? item.si.raw : <span className="cell-missing-text">Missing</span>}</td><td title={item.bl.raw ?? undefined}>{item.bl.raw?.trim() ? item.bl.raw : <span className="cell-missing-text">Missing</span>}</td><td><StatusBadge value={item.status}/></td></tr>)}</tbody></table></div>
          {selected && field && <div className="field-detail"><div className="field-detail-head"><StatusBadge value={selected.status}/><h3>{fieldName(field)} · evidence</h3><span className={`field-rule-tag ${selected.status === 'MATCH' ? 'ok' : 'bad'}`} title={`Evaluated by deterministic rule: ${selected.rule}`}>{formatFriendlyRule(selected.rule)}</span></div><div className="evidence-pair"><EvidenceValue name="Shipping Instruction" side={selected.si}/><EvidenceValue name="Bill of Lading" side={selected.bl}/></div>
            <FieldCorrection record={record} field={field} verdict={selected} onRecord={setRecord}/>
          </div>}
        </> : <div className="no-comparison"><Icon name="alert" size={24}/><strong>No field comparison was completed</strong><p>{record.blockers.length ? 'Resolve the blocker before the documents can be certified.' : 'This email does not require SI and BL comparison.'}</p></div>}
      </section>

      <section className="panel-card action-panel">
        <div className="panel-heading">
          <Icon name={compact ? "mail" : "spark"} size={21}/>
          <h2>{compact ? 'Draft reply' : 'Next action'}</h2>
          {compact && record.decision.draft && (
            <span style={{ marginLeft: 'auto', color: '#a56305', background: '#fff2db', borderRadius: '5px', fontSize: '10px', padding: '2px 7px', fontWeight: 700 }}>
              Not sent
            </span>
          )}
        </div>
        {compact ? (
          record.decision.draft ? (
            <div className="draft-card-body">
              <div className="draft-meta-bar">
                <dl>
                  <dt>To</dt><dd>{record.decision.draft.to}</dd>
                  <dt>Subject</dt><dd>{record.decision.draft.subject}</dd>
                </dl>
              </div>
              <pre className="draft-email-text">{record.decision.draft.body}</pre>
              <div className="draft-action-footer">
                <a className="primary-action download-action" href={api.draftUrl(record.email_id)} download={`${record.email_id}.eml`}>
                  <Icon name="download" size={16}/>Download .eml
                </a>
                <p className="small muted">Open and send from your own mail client after checking the draft.</p>
              </div>
            </div>
          ) : (
            <div className="empty-panel" style={{ minHeight: '90px', padding: '16px' }}>
              <p className="muted">No draft reply is required for this case.</p>
            </div>
          )
        ) : (
          record.decision.draft ? (
            <div className="draft-preview">
              <div className="draft-preview-head">
                <Icon name="mail" size={18}/>
                <h3>Draft reply</h3>
                <span>Not sent</span>
              </div>
              <dl>
                <dt>To</dt><dd>{record.decision.draft.to}</dd>
                <dt>Subject</dt><dd>{record.decision.draft.subject}</dd>
              </dl>
              <pre>{record.decision.draft.body}</pre>
              <a className="primary-action download-action" href={api.draftUrl(record.email_id)} download={`${record.email_id}.eml`}>
                <Icon name="download" size={16}/>Download .eml
              </a>
              <p className="small muted">Open and send from your own mail client after checking the draft.</p>
            </div>
          ) : (
            <div className="empty-panel" style={{ minHeight: '90px', padding: '16px' }}>
              <p className="muted">No draft reply is required for this case.</p>
            </div>
          )
        )}
      </section>
    </div>}

    {tab === 'documents' && (
      <div className={`documents-view ${docLayout === 'stacked' ? 'stacked' : ''}`}>
        {(record.documents.si || record.documents.bl) && (
          <div className="documents-toolbar">
            <div className="doc-filter-pills">
              <span className="toolbar-label">Doc:</span>
              {record.documents.si && record.documents.bl && (
                <button
                  className={`filter-pill ${docFilter === 'all' ? 'active' : ''}`}
                  onClick={() => setDocFilter('all')}
                >
                  All (2)
                </button>
              )}
              {record.documents.si && (
                <button
                  className={`filter-pill ${docFilter === 'si' ? 'active' : ''}`}
                  onClick={() => setDocFilter('si')}
                >
                  <Icon name="file" size={13} /> Shipping Instruction (SI)
                </button>
              )}
              {record.documents.bl && (
                <button
                  className={`filter-pill ${docFilter === 'bl' ? 'active' : ''}`}
                  onClick={() => setDocFilter('bl')}
                >
                  <Icon name="file" size={13} /> Bill of Lading (BL)
                </button>
              )}
            </div>

            <div className="doc-layout-toggles">
              <button
                className={`layout-btn ${docLayout === 'split' ? 'active' : ''}`}
                onClick={() => setDocLayout('split')}
                title="Side-by-side view"
              >
                <Icon name="layers" size={13} /> Side-by-side
              </button>
              <button
                className={`layout-btn ${docLayout === 'stacked' ? 'active' : ''}`}
                onClick={() => setDocLayout('stacked')}
                title="Full width stacked view"
              >
                <Icon name="file" size={13} /> Stacked
              </button>
            </div>
          </div>
        )}

        {docFilter === 'all' && record.documents.si && record.documents.bl && comparison?.detail && (
          <div className="doc-field-bar">
            <span className="doc-field-bar-label">Compare fields:</span>
            <div className="doc-field-pills">
              {Object.entries(comparison.detail).map(([name, item]) => {
                const status = item.status
                const isMismatch = status === 'MISMATCH'
                const isMissing = status === 'MISSING'
                const isActive = field === name
                const badgeLabel = isMismatch ? 'DIFF' : isMissing ? 'MISSING' : 'MATCH'
                const badgeClass = isMismatch ? 'diff' : isMissing ? 'missing' : 'match'
                return (
                  <button
                    key={name}
                    className={`field-pill-item ${isActive ? 'active' : ''} ${badgeClass}`}
                    onClick={() => setField(isActive ? null : name)}
                    title={`Click to focus ${fieldName(name)} evidence in both docs (${status})`}
                  >
                    <span className="field-pill-name">{fieldName(name)}</span>
                    <span className={`field-pill-badge ${badgeClass}`}>
                      {badgeLabel}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {docFilter === 'all' && record.documents.si && record.documents.bl ? (
          <DualDocComparison
            si={record.documents.si}
            bl={record.documents.bl}
            defectFields={[...(comparison?.defect_fields ?? []), ...(comparison?.missing_fields ?? [])]}
            activeField={field}
            onPick={setField}
            traces={record.traces}
          />
        ) : (
          <>
            {(docFilter === 'all' || docFilter === 'si') && record.documents.si && (
              <EvidenceHighlight
                doc={record.documents.si}
                defectFields={[...(comparison?.defect_fields ?? []), ...(comparison?.missing_fields ?? [])]}
                activeField={field}
                onPick={setField}
                traces={record.traces}
              />
            )}
            {(docFilter === 'all' || docFilter === 'bl') && record.documents.bl && (
              <EvidenceHighlight
                doc={record.documents.bl}
                defectFields={[...(comparison?.defect_fields ?? []), ...(comparison?.missing_fields ?? [])]}
                activeField={field}
                onPick={setField}
                traces={record.traces}
              />
            )}
          </>
        )}
        {!record.documents.si && !record.documents.bl && (
          <div className="empty-panel">No SI or BL document was extracted for this case.</div>
        )}
      </div>
    )}
    {tab === 'history' && (
      <div className="decision-trace-layout">
        <div className="trace-main-column">
          <PipelineTimeline
            record={record}
            onShowDocuments={() => setTab('documents')}
            onShowOverview={() => setTab('overview')}
          />
        </div>
        <aside className="trace-sidebar-column">
          <div className="panel-card outcome-card">
            <div className="panel-heading">
              <Icon name="flag" size={19} className="text-blue" />
              <h2>Case Outcome</h2>
            </div>
            <div className="outcome-section">
              <span className="outcome-label">Final action</span>
              <div className="outcome-action-pill">
                {record.decision.action === 'FLAG_DISCREPANCY'
                  ? 'Ask customer to resolve differences'
                  : record.decision.action.replace(/_/g, ' ')}
              </div>
            </div>
            <div className="outcome-section">
              <span className="outcome-label">Reason summary</span>
              <p className="outcome-reason">
                {record.decision.why}
              </p>
            </div>
            <div className="outcome-section">
              <span className="outcome-label">Human approval</span>
              <div className="outcome-approval-pill">
                <Icon name="user" size={15} />
                <span>{record.decision.needs_approval ? 'Required before sending' : 'No approval needed'}</span>
              </div>
            </div>
          </div>

          <div className="panel-card feedback-card quick-actions-card">
            <div className="panel-heading">
              <Icon name="zap" size={19} className="text-blue" />
              <h2>Quick actions</h2>
            </div>
            <div className="quick-action-list">
              <button onClick={() => setTab('overview')}>
                <Icon name="mail" size={15} />
                {record.decision.draft ? 'View draft reply' : 'Back to overview'}
              </button>
              <button onClick={() => setTab('documents')}>
                <Icon name="file" size={15} />
                Open documents ({record.attachments.length})
              </button>
            </div>
          </div>

          <div className="panel-card feedback-card">
            <div className="panel-heading">
              <Icon name="chat" size={19} className="text-blue" />
              <h2>Human feedback</h2>
            </div>
            <div className="feedback-body">
              {record.feedback.length ? (
                record.feedback.map((f) => (
                  <div className="feedback-event" key={f.id}>
                    <strong>{f.kind}{f.target ? ` · ${fieldName(f.target)}` : ''}</strong>
                    <span className="feedback-time">{formatMalaysiaTime(f.created_at)}</span>
                    <p>{f.was ?? '—'} → {f.corrected_to}</p>
                    {f.note && <small>{f.note}</small>}
                  </div>
                ))
              ) : (
                <p className="muted">No corrections have been recorded for this case.</p>
              )}
            </div>
          </div>
        </aside>
      </div>
    )}
  </div>
}

function EvidenceValue({ name, side }: { name: string; side: FieldVerdict['si'] }) {
  const isMissing = !side.raw || !side.raw.trim()
  return (
    <div>
      <span>{name}</span>
      {isMissing ? (
        <strong className="cell-missing-text">Missing</strong>
      ) : (
        <strong>{side.raw}</strong>
      )}
      <small>Normalized: {side.value ?? '—'}</small>
      <small>Source: {side.source}</small>
    </div>
  )
}
