import { api } from '../api'
import type { Draft } from '../types'
import { Badge, StatusBadge } from './Badges'

/**
 * The drafted reply, shown beside the reasoning that produced it.
 *
 * Nothing here sends mail. The operator reads the reasoning, downloads the .eml
 * and sends it from their own client -- so a machine mistake costs a deleted
 * draft rather than a wrong message to a customer.
 */
export function EmailDraft({ draft, emailId }: { draft: Draft; emailId: string }) {
  const r = draft.reasoning

  return (
    <div className="two-col">
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Drafted reply</h3>
          <span className="grow" />
          <Badge tone="warn">not sent</Badge>
        </div>

        <div className="small muted" style={{ marginBottom: 4 }}>
          <strong className="faint">To:</strong> {draft.to}
        </div>
        <div className="small muted" style={{ marginBottom: 12 }}>
          <strong className="faint">Subject:</strong> {draft.subject}
        </div>

        <pre className="draft-body">{draft.body}</pre>

        <div className="row" style={{ marginTop: 12 }}>
          <a href={api.draftUrl(emailId)} download={`${emailId}.eml`}>
            <button className="btn">Download .eml</button>
          </a>
          <span className="small faint">
            Opens in your mail client. You send it, not the system.
          </span>
        </div>
      </div>

      <div className="card">
        <h3>Why the system wrote this</h3>
        <dl className="reason-grid">
          <dt>Action chosen</dt>
          <dd><Badge tone="accent">{r.action.replace(/_/g, ' ')}</Badge></dd>

          <dt>Basis</dt>
          <dd>{r.basis}</dd>

          <dt>Classified as</dt>
          <dd>
            {r.classified_as}{' '}
            <span className="faint">
              ({Math.round((r.classification_confidence ?? 0) * 100)}% confidence)
            </span>
          </dd>

          <dt>Classifier said</dt>
          <dd className="muted">{r.classification_reason || '—'}</dd>

          <dt>Escalated to cloud</dt>
          <dd>{r.escalated_to_larger_model ? 'yes' : 'no — handled locally'}</dd>

          <dt>Comparison</dt>
          <dd>
            <StatusBadge value={r.comparison_status} />
            {r.comparison_method && <div className="small faint">{r.comparison_method}</div>}
          </dd>
        </dl>

        {r.evidence.length > 0 && (
          <>
            <h3 style={{ marginTop: 18 }}>Evidence cited in the draft</h3>
            {r.evidence.map((e) => (
              <div key={e.field} className="diff-row" style={{ gridTemplateColumns: '130px 1fr 1fr' }}>
                <span className="muted">{e.field.replace(/_/g, ' ')}</span>
                <span className={`v${e.si?.trim() ? '' : ' empty'}`}>{e.si?.trim() ? e.si : <span className="cell-missing-text">Missing</span>}</span>
                <span className={`v${e.bl?.trim() ? '' : ' empty'}`}>{e.bl?.trim() ? e.bl : <span className="cell-missing-text">Missing</span>}</span>
              </div>
            ))}
          </>
        )}

        <div className="banner warn" style={{ marginTop: 16, marginBottom: 0 }}>
          {r.disclaimer}
        </div>
      </div>
    </div>
  )
}
