import React, { useEffect, useRef, useState } from 'react';
import { FileText, Upload, Download, ShieldCheck } from 'lucide-react';
import { downloadApiFile, requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';
import { dateLabel, label } from '../utils/product';

export default function RequirementsWorkspace({ project, erpProfiles = [], canEdit, onSaved, busy, onDirtyChange }) {
  const documents = useApiResource(`/api/projects/${project.id}/requirements`, project.requirement_version || 0);
  const patterns = useApiResource(project.erp_profile_id ? `/api/integration-patterns?erp_profile_id=${project.erp_profile_id}` : null);
  const [patternChoice, setPatternChoice] = useState('');
  const selectedPattern = patterns.data?.flatMap((pattern) => pattern.versions.map((version) => ({ ...version, name: pattern.name }))).find((version) => version.id === patternChoice);
  const [text, setText] = useState(project.business_requirement || '');
  const [context, setContext] = useState(JSON.stringify(project.erp_schema_context || {}, null, 2));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedDocumentId, setSelectedDocumentId] = useState('');
  const [dragging, setDragging] = useState(false);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const pending = useRef(false);
  const files = documents.data || [];
  const selectedDocument = files.find((file) => file.id === selectedDocumentId) || null;
  const dirty = text !== (project.business_requirement || '') || context !== JSON.stringify(project.erp_schema_context || {}, null, 2);
  const newerProfile = !project.integration_pattern_version_id && erpProfiles.find((profile) => profile.id === project.erp_profile_id
    && profile.profile_version_id !== project.erp_profile_version_id
    && profile.profile_version > project.erp_version);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const save = async () => {
    if (!canEdit || pending.current) return;
    let schema;
    try { schema = JSON.parse(context); if (!schema || typeof schema !== 'object' || Array.isArray(schema)) throw new Error(); }
    catch { setError('ERP context must be a JSON object.'); return; }
    pending.current = true; setSaving(true); setError(''); setNotice('');
    try {
      await requestJson(`/api/projects/${project.id}`, { method: 'PATCH', body: JSON.stringify({ business_requirement: text, erp_schema_context: schema, expected_requirement_version: project.requirement_version, expected_schema_context_version: project.schema_context_version }) });
      setNotice('Requirement revision saved. Review and generate from the updated scope.'); onSaved();
    } catch (cause) { setError(cause.message); }
    finally { pending.current = false; setSaving(false); }
  };
  const upload = async (fileList) => {
    if (!canEdit || pending.current || !fileList?.length) return;
    if (dirty && !window.confirm('Uploading adds extracted text to the saved requirement. Discard your unsaved edits?')) return;
    pending.current = true; setSaving(true); setError(''); setNotice('');
    try {
      let expectedVersion = project.requirement_version;
      for (const file of fileList) {
        if (!/\.(pdf|docx|txt|md)$/i.test(file.name) || file.size > 10 * 1024 * 1024) throw new Error('Use PDF, DOCX, TXT or Markdown files under 10 MB.');
        const form = new FormData(); form.append('file', file);
        form.append('expected_requirement_version', String(expectedVersion));
        const saved = await requestJson(`/api/projects/${project.id}/requirements`, { method: 'POST', body: form });
        expectedVersion = saved.requirement_version;
        setSelectedDocumentId(saved.id); setNotice(saved.extraction_status === 'READY' ? 'Document uploaded. Review the extracted requirement before generation.' : saved.extraction_error || 'Document uploaded. Extraction requires review.');
      }
      const updated = await requestJson(`/api/projects/${project.id}`);
      setText(updated.business_requirement || '');
      setContext(JSON.stringify(updated.erp_schema_context || {}, null, 2));
      documents.reload(); onSaved();
    } catch (cause) { setError(cause.message); documents.reload(); onSaved(); }
    finally { pending.current = false; setSaving(false); }
  };
  const download = async (file) => {
    try { await downloadApiFile(`/api/projects/${project.id}/requirements/${file.id}/download`, file.filename); }
    catch (cause) { setError(cause.message); }
  };
  const upgrade = async () => {
    if (!canEdit || dirty || busy || pending.current || !newerProfile) return;
    pending.current = true; setSaving(true); setError('');
    try {
      await requestJson(`/api/projects/${project.id}`, { method: 'PATCH', body: JSON.stringify({
        erp_profile_version_id: newerProfile.profile_version_id,
        expected_erp_profile_version_id: project.erp_profile_version_id,
        expected_requirement_version: project.requirement_version,
        expected_schema_context_version: project.schema_context_version,
      }) });
      setShowUpgrade(false); setNotice('ERP profile upgraded. Regenerate and review each stage.'); onSaved();
    } catch (cause) { setError(cause.message); }
    finally { pending.current = false; setSaving(false); }
  };
  const changePattern = async () => {
    if (!canEdit || dirty || busy || pending.current || !selectedPattern) return;
    if (!window.confirm('Change the integration pattern and restart the active workflow? Approvals become stale; previous deliverables and evidence remain in History.')) return;
    pending.current = true; setSaving(true); setError('');
    try {
      await requestJson(`/api/projects/${project.id}`, { method: 'PATCH', body: JSON.stringify({
        integration_pattern_version_id: selectedPattern.id,
        expected_integration_pattern_version_id: project.integration_pattern_version_id || null,
        erp_profile_version_id: selectedPattern.profile_version_id,
        expected_erp_profile_version_id: project.erp_profile_version_id,
        expected_requirement_version: project.requirement_version,
        expected_schema_context_version: project.schema_context_version,
      }) });
      setPatternChoice(''); setNotice('Pattern changed. Regenerate and review every affected stage.'); onSaved();
    } catch (cause) { setError(cause.message); }
    finally { pending.current = false; setSaving(false); }
  };
  return <div className="studio-layout">
    <section className="workspace-card"><div className="section-title"><span className="section-icon"><Upload className="icon" /></span><div><h2>Start with the requirement document</h2><p>Upload the brief from your consulting team.</p></div></div>
      {(error || documents.error) && <div role="alert" className="notice red">{error || documents.error}</div>}{notice && <div role="status" className="notice blue">{notice}</div>}
      <label className={`dropzone ${dragging ? 'dragging' : ''} ${!canEdit ? 'disabled' : ''}`} onDragOver={(event) => { event.preventDefault(); if (canEdit) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files); }}><input aria-label="Upload requirement documents" type="file" accept=".pdf,.docx,.txt,.md" multiple disabled={!canEdit || saving || busy} onChange={(event) => { void upload(event.target.files); event.target.value = ''; }} /><span className="upload-illustration"><Upload className="icon" /></span><strong>{saving ? 'Saving requirement document…' : 'Drop your requirement files here'}</strong><span>or <b>browse files</b></span><small>PDF, DOCX, TXT or Markdown · up to 10 MB each</small></label>
      <div className="file-list">{documents.loading && <p role="status">Loading requirement documents…</p>}{files.map((file) => <div className="uploaded-file" key={file.id}><FileText className="icon" /><button className="file-preview-button" onClick={() => setSelectedDocumentId(file.id)}><strong>{file.filename}</strong><small>{Math.ceil(file.size_bytes / 1024)} KB · {label(file.extraction_status)} · Scan: {label(file.scan_status || 'NOT_CONFIGURED')} · {dateLabel(file.created_at)}</small></button><button className="icon-button" title="Download original" aria-label={`Download ${file.filename}`} onClick={() => { void download(file); }}><Download className="icon" /></button></div>)}</div>
      {selectedDocument && <details open className="requirement-original"><summary>Original source: {selectedDocument.filename}</summary>{selectedDocument.extraction_error && <p className="notice amber">{selectedDocument.extraction_error}</p>}<pre className="provenance-json">{selectedDocument.extracted_text || 'Text is unavailable. Download the original document and add the reviewed requirement below.'}</pre><small>SHA-256: {selectedDocument.checksum}</small></details>}
      <label className="field-label" htmlFor="requirement-text">Requirement text <span className="optional">editable preview</span></label><textarea className="brief" id="requirement-text" value={text} onChange={(event) => setText(event.target.value)} disabled={!canEdit || saving || busy} placeholder="Upload a requirement document or paste the reviewed scope here." />
      <p className="input-note">Save this scope before generating. Changing it invalidates active downstream approvals; prior revisions remain in History.</p>
      <details className="context-editor"><summary>ERP schema and context</summary><label className="field-label" htmlFor="requirement-context">ERP context (JSON)</label><textarea id="requirement-context" className="brief code-input" value={context} onChange={(event) => setContext(event.target.value)} disabled={!canEdit || saving || busy} /></details>
      <div className="workspace-bottom"><span>Requirement revision {project.requirement_version || 1}</span><button className="btn primary" disabled={!canEdit || saving || busy || !dirty} onClick={() => { void save(); }}>{saving ? 'Saving…' : 'Save requirement revision'}</button></div>
    </section>
    <aside className="context-panel"><section className="context-card"><div className="context-heading"><ShieldCheck className="icon" /><h3>Requirement scope</h3></div><p>Review the source documents, extracted text, assumptions and clarifications before approving the generated assessment.</p><dl><dt>Client</dt><dd>{project.client_name}</dd><dt>ERP profile</dt><dd>{project.erp_name} v{project.erp_version}</dd><dt>Documents</dt><dd>{files.length} uploaded</dd><dt>Last activity</dt><dd>{dateLabel(project.last_activity_at || project.updated_at)}</dd></dl>{canEdit && newerProfile && <><p>A newer published profile is available. Your project remains pinned until you choose to upgrade.</p><button className="btn secondary" disabled={dirty || saving || busy} onClick={() => setShowUpgrade(true)}>Use ERP profile v{newerProfile.profile_version}</button>{dirty && <p>Save requirement edits before upgrading.</p>}</>}</section></aside>
    {canEdit && !!patterns.data?.some((pattern) => pattern.versions.length) && <section className="workspace-card"><h3>Integration pattern</h3><p>{project.integration_pattern_name || 'Legacy profile workflow'}{project.integration_pattern_version ? ` · v${project.integration_pattern_version}` : ''}. Select a different published pattern/version only through an explicit workflow revision.</p><label className="field-label">Pattern and version<select value={patternChoice} disabled={dirty || saving || busy} onChange={(event) => setPatternChoice(event.target.value)}><option value="">Keep the pinned pattern</option>{patterns.data.flatMap((pattern) => pattern.versions.filter((version) => version.id !== project.integration_pattern_version_id).map((version) => <option key={version.id} value={version.id}>{pattern.name} · v{version.version} · {version.implementation_status}</option>))}</select></label><button className="btn secondary" disabled={!selectedPattern || dirty || saving || busy} onClick={() => { void changePattern(); }}>Change pattern and restart workflow</button></section>}
    {showUpgrade && newerProfile && <div className="hr-modal-overlay" role="dialog" aria-modal="true" aria-label="Upgrade ERP profile"><div className="hr-modal-content"><h2>Upgrade {project.erp_name} from v{project.erp_version} to v{newerProfile.profile_version}</h2><p>This restarts the active workflow and invalidates its approvals. Previous generations, decisions and downloads remain in History.</p><div className="modal-footer"><button className="btn secondary" disabled={saving} onClick={() => setShowUpgrade(false)}>Cancel</button><button className="btn primary" disabled={saving || dirty || busy} onClick={() => { void upgrade(); }}>Confirm profile upgrade</button></div></div></div>}
  </div>;
}
