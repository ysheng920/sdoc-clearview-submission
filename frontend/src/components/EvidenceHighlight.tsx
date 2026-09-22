import { useEffect, useMemo, useRef, useState } from 'react'
import type { DocumentView, Field, Trace } from '../types'
import { unreadableReason } from '../formatters'
import { autoCropScannedImage } from '../utils/imageCrop'
import { SourceBadge } from './Badges'
import { Icon } from './Icon'

type Props = {
  doc: DocumentView
  /** Fields the comparison flagged, shown in red rather than blue. */
  defectFields?: string[]
  activeField: string | null
  onPick: (field: string | null) => void
  /** The case's traces, so a pane with nothing in it can say why. */
  traces?: Trace[]
}

type Piece = { text: string; field?: string }

const FIELD_LABELS: Record<string, string> = {
  shipper: 'Shipper',
  consignee: 'Consignee',
  notify_party: 'Notify party',
  port_of_loading: 'Port of loading',
  port_of_discharge: 'Port of discharge',
  container_count: 'Container count',
  gross_weight_kg: 'Gross weight',
}

export function DocumentPane({
  doc,
  defectFields = [],
  activeField,
  onPick,
  title,
  traces,
}: {
  doc: DocumentView
  defectFields?: string[]
  activeField: string | null
  onPick: (field: string | null) => void
  title?: React.ReactNode
  /** The case's traces, so a pane with nothing in it can say why. */
  traces?: Trace[]
}) {
  const markRef = useRef<HTMLElement | null>(null)
  // Open on whichever pane has something in it. A page image carries no text
  // layer, so defaulting to text showed two panels of explanation where the
  // documents should have been.
  const [viewMode, setViewMode] = useState<'text' | 'original'>(
    doc.image && !doc.text?.trim() ? 'original' : 'text')
  const [zoom, setZoom] = useState<number>(100)
  const [focusContent, setFocusContent] = useState<boolean>(true)
  const [croppedImage, setCroppedImage] = useState<string | null>(null)
  const [hasCrop, setHasCrop] = useState<boolean>(false)

  useEffect(() => {
    if (!doc.image) return
    let active = true
    autoCropScannedImage(doc.image).then((res) => {
      if (active) {
        setCroppedImage(res.croppedSrc)
        setHasCrop(res.hasCrop)
      }
    })
    return () => {
      active = false
    }
  }, [doc.image])

  // If the document has no extractable text layer (e.g. image-based scanned PDF),
  // synthesize structured label/value text so that evidence highlights and field inspection work identically to .txt files!
  const effectiveDoc = useMemo<DocumentView>(() => {
    if (doc.text && doc.text.trim()) return doc
    const fieldList = Object.values(doc.fields)
    if (!fieldList.length) return doc

    const lines: string[] = []
    const newFields: Record<string, Field> = {}
    let offset = 0

    for (const f of fieldList) {
      const labelText = (FIELD_LABELS[f.name] || f.name.replace(/_/g, ' ')) + ': '
      const rawVal = f.raw || '—'
      const line = `${labelText}${rawVal}\n`
      lines.push(line)

      const start = offset + labelText.length
      const end = start + rawVal.length
      newFields[f.name] = {
        ...f,
        span: { start, end, label: f.name },
      }
      offset += line.length
    }

    return {
      ...doc,
      text: lines.join(''),
      fields: newFields,
    }
  }, [doc])

  const fields = useMemo(
    () => Object.values(effectiveDoc.fields).sort((a, b) => a.name.localeCompare(b.name)),
    [effectiveDoc.fields],
  )

  const pieces = useMemo<Piece[]>(() => {
    const spans = fields
      .filter((f): f is Field & { span: NonNullable<Field['span']> } => f.span !== null)
      .map((f) => ({ ...f.span, field: f.name }))
      .filter((s) => s.start >= 0 && s.end <= effectiveDoc.text.length && s.end > s.start)
      .sort((a, b) => a.start - b.start)

    const out: Piece[] = []
    let cursor = 0
    for (const s of spans) {
      if (s.start < cursor) continue
      if (s.start > cursor) out.push({ text: effectiveDoc.text.slice(cursor, s.start) })
      out.push({ text: effectiveDoc.text.slice(s.start, s.end), field: s.field })
      cursor = s.end
    }
    if (cursor < effectiveDoc.text.length) out.push({ text: effectiveDoc.text.slice(cursor) })
    return out
  }, [effectiveDoc.text, fields])

  useEffect(() => {
    const mark = markRef.current
    if (!mark) return
    const container = mark.closest('.doc-text') as HTMLElement | null
    if (!container) return

    const containerRect = container.getBoundingClientRect()
    const markRect = mark.getBoundingClientRect()
    const currentScrollTop = container.scrollTop
    const relativeTop = markRect.top - containerRect.top + currentScrollTop
    const targetScrollTop = relativeTop - containerRect.height / 2 + markRect.height / 2

    container.scrollTo({
      top: Math.max(0, targetScrollTop),
      behavior: 'smooth',
    })
  }, [activeField, viewMode])

  const isScan = Boolean(doc.image)
  // A page image used to mean one thing -- a page lifted out of a scanned PDF --
  // so the pane said "PDF" everywhere. A photographed document arrives the same
  // way and is not a PDF, and telling the reader it is one is a lie about the
  // evidence they are being shown.
  const isImage = /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(doc.name || '')
  const originalLabel = isImage ? 'Original image' : 'Original PDF'
  // Nothing was recovered at all: no text layer, no page image, no fields. An
  // empty pane badged "Digital Document" is indistinguishable from a broken UI.
  const unreadable = !doc.text?.trim() && !doc.image && !Object.keys(doc.fields).length
  const reason = unreadable ? unreadableReason(traces, doc.name) : null

  return (
    <div className="card doc-view-card">
      <div className="card-head-line">
        <div className="card-head-title-wrap">
          <h3>{title ?? <>Original document · <span className="doc-name-tag">{doc.name}</span></>}</h3>
          <span className={`doc-type-pill${unreadable ? ' unreadable' : ''}`}>
            {unreadable ? 'Unreadable' : isImage ? 'Photograph or scan' : isScan ? 'Scanned PDF' : 'Digital Document'}
          </span>
        </div>

        {isScan && (
          <div className="doc-mode-toggle">
            <button
              type="button"
              className={`doc-mode-btn ${viewMode === 'text' ? 'active' : ''}`}
              onClick={() => setViewMode('text')}
              title={doc.text?.trim()
                ? 'View extracted text with evidence highlights'
                : 'View the values the model read off the page'}
            >
              <Icon name="file" size={13} /> Extracted text
            </button>
            <button
              type="button"
              className={`doc-mode-btn ${viewMode === 'original' ? 'active' : ''}`}
              onClick={() => setViewMode('original')}
              title={isImage ? 'View the original image' : 'View original scanned PDF page'}
            >
              <Icon name="spark" size={13} /> {originalLabel}
            </button>
          </div>
        )}
      </div>

      {isScan && viewMode === 'original' ? (
        <div className="doc-scan-container">
          <div className="doc-scan-toolbar">
            <div className="doc-scan-toolbar-left">
              {hasCrop && (
                <button
                  type="button"
                  className={`doc-scan-btn ${focusContent ? 'active' : ''}`}
                  onClick={() => setFocusContent((v) => !v)}
                  title={focusContent ? (isImage ? 'Switch to the full image' : 'Switch to full untrimmed A4 page') : 'Auto-crop blank margins & focus on text'}
                >
                  <Icon name="crop" size={13} />
                  <span>{focusContent ? 'Focused content' : 'Full page'}</span>
                </button>
              )}
              {hasCrop && focusContent && (
                <span className="doc-scan-crop-badge" title="Excessive blank margins cropped; document content enlarged">
                  Auto-focused (~3× enlarged)
                </span>
              )}
              {(!hasCrop || !focusContent) && (
                <span className="doc-scan-hint">
                  <Icon name="info" size={13} /> {isImage ? 'Original image' : 'Scanned A4 page'}
                </span>
              )}
            </div>

            <div className="doc-scan-toolbar-right">
              <div className="doc-scan-zoom-group">
                <button
                  type="button"
                  className="doc-scan-icon-btn"
                  onClick={() => setZoom((z) => Math.max(50, z - 25))}
                  title="Zoom out (-25%)"
                  disabled={zoom <= 50}
                >
                  <Icon name="zoom-out" size={13} />
                </button>
                <button
                  type="button"
                  className="doc-scan-zoom-level"
                  onClick={() => setZoom(100)}
                  title="Click to reset to 100%"
                >
                  {zoom}%
                </button>
                <button
                  type="button"
                  className="doc-scan-icon-btn"
                  onClick={() => setZoom((z) => Math.min(300, z + 25))}
                  title="Zoom in (+25%)"
                  disabled={zoom >= 300}
                >
                  <Icon name="zoom-in" size={13} />
                </button>
                <button
                  type="button"
                  className={`doc-scan-btn ${zoom > 100 ? 'active' : ''}`}
                  onClick={() => setZoom((z) => (z === 100 ? 160 : 100))}
                  title={zoom > 100 ? 'Reset to fit width (100%)' : 'Enlarge view (160%)'}
                >
                  <Icon name="maximize" size={13} />
                  <span>{zoom > 100 ? 'Fit' : 'Enlarge'}</span>
                </button>
              </div>

              <a
                href={doc.image!}
                download={isImage ? doc.name : `${doc.name}.png`}
                className="doc-scan-action-link"
                title={isImage ? 'Download the original image' : 'Download original scanned page image'}
              >
                <Icon name="download" size={13} />
                <span>Download</span>
              </a>
            </div>
          </div>

          <div className="doc-scan-viewport">
            <img
              className="doc-scan-img"
              style={{
                width: zoom === 100 ? '100%' : `${zoom}%`,
                maxWidth: zoom === 100 ? (focusContent && hasCrop ? '490px' : '720px') : 'none',
                cursor: zoom === 100 ? 'zoom-in' : 'zoom-out',
              }}
              src={(focusContent && hasCrop && croppedImage) ? croppedImage : doc.image!}
              alt={isImage ? doc.name : `Scanned page of ${doc.name}`}
              onClick={() => setZoom((z) => (z === 100 ? 160 : 100))}
              title={zoom === 100 ? 'Click to zoom in (160%)' : 'Click to fit container'}
            />
          </div>
        </div>
      ) : unreadable ? (
        <div className="doc-unreadable">
          <Icon name="alert" size={26} />
          <h4>This file could not be read</h4>
          {reason ? (
            <ul>{reason.map((line, i) => <li key={i}>{line}</li>)}</ul>
          ) : (
            <p>No text, no page image and no fields were recovered from it.</p>
          )}
          <p className="small faint">
            Nothing from this document reached the comparison, so the case needs a
            human to open the original attachment.
          </p>
        </div>
      ) : (
        /* Synthesised above when the document had no text layer: the values
           the model read off the page, laid out as "Label: value" lines with
           real offsets. Both extraction shapes render through the same pane,
           so highlighting and field-pinning work the same on a photograph as
           on a .txt -- which is the point of calling both extracted text. */
        <pre className="doc-text">
          {pieces.map((p, i) =>
            p.field ? (
              <mark
                key={i}
                ref={p.field === activeField ? markRef : undefined}
                className={
                  'evidence' +
                  (defectFields.includes(p.field) ? ' mismatch' : '') +
                  (p.field === activeField ? ' active' : '')
                }
                title={`${p.field.replace(/_/g, ' ')} — click to pin`}
                onClick={() => onPick(p.field === activeField ? null : p.field!)}
              >
                {p.text}
              </mark>
            ) : (
              <span key={i}>{p.text}</span>
            ),
          )}
        </pre>
      )}
    </div>
  )
}

export function DualDocComparison({
  si,
  bl,
  defectFields = [],
  activeField,
  onPick,
  traces,
}: {
  si: DocumentView
  bl: DocumentView
  defectFields?: string[]
  activeField: string | null
  onPick: (field: string | null) => void
  traces?: Trace[]
}) {
  return (
    <div className="dual-doc-view">
      <DocumentPane
        doc={si}
        defectFields={defectFields}
        activeField={activeField}
        onPick={onPick}
        traces={traces}
        title={<>Shipping Instruction (SI) · <span className="doc-name-tag">{si.name}</span></>}
      />
      <DocumentPane
        doc={bl}
        defectFields={defectFields}
        activeField={activeField}
        onPick={onPick}
        traces={traces}
        title={<>Bill of Lading (BL) · <span className="doc-name-tag">{bl.name}</span></>}
      />
    </div>
  )
}

/**
 * Shows a single document next to the values pulled out of it.
 */
export function EvidenceHighlight({ doc, defectFields = [], activeField, onPick, traces }: Props) {
  const fields = useMemo(
    () => Object.values(doc.fields).sort((a, b) => a.name.localeCompare(b.name)),
    [doc.fields],
  )

  return (
    <div className="two-col">
      <DocumentPane
        doc={doc}
        defectFields={defectFields}
        activeField={activeField}
        onPick={onPick}
        traces={traces}
      />

      <div className="card extracted-fields-card">
        <div className="card-head-line">
          <h3>Extracted fields</h3>
          <span className="field-count-pill">{fields.length} fields</span>
        </div>
        <div className="fields-list">
          {fields.map((f) => {
            const hasNorm = f.value && f.raw && f.value !== f.raw.toLowerCase()
            const isMismatch = defectFields.includes(f.name)
            return (
              <div
                key={f.name}
                className={`field-row${f.name === activeField ? ' active' : ''}${isMismatch ? ' mismatch' : ''}`}
                onMouseEnter={() => onPick(f.name)}
                onClick={() => onPick(f.name === activeField ? null : f.name)}
              >
                <div className="field-row-header">
                  <span className="fname">{f.name.replace(/_/g, ' ')}</span>
                  <div className="field-row-badges">
                    {isMismatch && <span className="diff-tag">DIFF</span>}
                    <SourceBadge value={f.source} />
                  </div>
                </div>
                <div className={`fvalue${f.raw?.trim() ? '' : ' empty'}`}>
                  <span className="fraw-text">{f.raw?.trim() ? f.raw : <span className="cell-missing-text">Missing</span>}</span>
                  {hasNorm && (
                    <span className="fnorm-pill" title="Normalised form used for comparison">
                      <span className="fnorm-arrow">→</span>
                      <code>{f.value}</code>
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        <p className="small faint fields-footnote">
          {fields.length === 0
            ? 'Nothing was extracted — see the document pane for why this file could not be read.'
            : doc.image
              ? 'Values with → indicate normalised form used for comparison.'
              : 'Hover or click a field to highlight evidence. Values with → show normalised form.'}
        </p>
      </div>
    </div>
  )
}
