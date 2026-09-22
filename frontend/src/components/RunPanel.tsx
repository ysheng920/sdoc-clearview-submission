import { useState } from 'react'
import { api } from '../api'
import type { SimAttachment } from '../types'
import { Icon } from './Icon'

/**
 * Simulate processing an incoming email with custom attachments.
 * Ingests documents (PDF, Scanned Images, TXT) and runs them through the full
 * classification, extraction, comparison, and decision pipeline in real time.
 */
export function RunPanel({
  onClose,
  onSimulated,
}: {
  onClose: () => void
  onSimulated: (emailId: string) => void
  running?: boolean
  onStarted?: (runId: number) => void
  onReset?: () => void
  initialTab?: string
}) {
  return (
    <div className="run-panel-v2">
      <div className="sim-modal-header">
        <div className="sim-modal-title">
          <div className="sim-modal-icon">
            <Icon name="mail" size={20} />
          </div>
          <div>
            <h3>Simulate Incoming Email</h3>
            <p>Ingest and verify custom documents in real time</p>
          </div>
        </div>
        <div className="sim-header-actions">
          <button className="sim-close-btn" onClick={onClose} aria-label="Close modal">
            <Icon name="x" size={18} />
          </button>
        </div>
      </div>

      <div className="sim-modal-body">
        <SimulateEmail onSimulated={onSimulated} onClose={onClose} />
      </div>
    </div>
  )
}

/** Files travel base64 in the JSON body, so read the bytes, not a data URI. */
async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  // Chunked: String.fromCharCode(...bytes) overflows the argument stack on
  // anything bigger than a small file.
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  }
  return btoa(binary)
}

const ROLES = [
  { value: 'si', label: 'Shipping Instruction' },
  { value: 'bl', label: 'Draft Bill of Lading' },
  { value: '', label: 'Other — let it work it out' },
]

/**
 * An email written by hand, run through the same pipeline as the corpus.
 *
 * The role dropdown exists because the pipeline locates the SI and the BL by
 * filename and, when the names carry no marker, falls back to reading the first
 * 600 characters of each. That guess is pointless here: whoever is composing
 * the email already knows which document is which.
 */
function SimulateEmail({ onSimulated, onClose }: {
  onSimulated: (emailId: string) => void
  onClose: () => void
}) {
  const [sender, setSender] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [files, setFiles] = useState<{ file: File; role: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const empty = !subject.trim() && !body.trim() && files.length === 0
  const hasSI = files.some((f) => f.role === 'si')
  const hasBL = files.some((f) => f.role === 'bl')

  function add(list: FileList | null) {
    if (!list) return
    setError(null)
    const picked = Array.from(list)
    setFiles((current) => [
      ...current,
      ...picked.map((file, i) => ({
        file,
        role: current.length + i === 0 ? 'si' : current.length + i === 1 ? 'bl' : '',
      })),
    ])
  }

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const attachments: SimAttachment[] = await Promise.all(
        files.map(async ({ file, role }) => ({
          filename: file.name, role, content_b64: await toBase64(file),
        })),
      )
      const res = await api.simulate({ subject, sender, body, attachments })
      onClose()
      onSimulated(res.email_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sim-form-wrap">
      {/* Email Fields */}
      <div className="sim-fields-grid">
        <div className="sim-field-row">
          <label className="sim-input-label">
            <span className="sim-label-text">
              <Icon name="user" size={13} />
              Sender Email (From)
            </span>
            <input
              className="sim-input"
              value={sender}
              onChange={(e) => setSender(e.target.value)}
              placeholder="e.g. operations@customer.com"
              spellCheck={false}
            />
          </label>
          <label className="sim-input-label">
            <span className="sim-label-text">
              <Icon name="file" size={13} />
              Email Subject
            </span>
            <input
              className="sim-input"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="e.g. Please confirm draft BL against the SI"
            />
          </label>
        </div>

        <label className="sim-input-label">
          <span className="sim-label-text">
            <Icon name="chat" size={13} />
            Email Body Content
          </span>
          <textarea
            className="sim-textarea"
            value={body}
            rows={3}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Paste or write the customer email message here…"
          />
        </label>
      </div>

      {/* 3. Attachments & Dropzone */}
      <div className="sim-attachments-container">
        <div className="sim-attachments-header">
          <div>
            <h4>Document Attachments ({files.length})</h4>
            <span className="sim-formats-hint">Supports PDF, Scanned Images (PNG, JPG, TIFF), Word, Excel</span>
          </div>
          <label className="sim-upload-btn">
            <Icon name="plus" size={14} />
            <span>Upload Files</span>
            <input
              type="file"
              multiple
              hidden
              accept=".txt,.pdf,.docx,.xlsx,.csv,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff"
              onChange={(e) => { add(e.target.files); e.target.value = '' }}
            />
          </label>
        </div>

        {files.length === 0 ? (
          <div
            className={`sim-dropzone ${isDragging ? 'dragging' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => { e.preventDefault(); setIsDragging(false); add(e.dataTransfer.files) }}
          >
            <div className="sim-dropzone-icon">
              <Icon name="file" size={30} />
            </div>
            <div className="sim-dropzone-text">
              <strong>Drag & drop documents or photos here</strong>
              <p>Upload a Shipping Instruction (SI) and Draft Bill of Lading (BL) to test discrepancy detection</p>
            </div>
            <label className="sim-browse-btn">
              Browse Files
              <input
                type="file"
                multiple
                hidden
                accept=".txt,.pdf,.docx,.xlsx,.csv,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff"
                onChange={(e) => { add(e.target.files); e.target.value = '' }}
              />
            </label>
          </div>
        ) : (
          <div className="sim-files-list">
            {files.map(({ file, role }, i) => (
              <div className="sim-file-card" key={`${file.name}-${i}`}>
                <div className="sim-file-badge">
                  {file.name.endsWith('.pdf') ? 'PDF' : file.name.match(/\.(png|jpe?g|tiff?|webp)$/i) ? 'IMG' : 'DOC'}
                </div>
                <div className="sim-file-details">
                  <span className="sim-file-title" title={file.name}>{file.name}</span>
                  <span className="sim-file-meta">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                </div>
                <div className="sim-file-role-select">
                  <span className="sim-role-label">Role:</span>
                  <select
                    value={role}
                    className={`sim-select role-${role || 'other'}`}
                    onChange={(e) => setFiles((cur) =>
                      cur.map((f, j) => (j === i ? { ...f, role: e.target.value } : f)))}
                  >
                    {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </div>
                <button
                  type="button"
                  className="sim-remove-btn"
                  title="Remove attachment"
                  onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
            ))}

            <div className="sim-add-more-row">
              <label className="sim-add-more-btn">
                <Icon name="plus" size={12} />
                <span>Add another document</span>
                <input
                  type="file"
                  multiple
                  hidden
                  accept=".txt,.pdf,.docx,.xlsx,.csv,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff"
                  onChange={(e) => { add(e.target.files); e.target.value = '' }}
                />
              </label>
            </div>
          </div>
        )}

        {/* Readiness Status Indicator */}
        {files.length > 0 && (
          <div className={`sim-readiness-pill ${hasSI && hasBL ? 'ready' : 'incomplete'}`}>
            <Icon name={hasSI && hasBL ? 'check' : 'info'} size={14} />
            <span>
              {hasSI && hasBL
                ? 'Ready for comparison: Both Shipping Instruction (SI) and Draft Bill of Lading (BL) are attached.'
                : hasSI
                ? 'Shipping Instruction (SI) attached. Add or label a Draft Bill of Lading (BL) to perform field comparison.'
                : hasBL
                ? 'Draft Bill of Lading (BL) attached. Add or label a Shipping Instruction (SI) to perform field comparison.'
                : 'Please label attachments as SI and BL using the role dropdown above for discrepancy checking.'}
            </span>
          </div>
        )}
      </div>

      {error && (
        <div className="sim-error-banner">
          <Icon name="alert" size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* 4. Modal Footer */}
      <div className="sim-modal-footer">
        <div className="sim-footer-meta">
          <span className="sim-meta-dot" />
          <span>{files.length} attachment{files.length === 1 ? '' : 's'}</span>
          {files.length > 0 && <span className="sim-meta-roles">({hasSI ? 'SI ✓' : 'SI ✗'} · {hasBL ? 'BL ✓' : 'BL ✗'})</span>}
        </div>
        <div className="sim-footer-buttons">
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary-action sim-run-btn" onClick={run} disabled={busy || empty}>
            <Icon name="spark" size={15} />
            <span>{busy ? 'Processing Pipeline…' : 'Run Pipeline Simulation'}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
