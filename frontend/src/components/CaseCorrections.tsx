import { useState } from 'react'
import { api } from '../api'
import type { EmailRecord } from '../types'
import { Icon } from './Icon'

/**
 * The three corrections that are about the case as a whole rather than one field.
 *
 * Each sits next to the thing it disputes -- the category beside the category
 * badge, the review reason inside the blocker that states it, the close beside
 * the recommended action -- because a reviewer disagrees while looking at the
 * claim, and a control anywhere else asks them to carry it across the page.
 *
 * All three are per-case overrides: they change what this email shows and
 * nothing else. None of them touch a rule.
 */
const CATEGORIES = ['BL_COMPARISON', 'SI_REQUEST', 'INVOICE_QUERY', 'GENERAL', 'SPAM']

const CATEGORY_NAMES: Record<string, string> = {
  BL_COMPARISON: 'BL Comparison',
  SI_REQUEST: 'SI Request',
  INVOICE_QUERY: 'Invoice Query',
  GENERAL: 'General',
  SPAM: 'Spam',
}

/** The four ways a document pair can fail to be certifiable at all. */
const REVIEW_REASONS = ['wrong_doc_type', 'missing_attachment', 'unreadable', 'missing_value']

const REVIEW_REASON_NAMES: Record<string, string> = {
  missing_value: 'Missing Field Value',
  wrong_doc_type: 'Wrong Document Type Attached',
  missing_attachment: 'Missing Attachment',
  unreadable: 'Unreadable Document / Scan',
}

function useSave(record: EmailRecord, onRecord: (r: EmailRecord) => void,
                 onSaved?: (r: EmailRecord) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(payload: Parameters<typeof api.sendFeedback>[1]) {
    setBusy(true)
    setError('')
    try {
      const next = (await api.sendFeedback(record.email_id, payload)).record
      onRecord(next)
      onSaved?.(next)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, save }
}

export function CategoryCorrection({ record, onRecord }: {
  record: EmailRecord
  onRecord: (r: EmailRecord) => void
}) {
  const { busy, error, save } = useSave(record, onRecord)
  const corrected = record.feedback?.some((f) => f.kind === 'category')
  return (
    <div className="category-override-pill">
      <span className="category-override-label">
        <Icon name="edit" size={12} />
        <span>Reclassify:</span>
      </span>
      <div className="category-select-wrap">
        <select
          value={record.classification.category}
          disabled={busy}
          onChange={(e) => save({ kind: 'category', corrected_to: e.target.value })}
          title="Manually override email category classification"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_NAMES[c] ?? c.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <Icon name="chevron" size={12} className="select-chevron-icon" />
      </div>
      {corrected && (
        <span className="correction-tag" title="Category was manually adjusted">
          <Icon name="user" size={11} /> Manual
        </span>
      )}
      {error && <span className="correction-error">{error}</span>}
    </div>
  )
}

/**
 * Which kind of unfinishable this is. It reads as a detail, but it is the whole
 * of the edge-case score and it tells the operator what to chase -- a missing
 * attachment is an email to the customer, an unreadable scan is a person with
 * the paper copy.
 */
export function ReviewReasonCorrection({ record, onRecord }: {
  record: EmailRecord
  onRecord: (r: EmailRecord) => void
}) {
  const { busy, error, save } = useSave(record, onRecord)
  const current = record.review_reason_override
    ?? REVIEW_REASONS.find((r) => record.blockers.join(' ').includes(r))
    ?? ''
  return (
    <div className="blocker-dispute-row">
      <span className="blocker-dispute-label">
        <Icon name="sliders" size={12} />
        <span>Dispute / Override reason:</span>
      </span>
      <div className="blocker-dispute-select-wrap">
        <select
          value={current}
          disabled={busy}
          onChange={(e) => save({ kind: 'review_reason', corrected_to: e.target.value })}
          title="Change the recorded reason for manual review"
        >
          <option value="" disabled>Choose reason…</option>
          {REVIEW_REASONS.map((r) => (
            <option key={r} value={r}>
              {REVIEW_REASON_NAMES[r] ?? r.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <Icon name="chevron" size={12} className="select-chevron-icon" />
      </div>
      {record.review_reason_override && (
        <span className="dispute-manual-badge" title="Dispute reason manually set">
          <Icon name="user" size={11} /> Manually set
        </span>
      )}
      {error && <span className="correction-error">{error}</span>}
    </div>
  )
}

/**
 * Closing a case. Without it `needs_judgement` is a property of the machine's
 * output rather than a state anyone can leave, so the review queue never empties
 * however much work gets done.
 */
export function ResolveControl({ record, onRecord, onResolvedChange }: {
  record: EmailRecord
  onRecord: (r: EmailRecord) => void
  onResolvedChange?: (resolved: boolean) => void
}) {
  const { busy, error, save } = useSave(
    record, onRecord, (next) => onResolvedChange?.(Boolean(next.resolved)),
  )
  if (record.resolved) {
    return (
      <div className="resolve-row done">
        <span className="handled-pill">
          <Icon name="check" size={14} aria-hidden="true"/>
          <span>Handled</span>
        </span>
        <button
          className="reopen-btn"
          disabled={busy}
          onClick={() => save({ kind: 'resolve', corrected_to: 'reopen' })}
          title="Reopen case to review queue"
        >
          {busy ? 'Reopening…' : 'Reopen'}
        </button>
        {error && <span className="correction-error">{error}</span>}
      </div>
    )
  }
  return (
    <div className="resolve-row">
      <button
        className="mark-handled-btn"
        disabled={busy}
        onClick={() => save({ kind: 'resolve', corrected_to: 'done' })}
        title="Mark case as handled and close from review queue. Nothing is sent — draft remains available."
      >
        <Icon name="check" size={15} aria-hidden="true"/>
        <span>{busy ? 'Saving…' : 'Mark as handled'}</span>
      </button>
      {error && <span className="correction-error">{error}</span>}
    </div>
  )
}
