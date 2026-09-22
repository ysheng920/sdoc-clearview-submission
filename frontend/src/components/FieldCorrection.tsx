import { useState } from 'react'
import { api } from '../api'
import type { BlastRadius, EmailRecord, FieldVerdict, Occurrence } from '../types'
import { Icon } from './Icon'
import { formatFriendlyRule } from '../formatters'

/**
 * Where a reviewer disagrees with the comparison, placed next to the evidence
 * rather than at the foot of the page -- the judgement is made while looking at
 * the two values, and an entry box anywhere else asks the reviewer to remember
 * them on the way there.
 *
 * Three actions, deliberately separate, because they reach different distances:
 *
 *   overrule the verdict / correct a value -> this email only, immediately
 *   record it in the mapping library        -> counted, changes no verdict
 *   approve the pair                        -> every future email with that pair
 *
 * The last one is the only irreversible-feeling step, so it is the only one that
 * makes the reviewer read something first: what it would change, by case number.
 */
export function FieldCorrection({ record, field, verdict, onRecord }: {
  record: EmailRecord
  field: string
  verdict: FieldVerdict
  onRecord: (next: EmailRecord) => void
}) {
  const [editing, setEditing] = useState<'si' | 'bl' | null>(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [asked, setAsked] = useState<{ id: number; occurrence: Occurrence } | null>(null)
  const [answered, setAnswered] = useState<'kept' | 'private' | null>(null)

  const overridden = verdict.rule.startsWith('human_override')
  const flipTo = verdict.status === 'MATCH' ? 'MISMATCH' : 'MATCH'

  async function save(payload: Parameters<typeof api.sendFeedback>[1]) {
    setBusy(true)
    setError('')
    try {
      const res = await api.sendFeedback(record.email_id, payload)
      onRecord(res.record)
      setEditing(null)
      setValue('')
      setAnswered(null)
      setAsked(res.occurrence?.kind ? { id: res.id, occurrence: res.occurrence } : null)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  function startEdit(side: 'si' | 'bl') {
    setEditing(side)
    setValue(verdict[side].raw ?? '')
    setError('')
  }

  function saveValue() {
    if (!value.trim()) {
      setError('Enter the correct value first')
      return
    }
    save({ kind: 'field', target: field, side: editing!, corrected_to: value.trim(),
           was: verdict[editing!].raw ?? '' })
  }

  return (
    <div className="field-correction">
      {overridden && (
        <div className="correction-note-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
          <p className="correction-note" style={{ margin: 0 }}>
            <Icon name="user" size={15} aria-hidden="true"/>
            You set this verdict by hand. The engine said{' '}
            <code>{verdict.overruled_rule ? formatFriendlyRule(verdict.overruled_rule) : 'something else'}</code>.
          </p>
          <button
            type="button"
            className="secondary-action"
            style={{ fontSize: '11px', padding: '3px 9px', height: '26px', display: 'inline-flex', alignItems: 'center', gap: '5px' }}
            disabled={busy}
            onClick={() => save({
              kind: 'verdict',
              target: field,
              corrected_to: 'revert',
              was: verdict.status,
            })}
            title="Undo human override and restore engine's original decision"
          >
            <Icon name="arrow" size={12}/>
            Reset to engine verdict
          </button>
        </div>
      )}

      {editing ? (
        <div className="correction-edit-box">
          <div className="correction-edit-head">
            <span className="correction-edit-label">
              <Icon name="edit" size={13} />
              Correct <strong>{editing === 'si' ? 'Shipping Instruction (SI)' : 'Bill of Lading (BL)'}</strong> value:
            </span>
            <button className="correction-cancel-link" onClick={() => { setEditing(null); setError('') }}>
              Cancel
            </button>
          </div>
          <div className="correction-edit-input-row">
            <input
              className="correction-input-field"
              value={value}
              autoFocus
              onChange={(e) => { setValue(e.target.value); setError('') }}
              onKeyDown={(e) => e.key === 'Enter' && saveValue()}
              placeholder="As it reads on document…"
            />
            <button className="correction-save-btn" disabled={busy} onClick={saveValue}>
              {busy ? 'Saving…' : 'Save and re-compare'}
            </button>
          </div>
        </div>
      ) : (
        <div className="correction-toolbar">
          <div className="correction-group">
            <span className="correction-label">Review Actions:</span>
            <button
              className={`correction-action-btn ${flipTo === 'MATCH' ? 'btn-match' : 'btn-mismatch'}`}
              disabled={busy}
              onClick={() => save({
                kind: 'verdict', target: field, corrected_to: overridden ? 'revert' : flipTo, was: verdict.status,
              })}
              title={overridden ? 'Restore engine evaluation' : (flipTo === 'MATCH' ? 'Overrule the engine: accept these two values as matching' : 'Overrule the engine: flag these two values as different')}
            >
              <Icon name={flipTo === 'MATCH' ? 'check' : 'x'} size={13} aria-hidden="true"/>
              <span>{overridden ? (flipTo === 'MATCH' ? 'Revert to Match' : 'Revert to Discrepancy') : (flipTo === 'MATCH' ? 'Accept as Match' : 'Mark as Discrepancy')}</span>
            </button>
          </div>

          <div className="correction-group">
            <button
              className="correction-action-btn btn-edit"
              disabled={busy}
              onClick={() => startEdit('si')}
              title="Manually correct or enter Shipping Instruction value"
            >
              <Icon name="edit" size={13} aria-hidden="true"/>
              <span>Edit SI value</span>
            </button>
            <button
              className="correction-action-btn btn-edit"
              disabled={busy}
              onClick={() => startEdit('bl')}
              title="Manually correct or enter Bill of Lading value"
            >
              <Icon name="edit" size={13} aria-hidden="true"/>
              <span>Edit BL value</span>
            </button>
          </div>
        </div>
      )}

      {error && <p className="correction-error">{error}</p>}

      {asked && !answered && (
        <LibraryPrompt
          occurrence={asked.occurrence}
          onAnswer={async (keep) => {
            await api.recordInLibrary(asked.id, keep)
            setAnswered(keep ? 'kept' : 'private')
          }}
        />
      )}

      {asked && answered === 'kept' && (
        <Approval occurrence={asked.occurrence} onDone={() => setAsked(null)}/>
      )}
      {answered === 'private' && (
        <p className="correction-note">
          Kept to this case. The comparison rules are unchanged.
        </p>
      )}
    </div>
  )
}

/**
 * The same question three ways. The wording escalates with the count because the
 * answer changes with it: the first one is bookkeeping, and the fifth is a
 * finding that somebody should act on.
 */
function LibraryPrompt({ occurrence, onAnswer }: {
  occurrence: Occurrence
  onAnswer: (keep: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  // The count is of corrections already recorded; the one being asked about is
  // not among them yet, which is the whole reason the question is being asked.
  const seen = occurrence.count + 1
  const others = occurrence.emails ?? []

  return (
    <div className={`library-prompt${seen > 1 ? ' repeated' : ''}`}>
      <p className="pair">
        <code>{occurrence.a}</code>
        <span aria-hidden="true">≡</span>
        <code>{occurrence.b}</code>
      </p>
      {seen <= 1 ? (
        <p>First time these two spellings have come up. Record them in the mapping library?</p>
      ) : (
        <>
          <p>
            Seen {seen} times now{others.length ? ` — also on ${others.join(', ').replace(/email_/g, '#')}` : ''}.
          </p>
          <p className="small muted">
            A pair this persistent is a naming gap rather than a one-off.
          </p>
        </>
      )}
      <div className="correction-actions">
        <button
          className="prompt-btn prompt-btn-primary"
          disabled={busy}
          onClick={() => { setBusy(true); onAnswer(true).finally(() => setBusy(false)) }}
        >
          <Icon name="check" size={13} aria-hidden="true" />
          <span>Record in library</span>
        </button>
        <button
          className="prompt-btn prompt-btn-secondary"
          disabled={busy}
          onClick={() => { setBusy(true); onAnswer(false).finally(() => setBusy(false)) }}
        >
          <Icon name="x" size={13} aria-hidden="true" />
          <span>Keep as one-off only</span>
        </button>
      </div>
    </div>
  )
}

/**
 * Approving is the one act here that reaches emails nobody in this room has read,
 * so it does not happen on a single click. The reviewer is shown which stored
 * cases it would change, by case number, and approves against that list.
 *
 * Narrow as it is -- one pair of normalised values, matched nowhere else -- it is
 * still permanent and global, and the file it lands in is committed, so the
 * approval also shows up later as a diff somebody can argue with.
 */
function Approval({ occurrence, onDone }: { occurrence: Occurrence; onDone: () => void }) {
  const [radius, setRadius] = useState<BlastRadius | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'done'>('idle')
  const [error, setError] = useState('')

  if (occurrence.approved) {
    return <p className="correction-note">
      <Icon name="check" size={15} aria-hidden="true"/>
      Already in the mapping library — any case carrying this pair matches on it.
    </p>
  }

  async function look() {
    setState('loading')
    setError('')
    try {
      setRadius(await api.blastRadius(occurrence.kind!, occurrence.a!, occurrence.b!))
      setState('ready')
    } catch (e) {
      setError(String(e))
      setState('idle')
    }
  }

  async function approve() {
    setState('loading')
    try {
      await api.approveMapping(occurrence.kind!, occurrence.a!, occurrence.b!)
      setState('done')
    } catch (e) {
      setError(String(e))
      setState('ready')
    }
  }

  if (state === 'done') {
    return <p className="correction-note">
      <Icon name="check" size={15} aria-hidden="true"/>
      Approved. Any case carrying this pair matches from now on; the ones already
      processed pick it up when they are next run. The change is in a committed
      file, so it shows up as a diff for review.
    </p>
  }

  return (
    <div className="library-prompt approval">
      <p>Recorded. Approving it settles every case with this exact pair, not just this one.</p>
      {error && <p className="correction-error">{error}</p>}

      {state !== 'ready' ? (
        <div className="correction-actions">
          <button
            className="prompt-btn prompt-btn-secondary"
            disabled={state === 'loading'}
            onClick={look}
          >
            <Icon name="search" size={13} aria-hidden="true" />
            <span>{state === 'loading' ? 'Checking…' : 'See what it would change'}</span>
          </button>
          <button className="prompt-btn prompt-btn-ghost" onClick={onDone}>
            Not now
          </button>
        </div>
      ) : (
        <>
          <p className="radius">
            {radius!.would_change.length === 0
              ? `No processed case carries this pair yet (${radius!.scanned} checked).`
              : `${radius!.would_change.length} of ${radius!.scanned} processed case${radius!.scanned === 1 ? '' : 's'} carries it, and would match when next run:`}
          </p>
          {radius!.would_change.length > 0 && (
            <ul className="radius-list">
              {radius!.would_change.slice(0, 8).map((c) => (
                <li key={`${c.email_id}-${c.field}`}>
                  <strong>{c.email_id.replace('email_', '#')}</strong>
                  <span>{c.field.replace(/_/g, ' ')}</span>
                  <span className="muted">{c.status} → MATCH</span>
                </li>
              ))}
              {radius!.would_change.length > 8 && (
                <li className="muted">and {radius!.would_change.length - 8} more</li>
              )}
            </ul>
          )}
          <div className="correction-actions">
            <button className="prompt-btn prompt-btn-primary" onClick={approve}>
              <Icon name="check" size={13} aria-hidden="true" />
              <span>Approve for all cases</span>
            </button>
            <button className="prompt-btn prompt-btn-ghost" onClick={onDone}>
              Not now
            </button>
          </div>
        </>
      )}
    </div>
  )
}
