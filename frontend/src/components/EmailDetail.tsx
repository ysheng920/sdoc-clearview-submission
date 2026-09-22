import { useEffect, useState } from 'react'
import { api } from '../api'
import type { EmailRecord } from '../types'
import { ActionBadge, Badge, CategoryBadge, RouterBadge, StatusBadge } from './Badges'
import { EmailDraft } from './EmailDraft'
import { EvidenceHighlight } from './EvidenceHighlight'
import { FieldDiff } from './FieldDiff'
import { PipelineTimeline } from './PipelineTimeline'
import { formatFriendlyBlocker, formatMalaysiaTime } from '../formatters'

type Tab = 'pipeline' | 'documents' | 'comparison' | 'draft' | 'source'

export function EmailDetail({ emailId, onFeedback }: {
  emailId: string
  onFeedback?: () => void
}) {
  const [record, setRecord] = useState<EmailRecord | null>(null)
  const [tab, setTab] = useState<Tab>('pipeline')
  const [activeField, setActiveField] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRecord(null)
    setError(null)
    setActiveField(null)
    api.email(emailId).then(setRecord).catch((e) => setError(String(e)))
  }, [emailId])

  if (error) return <div className="empty-state">{error}</div>
  if (!record) return <div className="empty-state">Loading {emailId}…</div>

  const { classification: cls, comparison, documents, decision } = record
  const defects = comparison?.defect_fields ?? []
  const hasDocs = Boolean(documents.si || documents.bl)

  const tabs: [Tab, string, boolean][] = [
    ['pipeline', 'Pipeline', true],
    ['documents', 'Documents & evidence', hasDocs],
    ['comparison', 'Comparison', Boolean(comparison)],
    ['draft', 'Drafted reply', Boolean(decision.draft)],
    ['source', 'Email source', true],
  ]
  const visible = tabs.filter(([, , show]) => show)
  const activeTab = visible.some(([t]) => t === tab) ? tab : 'pipeline'

  return (
    <div className="detail-pane">
      <div className="detail-head">
        <h2>{record.subject}</h2>
        <div className="row small" style={{ flexWrap: 'wrap', gap: 8 }}>
          <span className="mono faint">{record.email_id}</span>
          <CategoryBadge value={cls.category} />
          <RouterBadge escalated={cls.escalated} confidence={cls.confidence} />
          <StatusBadge value={comparison?.status ?? null} />
          <ActionBadge value={decision.action} />
          {decision.needs_approval && <Badge tone="warn">needs human approval</Badge>}
          <span className="grow" />
          <span className="mono faint">{record.total_ms}ms total</span>
        </div>
      </div>

      {record.blockers.length > 0 && (
        <div className="banner warn">
          <strong>Blocked:</strong> {record.blockers.map(formatFriendlyBlocker).join(' ')}
        </div>
      )}

      <div className="tabs">
        {visible.map(([t, label]) => (
          <button
            key={t}
            className={activeTab === t ? 'active' : ''}
            onClick={() => setTab(t)}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'pipeline' && <PipelineTimeline record={record} onShowDocuments={() => setTab('documents')} onShowOverview={() => setTab('source')} />}

      {activeTab === 'documents' && (
        <div style={{ display: 'grid', gap: 14 }}>
          {documents.si && (
            <EvidenceHighlight
              doc={documents.si}
              defectFields={defects}
              activeField={activeField}
              onPick={setActiveField}
            />
          )}
          {documents.bl && (
            <EvidenceHighlight
              doc={documents.bl}
              defectFields={defects}
              activeField={activeField}
              onPick={setActiveField}
            />
          )}
        </div>
      )}

      {activeTab === 'comparison' && comparison && <FieldDiff comparison={comparison} />}

      {activeTab === 'draft' && decision.draft && (
        <EmailDraft draft={decision.draft} emailId={record.email_id} />
      )}

      {activeTab === 'source' && (
        <div className="card">
          <h3>Original email</h3>
          <div className="small muted"><strong className="faint">From:</strong> {record.from}</div>
          <div className="small muted" style={{ marginBottom: 10 }}>
            <strong className="faint">Attachments:</strong>{' '}
            {record.attachments.length ? record.attachments.join(', ') : 'none'}
          </div>
          <pre className="doc-text">{record.body}</pre>
        </div>
      )}

      <CorrectionPanel record={record} onSaved={onFeedback} />
    </div>
  )
}

const CATEGORIES = ['BL_COMPARISON', 'SI_REQUEST', 'INVOICE_QUERY', 'GENERAL', 'SPAM']

/**
 * Where a reviewer disagrees with the machine. Corrections are not just logged:
 * they become alias-table suggestions and regression cases (see the Review tab),
 * which is how manual inspection feeds back into the system.
 */
function CorrectionPanel({ record, onSaved }: {
  record: EmailRecord
  onSaved?: () => void
}) {
  const [category, setCategory] = useState(record.classification.category)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const changed = category !== record.classification.category

  async function save() {
    setBusy(true)
    try {
      await api.sendFeedback(record.email_id, {
        kind: 'category',
        was: record.classification.category,
        corrected_to: category,
        note: note || undefined,
      })
      setSaved(true)
      setNote('')
      onSaved?.()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h3>Human review</h3>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="small muted">Correct classification:</span>
        <select value={category} onChange={(e) => { setCategory(e.target.value); setSaved(false) }}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>
        <input
          type="text"
          placeholder="note (optional)"
          value={note}
          style={{ flex: 1, minWidth: 180 }}
          onChange={(e) => setNote(e.target.value)}
        />
        <button className="btn" disabled={!changed || busy} onClick={save}>
          {busy ? 'Saving…' : 'Submit correction'}
        </button>
        {saved && <Badge tone="ok">recorded</Badge>}
      </div>

      {record.feedback?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {record.feedback.map((f) => (
            <div key={f.id} className="small muted">
              <span className="mono faint">{formatMalaysiaTime(f.created_at)}</span>{' '}
              {f.reviewer} changed {f.kind}
              {f.target ? ` (${f.target})` : ''} from <strong>{f.was}</strong> to{' '}
              <strong>{f.corrected_to}</strong>
              {f.note ? ` — ${f.note}` : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
