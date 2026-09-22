import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import { THEMES, useTheme, type Theme } from '../theme'
import type { AppConfig, MappingListResponse } from '../types'
import { formatMalaysiaTime } from '../formatters'

const CANONICAL_FIELDS = [
  {
    name: 'Shipper',
    note: 'Legal entity normalization (removes suffixes: Pte Ltd, Sdn Bhd, Inc, Ltd for alias matching)',
    category: 'Entity',
  },
  {
    name: 'Consignee',
    note: 'Recipient entity & address standardisation with fuzzy entity matching and aliases',
    category: 'Entity',
  },
  {
    name: 'Notify Party',
    note: 'Equivalence mapping with automated "SAME AS CONSIGNEE" alias resolution',
    category: 'Entity',
  },
  {
    name: 'Port of Loading (POL)',
    note: 'Port standardisation to UN/LOCODE with regional port aliases (e.g. Port Klang ≡ MYPKG)',
    category: 'Routing',
  },
  {
    name: 'Port of Discharge (POD)',
    note: 'Standardized destination port and terminal berth identification',
    category: 'Routing',
  },
  {
    name: 'Container Count',
    note: "ISO shipping container quantity & type normalization (e.g. 4 x 40'HQ ≡ 4 x 40HC)",
    category: 'Equipment',
  },
  {
    name: 'Gross Weight',
    note: 'Mass conversion standardisation to Kilograms (KG) with decimal tolerance',
    category: 'Cargo',
  },
]

export function Settings({ onOpenCase }: { onOpenCase?: (id: string) => void }) {
  const [theme, setTheme, resolved] = useTheme()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [tab, setTab] = useState('AI & Model')
  const [checking, setChecking] = useState(false)
  const [checked, setChecked] = useState('')
  const [pingMs, setPingMs] = useState<number | null>(null)
  const [currentTime, setCurrentTime] = useState(() => formatMalaysiaTime(new Date().toISOString()))

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(formatMalaysiaTime(new Date().toISOString()))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  // Mapping library state
  const [mappingData, setMappingData] = useState<MappingListResponse | null>(null)
  const [mappingLoading, setMappingLoading] = useState(false)
  const [subTab, setSubTab] = useState<'mappings' | 'corrections'>('mappings')
  const [searchTerm, setSearchTerm] = useState('')
  const [kindFilter, setKindFilter] = useState<'all' | 'entity' | 'port'>('all')

  // Add knowledge modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [addKind, setAddKind] = useState<'entity' | 'port'>('entity')
  const [addA, setAddA] = useState('')
  const [addB, setAddB] = useState('')
  const [addNote, setAddNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [addError, setAddError] = useState('')
  const [revokingKey, setRevokingKey] = useState<string | null>(null)
  const [toast, setToast] = useState('')

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null))
  }, [])

  useEffect(() => {
    if (tab === 'Mapping Library') {
      loadMappings()
    }
  }, [tab])

  async function loadMappings() {
    setMappingLoading(true)
    try {
      const res = await api.mappings()
      setMappingData(res)
    } catch (err) {
      console.error('Failed to load mappings', err)
    } finally {
      setMappingLoading(false)
    }
  }

  async function checkConnection() {
    setChecking(true)
    setChecked('')
    setPingMs(null)
    const t0 = performance.now()
    try {
      const result = await api.config()
      const t1 = performance.now()
      setConfig(result)
      setPingMs(Math.round(t1 - t0))
      setChecked('Backend API is healthy & responding.')
    } catch {
      setChecked('Backend API is not reachable.')
    } finally {
      setChecking(false)
    }
  }

  async function handleAddMapping(e: React.FormEvent) {
    e.preventDefault()
    if (!addA.trim() || !addB.trim()) {
      setAddError('Both original and canonical values are required.')
      return
    }
    setSubmitting(true)
    setAddError('')
    try {
      await api.approveMapping(addKind, addA.trim(), addB.trim(), addNote.trim() || undefined)
      setAddA('')
      setAddB('')
      setAddNote('')
      setShowAddModal(false)
      setToast('Knowledge mapping successfully saved to library!')
      setTimeout(() => setToast(''), 3500)
      await loadMappings()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save mapping to library.'
      setAddError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRevoke(kind: string, a: string, b: string) {
    const key = `${kind}-${a}-${b}`
    if (!window.confirm(`Revoke knowledge mapping for "${a}" ≡ "${b}"?`)) return
    setRevokingKey(key)
    try {
      await api.revokeMapping(kind, a, b)
      setToast('Mapping revoked.')
      setTimeout(() => setToast(''), 3000)
      await loadMappings()
    } catch {
      alert('Failed to revoke mapping.')
    } finally {
      setRevokingKey(null)
    }
  }

  const filteredEntries = (mappingData?.entries || []).filter((m) => {
    if (kindFilter !== 'all' && m.kind !== kindFilter) return false
    if (!searchTerm.trim()) return true
    const term = searchTerm.toLowerCase()
    return (
      m.a.toLowerCase().includes(term) ||
      m.b.toLowerCase().includes(term) ||
      (m.note && m.note.toLowerCase().includes(term)) ||
      (m.from_email && m.from_email.toLowerCase().includes(term)) ||
      (m.approved_by && m.approved_by.toLowerCase().includes(term))
    )
  })

  const filteredCorrections = (mappingData?.corrections || []).filter((c) => {
    if (!searchTerm.trim()) return true
    const term = searchTerm.toLowerCase()
    return (
      c.email_id.toLowerCase().includes(term) ||
      (c.target && c.target.toLowerCase().includes(term)) ||
      (c.was && c.was.toLowerCase().includes(term)) ||
      (c.corrected_to && c.corrected_to.toLowerCase().includes(term)) ||
      (c.reviewer && c.reviewer.toLowerCase().includes(term)) ||
      (c.note && c.note.toLowerCase().includes(term))
    )
  })

  return (
    <div className="workspace-page settings-page">
      <div className="page-tabs">
        {['AI & Model', 'Processing & Rules', 'Appearance', 'Mapping Library'].map((item) => (
          <button
            key={item}
            className={tab === item ? 'active' : ''}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === 'AI & Model' && (
        <div className="settings-tab-content">
          <div className="settings-hero-banner">
            <div className="settings-hero-content">
              <div className="settings-hero-badge">
                <Icon name="cpu" size={13}/>
                <span>HYBRID DUAL-ENGINE ARCHITECTURE</span>
              </div>
              <h2>Jev ➔ Gemini Calibrated Escalation Pipeline</h2>
              <p>
                Inbound shipping communications are classified using <strong>TypeSafe Jev</strong> (calibrated decisions with an 80% confidence gate), automatically escalating uncertain cases or visual document extractions to <strong>Gemini 2.5 Flash Lite</strong>.
              </p>
            </div>
            <div className="settings-flow-pills">
              <div className="flow-step-pill">
                <span className="step-num">1</span>
                <div>
                  <strong>Inbound Case</strong>
                  <small>Email & Docs</small>
                </div>
              </div>
              <span className="flow-arrow">➔</span>
              <div className="flow-step-pill primary">
                <span className="step-num">2</span>
                <div>
                  <strong>TypeSafe Jev</strong>
                  <small>≥ 80% Fast Path</small>
                </div>
              </div>
              <span className="flow-arrow">➔</span>
              <div className="flow-step-pill fallback">
                <span className="step-num">3</span>
                <div>
                  <strong>Gemini Escalation</strong>
                  <small>&lt; 80% & Vision</small>
                </div>
              </div>
            </div>
          </div>

          <div className="settings-grid">
            <section className="panel-card">
              <h2>Model configuration</h2>
              <p className="panel-subtitle">Active provider engines and runtime specifications.</p>
              <div className="setting-rows">
                <SettingRow title="Active backend" note="Selected by backend environment" value={config?.backend ?? 'jev+gemini'}/>
                <SettingRow title="Primary classification" note="OpenRouter Decisions API" value="~typesafe/jev-latest"/>
                <SettingRow title="Cloud escalation / vision" note="Multimodal document reader" value={config?.cloud_model ?? 'gemini-2.5-flash-lite'}/>
                <SettingRow title="Escalation threshold" note="Confidence gate for cloud fallback" value="0.80 (80%)"/>
                <SettingRow title="Sample corpus" note="Labelled operational test emails" value={`${config?.emails_available ?? '520'} emails`}/>
              </div>
            </section>

            <section className="panel-card">
              <h2>Routing & Governance</h2>
              <p className="panel-subtitle">Operational decision policies and safeguards.</p>
              <div className="setting-rows">
                <SettingRow title="Dynamic escalation" note="Automatic reroute on low confidence" value={config?.escalation_enabled !== false ? 'Active' : 'Disabled'}/>
                <SettingRow title="Field comparison" note="Deterministic rules overrule LLM" value="Rules Priority"/>
                <SettingRow title="Email dispatch" note="Reply drafts are never sent automatically" value="Air-gapped (Draft only)"/>
                <SettingRow title="Decision auditability" note="Per-case telemetry & token tracking" value="Full Trace Logged"/>
                <SettingRow title="Operator oversight" note="Cases with defects route to queue" value="Human-in-the-Loop"/>
              </div>
            </section>

            <section className="panel-card">
              <h2>Backend Service Health</h2>
              <p className="panel-subtitle">Connectivity status of the FastAPI backend.</p>
              <div className={`connection-box ${config ? 'connected' : ''}`}>
                <span className="runtime-dot"/>
                <div>
                  <strong>{config ? 'API Connected' : 'API Unavailable'}</strong>
                  <small>{config ? `Port 8000 ${pingMs !== null ? `· Latency ${pingMs}ms` : '· Serving requests'}` : 'Start the FastAPI server on port 8000'}</small>
                </div>
              </div>
              <button className="secondary-action" onClick={checkConnection} disabled={checking}>
                <Icon name="check" size={17}/>{checking ? 'Checking…' : 'Test connection'}
              </button>
              {checked && <p className="small muted" style={{ marginTop: '8px' }}>{checked}</p>}
              <div className="settings-note">
                <Icon name="info" size={17}/>
                <p>AI provider keys and backend models are loaded from <code>backend/.env</code> on launch.</p>
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'Processing & Rules' && (
        <div className="settings-tab-content">
          <div className="settings-grid" style={{ gridTemplateColumns: '1.05fr 1.35fr 0.95fr' }}>
            <section className="panel-card">
              <h2>Document Ingestion Engine</h2>
              <p className="panel-subtitle">Supported formats and parsing extractors.</p>
              <div className="doc-format-grid" style={{ gridTemplateColumns: '1fr' }}>
                <div className="doc-format-card">
                  <div className="doc-format-head">
                    <span className="doc-format-title"><Icon name="file" size={15}/>PDF Documents (.pdf)</span>
                    <span className="doc-format-badge">Dual Mode</span>
                  </div>
                  <p>Native text layer extraction via PyPDF. Scanned raster images trigger Vision OCR with mandatory review gate.</p>
                </div>

                <div className="doc-format-card">
                  <div className="doc-format-head">
                    <span className="doc-format-title"><Icon name="file" size={15}/>Images & Scans (.png, .jpg, .tiff)</span>
                    <span className="doc-format-badge">Vision OCR</span>
                  </div>
                  <p>Direct visual extraction for photos and image scans via Gemini Vision with mandatory operator verification.</p>
                </div>

                <div className="doc-format-card">
                  <div className="doc-format-head">
                    <span className="doc-format-title"><Icon name="file" size={15}/>Excel Spreadsheets (.xlsx)</span>
                    <span className="doc-format-badge">Tabular Grid</span>
                  </div>
                  <p>Multi-sheet workbook parsing with cell coordinate mapping for shipping container manifests.</p>
                </div>

                <div className="doc-format-card">
                  <div className="doc-format-head">
                    <span className="doc-format-title"><Icon name="file" size={15}/>Word Documents (.docx)</span>
                    <span className="doc-format-badge">Structured XML</span>
                  </div>
                  <p>Paragraph segment scanning and table cell extraction for shipping instructions and packing notes.</p>
                </div>

                <div className="doc-format-card">
                  <div className="doc-format-head">
                    <span className="doc-format-title"><Icon name="file" size={15}/>Plain Text (.txt)</span>
                    <span className="doc-format-badge">Direct Regex</span>
                  </div>
                  <p>Direct header-body boundary segmentation and rapid key-value shipping field recognition.</p>
                </div>
              </div>
            </section>

            <section className="panel-card">
              <h2>Canonical Field Verification Matrix</h2>
              <p className="panel-subtitle">Standardized normalization rules applied across all shipping document pairs.</p>
              <div className="field-matrix-list">
                {CANONICAL_FIELDS.map((f) => (
                  <div key={f.name} className="field-matrix-item">
                    <div className="field-matrix-info">
                      <strong>{f.name}</strong>
                      <small>{f.note}</small>
                    </div>
                    <span className="field-matrix-tag">{f.category}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel-card">
              <h2>Verification Guardrails</h2>
              <p className="panel-subtitle">Safety policies enforced prior to document clearance.</p>
              <div className="setting-rows">
                <SettingRow title="Precedence hierarchy" note="Rules always supersede AI inferences" value="Deterministic"/>
                <SettingRow title="Discrepancy policy" note="Numerical or entity mismatch flags review" value="Zero Tolerance"/>
                <SettingRow title="Scanned document gate" note="Visual OCR outputs require visual check" value="Operator Sign-Off"/>
                <SettingRow title="Field evidence audit" note="Original spans and coordinates preserved" value="Tamper-Evident"/>
                <SettingRow title="Knowledge sync" note="Approved aliases feed into normalizer" value="Mapping Library"/>
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'Appearance' && (
        <div className="settings-tab-content">
          <div className="settings-grid">
            <section className="panel-card">
              <h2>Workspace Theme</h2>
              <p className="panel-subtitle">Choose interface styling tailored for day or night operations.</p>
              <div className="theme-cards-grid">
                {THEMES.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={`theme-card-button ${theme === option.value ? 'active' : ''}`}
                    onClick={() => setTheme(option.value as Theme)}
                  >
                    <div className={`theme-preview-box ${option.value}`}/>
                    <strong>{option.label}</strong>
                    <small>{option.hint}</small>
                    {theme === option.value && <Icon name="check" size={16} className="theme-card-check"/>}
                  </button>
                ))}
              </div>
              <p className="small muted" style={{ marginTop: '16px' }}>
                Active appearance: <strong>{resolved}</strong> (Saved in browser storage).
              </p>
            </section>

            <section className="panel-card">
              <h2>Operational Locale & Timezone</h2>
              <p className="panel-subtitle">Configured time standards across case feeds, queues, and traces.</p>
              <div className="setting-rows">
                <SettingRow title="System timezone" note="Primary desk operational timezone" value="Asia/Kuala_Lumpur (GMT+8)"/>
                <SettingRow title="Regional standard" note="National standard for logistics desk" value="Malaysia Time (MYT)"/>
                <SettingRow title="Time format" note="24-hour timestamp formatting" value="YYYY-MM-DD HH:mm:ss"/>
                <div className="setting-row">
                  <div>
                    <strong>Current desk time</strong>
                    <small>Real-time workspace clock</small>
                  </div>
                  <span className="live-clock-pill">
                    <Icon name="clock" size={13}/>
                    {currentTime}
                  </span>
                </div>
              </div>
              <div className="settings-note">
                <Icon name="info" size={17}/>
                <p>All queue timestamps, review logs, and decision traces are automatically synchronized to Malaysia Standard Time.</p>
              </div>
            </section>

            <section className="panel-card">
              <h2>Status Color Guide</h2>
              <p className="panel-subtitle">Visual color-coded badges used across Work Queue and Case Workspaces.</p>
              <div className="status-legend-list">
                <div className="status-legend-row">
                  <span className="field-rule-tag ok">MATCH / AUTO-CLEAR</span>
                  <span className="status-legend-desc">SI and BL align within normalized rules.</span>
                </div>
                <div className="status-legend-row">
                  <span className="field-rule-tag bad">MISMATCH / DISCREPANCY</span>
                  <span className="status-legend-desc">Conflicting data points detected between documents.</span>
                </div>
                <div className="status-legend-row">
                  <span className="field-rule-tag" style={{ background: '#fffbeb', color: '#b45309', borderColor: '#fde68a' }}>
                    NEEDS REVIEW / BLOCKER
                  </span>
                  <span className="status-legend-desc">Unreadable scan, missing attachment, or operator judgment needed.</span>
                </div>
                <div className="status-legend-row">
                  <span className="field-rule-tag" style={{ background: '#eff6ff', color: '#1d4ed8', borderColor: '#bfdbfe' }}>
                    INFORMATION / INQUIRY
                  </span>
                  <span className="status-legend-desc">General notices, booking inquiries, or spam filters.</span>
                </div>
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'Mapping Library' && (
        <div className="mapping-library-container">
          {toast && (
            <div className="mapping-toast">
              <Icon name="check" size={16}/>
              <span>{toast}</span>
            </div>
          )}

          <section className="panel-card mapping-hero-card">
            <div className="mapping-header-row">
              <div>
                <span className="mapping-eyebrow">CUSTOM NORMALIZATION & ALIAS KNOWLEDGE</span>
                <h2>Mapping Library</h2>
                <p className="panel-subtitle">
                  Inspect manual knowledge entries and custom aliases added to equate differing shipping entities and ports.
                </p>
              </div>
              <button
                className="primary-action add-mapping-btn"
                onClick={() => { setShowAddModal(true); setAddError('') }}
              >
                <Icon name="plus" size={16}/> Add Knowledge
              </button>
            </div>

            <div className="mapping-controls-bar">
              <div className="mapping-subtabs">
                <button
                  className={`mapping-subtab ${subTab === 'mappings' ? 'active' : ''}`}
                  onClick={() => setSubTab('mappings')}
                >
                  Approved Mappings
                  <span className="count-pill">{mappingData?.entries?.length ?? 0}</span>
                </button>
                <button
                  className={`mapping-subtab ${subTab === 'corrections' ? 'active' : ''}`}
                  onClick={() => setSubTab('corrections')}
                >
                  Manual Case Corrections
                  <span className="count-pill">{mappingData?.corrections?.length ?? 0}</span>
                </button>
              </div>

              <div className="mapping-filters-right">
                <div className="mapping-search-wrap">
                  <Icon name="search" size={14}/>
                  <input
                    type="text"
                    placeholder={subTab === 'mappings' ? "Search mapped values or notes..." : "Search corrections by case or field..."}
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                  {searchTerm && (
                    <button className="clear-search" onClick={() => setSearchTerm('')}>
                      <Icon name="x" size={12}/>
                    </button>
                  )}
                </div>

                {subTab === 'mappings' && (
                  <div className="mapping-kind-pills">
                    <button
                      className={`kind-pill ${kindFilter === 'all' ? 'active' : ''}`}
                      onClick={() => setKindFilter('all')}
                    >
                      All ({mappingData?.entries?.length ?? 0})
                    </button>
                    <button
                      className={`kind-pill ${kindFilter === 'entity' ? 'active' : ''}`}
                      onClick={() => setKindFilter('entity')}
                    >
                      Entities ({mappingData?.counters?.entity ?? 0})
                    </button>
                    <button
                      className={`kind-pill ${kindFilter === 'port' ? 'active' : ''}`}
                      onClick={() => setKindFilter('port')}
                    >
                      Ports ({mappingData?.counters?.port ?? 0})
                    </button>
                  </div>
                )}
              </div>
            </div>
          </section>

          {subTab === 'mappings' ? (
            <section className="panel-card mapping-table-card">
              {mappingLoading ? (
                <div className="mapping-loading">
                  <span className="loading-spinner"/> Loading mapping library...
                </div>
              ) : filteredEntries.length === 0 ? (
                <div className="mapping-empty-state">
                  <div className="empty-icon-wrap">
                    <Icon name="file" size={28}/>
                  </div>
                  <h3>{searchTerm || kindFilter !== 'all' ? 'No Matching Knowledge Entries' : 'No Mappings Added Yet'}</h3>
                  <p>
                    {searchTerm || kindFilter !== 'all'
                      ? 'Try adjusting your search query or filter tags.'
                      : 'Equivalence rules added here or recorded during case review teach the engine to treat differing spellings as exact matches.'}
                  </p>
                  {!searchTerm && kindFilter === 'all' && (
                    <button
                      className="primary-action"
                      onClick={() => { setShowAddModal(true); setAddError('') }}
                    >
                      <Icon name="plus" size={15}/> Add First Mapping
                    </button>
                  )}
                </div>
              ) : (
                <div className="mapping-table-wrap">
                  <table className="mapping-table">
                    <thead>
                      <tr>
                        <th style={{ width: '100px' }}>Type</th>
                        <th>Knowledge Equivalence (A ≡ B)</th>
                        <th style={{ width: '120px' }}>Added By</th>
                        <th style={{ width: '165px' }}>Logged At (MYT)</th>
                        <th>Origin / Note</th>
                        <th style={{ width: '90px', textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEntries.map((m) => {
                        const key = `${m.kind}-${m.a}-${m.b}`
                        const isRevoking = revokingKey === key
                        return (
                          <tr key={key}>
                            <td>
                              <span className={`mapping-type-pill ${m.kind}`}>
                                {m.kind === 'entity' ? 'Entity' : 'Port'}
                              </span>
                            </td>
                            <td>
                              <div className="mapping-eq-cell">
                                <code className="eq-val">{m.a}</code>
                                <span className="eq-symbol">≡</span>
                                <code className="eq-val canonical">{m.b}</code>
                              </div>
                            </td>
                            <td>
                              <span className="mapping-author-pill">
                                <Icon name="user" size={12}/>
                                {m.approved_by || 'operator'}
                              </span>
                            </td>
                            <td>
                              <span className="mapping-time-pill">
                                {formatMalaysiaTime(m.approved_at)}
                              </span>
                            </td>
                            <td>
                              {m.from_email ? (
                                <button
                                  className="mapping-case-link"
                                  onClick={() => onOpenCase?.(m.from_email!)}
                                  title={`Jump to origin case ${m.from_email}`}
                                >
                                  #{m.from_email}
                                </button>
                              ) : m.note ? (
                                <span className="mapping-note">{m.note}</span>
                              ) : (
                                <span className="muted small">Direct entry</span>
                              )}
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              <button
                                className="revoke-mapping-btn"
                                disabled={isRevoking}
                                onClick={() => handleRevoke(m.kind, m.a, m.b)}
                                title="Revoke this mapping from the active library"
                              >
                                {isRevoking ? 'Revoking…' : 'Revoke'}
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ) : (
            <section className="panel-card mapping-table-card">
              {filteredCorrections.length === 0 ? (
                <div className="mapping-empty-state">
                  <div className="empty-icon-wrap"><Icon name="review" size={28}/></div>
                  <h3>No Manual Corrections Logged</h3>
                  <p>When reviewers modify field values or overrule verdicts in Case Review, audit records are logged here.</p>
                </div>
              ) : (
                <div className="mapping-table-wrap">
                  <table className="mapping-table">
                    <thead>
                      <tr>
                        <th style={{ width: '120px' }}>Case</th>
                        <th style={{ width: '160px' }}>Field / Target</th>
                        <th>Human Adjustment</th>
                        <th style={{ width: '120px' }}>Reviewer</th>
                        <th style={{ width: '165px' }}>Logged At (MYT)</th>
                        <th>Context / Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCorrections.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <button
                              className="mapping-case-link"
                              onClick={() => onOpenCase?.(row.email_id)}
                              title={`Open case ${row.email_id}`}
                            >
                              #{row.email_id}
                            </button>
                          </td>
                          <td>
                            <strong className="correction-target">
                              {row.target ? row.target.replace(/_/g, ' ') : row.kind}
                            </strong>
                          </td>
                          <td>
                            <div className="correction-val-cell">
                              {row.was && <span className="cell-was">{row.was}</span>}
                              {row.was && <span className="cell-arrow">➔</span>}
                              <span className={`cell-to ${row.corrected_to === 'MATCH' ? 'match' : row.corrected_to === 'MISMATCH' ? 'mismatch' : ''}`}>
                                {row.corrected_to}
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className="mapping-author-pill">
                              <Icon name="user" size={12}/>
                              {row.reviewer || 'operator'}
                            </span>
                          </td>
                          <td>
                            <span className="mapping-time-pill">
                              {formatMalaysiaTime(row.created_at)}
                            </span>
                          </td>
                          <td>
                            <span className="mapping-note">
                              {row.note || `${row.kind} correction`}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {/* Add Knowledge Modal */}
          {showAddModal && (
            <div className="run-modal-backdrop" onClick={() => setShowAddModal(false)}>
              <div
                className="run-modal add-knowledge-modal"
                role="dialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="modal-header">
                  <div className="modal-title-group">
                    <Icon name="plus" size={18}/>
                    <h3>Add Mapping Knowledge</h3>
                  </div>
                  <button className="modal-close-btn" onClick={() => setShowAddModal(false)}>
                    <Icon name="x" size={16}/>
                  </button>
                </div>

                <form onSubmit={handleAddMapping} className="add-knowledge-form">
                  <p className="modal-desc">
                    Define an equivalence rule. Any future document containing the variant value will automatically equate to the canonical value.
                  </p>

                  <div className="form-group">
                    <label>Domain Category</label>
                    <div className="kind-selector-row">
                      <button
                        type="button"
                        className={`kind-select-card ${addKind === 'entity' ? 'active' : ''}`}
                        onClick={() => setAddKind('entity')}
                      >
                        <Icon name="file" size={16}/>
                        <div>
                          <strong>Entity Name</strong>
                          <small>Shipper & Consignee</small>
                        </div>
                      </button>
                      <button
                        type="button"
                        className={`kind-select-card ${addKind === 'port' ? 'active' : ''}`}
                        onClick={() => setAddKind('port')}
                      >
                        <Icon name="ship" size={16}/>
                        <div>
                          <strong>Port Name</strong>
                          <small>Loading & Discharge</small>
                        </div>
                      </button>
                    </div>
                  </div>

                  <div className="form-group">
                    <label>
                      Variant / Input Value (A)
                      <small>The spelling or alias appearing in documents</small>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder={addKind === 'entity' ? "e.g. COSCO LOGISTICS SDN BHD" : "e.g. MYPKG / PORT KELANG"}
                      value={addA}
                      onChange={(e) => setAddA(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>

                  <div className="form-group">
                    <label>
                      Canonical / Equivalent Value (B)
                      <small>The standard value to match against</small>
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder={addKind === 'entity' ? "e.g. COSCO SHIPPING LINES" : "e.g. PORT KLANG"}
                      value={addB}
                      onChange={(e) => setAddB(e.target.value)}
                      required
                    />
                  </div>

                  <div className="form-group">
                    <label>
                      Note / Description (Optional)
                    </label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="e.g. Regional subsidiary alias or LOCODE equivalent"
                      value={addNote}
                      onChange={(e) => setAddNote(e.target.value)}
                    />
                  </div>

                  {addError && (
                    <div className="form-error-banner">
                      <Icon name="alert" size={15}/>{addError}
                    </div>
                  )}

                  <div className="modal-actions">
                    <button
                      type="button"
                      className="secondary-action"
                      onClick={() => setShowAddModal(false)}
                      disabled={submitting}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="primary-action"
                      disabled={submitting || !addA.trim() || !addB.trim()}
                    >
                      {submitting ? 'Saving…' : 'Save to Library'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SettingRow({ title, note, value }: { title: string; note: string; value: string }) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <small>{note}</small>
      </div>
      <span>{value}</span>
    </div>
  )
}
