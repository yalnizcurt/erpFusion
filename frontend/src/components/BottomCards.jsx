import React, { useRef, useState } from 'react';
import { FileText, ShieldCheck, GitCompare, FileDown, Lock } from 'lucide-react';
import { label } from '../utils/product';

function DocumentValue({ value }) {
  if (value == null) return <span className="muted">Not provided</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  if (Array.isArray(value)) return <div className="document-items">{value.map((item, index) => <div key={index}><DocumentValue value={item} /></div>)}</div>;
  return <dl className="document-fields">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{label(key)}</dt><dd><DocumentValue value={item} /></dd></div>)}</dl>;
}

export default function BottomCards({ artifact, versions = [], selectedVersion, onSelectVersion, validations = [], onApprove, onRequestChanges, onReject, onOpenDiff, canReview = false, isReviewing = false, approvalBlockers = [] }) {
  const [view, setView] = useState('doc');
  const [dialog, setDialog] = useState(null);
  const [comments, setComments] = useState('');
  const [error, setError] = useState('');
  const [pdfError, setPdfError] = useState('');
  const pending = useRef(false);
  const content = selectedVersion?.content || {};
  const historical = !!selectedVersion && artifact?.current_version !== undefined && artifact.current_version !== selectedVersion.version_number;
  const reviewable = selectedVersion?.state === 'PENDING_HUMAN_REVIEW' && !historical && canReview;
  const submit = async (action) => {
    if (!reviewable || isReviewing || pending.current) return;
    pending.current = true; setError('');
    try { await action(); setDialog(null); setComments(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Review failed.'); }
    finally { pending.current = false; }
  };
  const decide = () => {
    if (!comments.trim()) { setError('Enter reviewer feedback.'); return; }
    void submit(() => (dialog === 'reject' ? onReject : onRequestChanges)(selectedVersion.version_number, undefined, comments.trim()));
  };
  const exportPdf = async () => {
    setPdfError('');
    let popup;
    try {
      popup = window.open('', '_blank');
      if (!popup) throw new Error('Allow pop-ups to view the PDF.');
      const { createArtifactPdf } = await import('../utils/generatePdf');
      const url = URL.createObjectURL(await createArtifactPdf(artifact, selectedVersion));
      popup.location.href = url;
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) {
      popup?.close();
      setPdfError(cause instanceof Error ? cause.message : 'Could not create the PDF.');
    }
  };
  return <div className="studio-layout artifact-review-layout">
    <section className="workspace-card document-card">
      <div className="document-toolbar"><div><FileText className="icon" /><strong>{label(artifact?.artifact_type || 'Artifact')}</strong>{selectedVersion && <span className="version">v{selectedVersion.version_number}</span>}</div><div className="artifact-toolbar-actions">
        {versions.length > 0 && <label className="revision-select">Revision:<select aria-label="Artifact revision" value={selectedVersion?.version_number || ''} disabled={isReviewing} onChange={(event) => onSelectVersion?.(Number(event.target.value))}>{versions.map((version) => <option key={version.id || version.version_number} value={version.version_number}>v{version.version_number} ({version.state})</option>)}</select></label>}
        <div className="view-toggle">{[['doc', 'Document'], ['code', 'SQL / Code'], ['json', 'JSON']].map(([id, title]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{title}</button>)}</div>
        <button className="icon-button" aria-label="View as PDF" title="View as PDF" disabled={!selectedVersion} onClick={() => { void exportPdf(); }}><FileDown className="icon" /></button>{versions.length > 1 && <button className="icon-button" aria-label="Diff" title="Compare revisions" onClick={onOpenDiff}><GitCompare className="icon" /></button>}
      </div></div>
      {historical && <div className="notice slate">Historical revision. Read only; the active workflow is unchanged.</div>}
      {!selectedVersion ? <div className="locked-workspace"><span className="big-icon"><FileText className="icon" /></span><h2>No generated artifact yet</h2><p>Generate the selected stage after its prerequisites are approved.</p></div> : view === 'doc' ? <article className="document"><div className="document-brand"><span>High<span>Studio</span></span><span>ENGINEERING DOCUMENT</span></div><div className="document-eyebrow">{label(artifact?.artifact_type)} / V{selectedVersion.version_number}</div><h2>{content.document_title || content.business_objective || label(artifact?.artifact_type)}</h2><div className="document-metadata"><span>{label(selectedVersion.state)}</span></div><div className="document-rule" /><div className="document-body"><DocumentValue value={content} /></div></article> : <pre className="code-container json-view" style={{ maxWidth: '100%', overflow: 'auto', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{view === 'json' ? JSON.stringify(content, null, 2) : content.extraction_sql || content.pks_content || content.pkb_content || JSON.stringify(content, null, 2)}</pre>}
      <div className="document-disclaimer"><Lock className="icon" />Approvals apply to the exact artifact revision.</div>
      {pdfError && <p role="alert" className="error-text">{pdfError}</p>}
    </section>
    <aside className="context-panel"><section className="context-card"><div className="context-heading"><ShieldCheck className="icon" /><h3>Review & approval</h3></div><span className={`badge ${selectedVersion?.state === 'APPROVED' ? 'green' : 'amber'}`}>{selectedVersion ? label(selectedVersion.state) : 'Awaiting generation'}</span><p>Review the document and required validations before approving this revision.</p>
      {validations.length ? <div className="validation-list">{validations.map((validation, index) => <div key={validation.id || index}><strong>{label(validation.category)}</strong><span className={`badge ${validation.status === 'PASS' ? 'green' : validation.status === 'FAIL' ? 'red' : 'amber'}`}>{validation.status}</span>{validation.checks?.map((check, checkIndex) => <p key={checkIndex}>{check.message}</p>)}</div>)}</div> : <div className="notice slate">No validation evidence is available.</div>}
      {error && !dialog && <p role="alert" className="error-text">{error}</p>}
      {reviewable && approvalBlockers.length > 0 && <div className="notice amber"><strong>Clarifications required before approval</strong>{approvalBlockers.map((blocker, index) => <p key={index}>{blocker}</p>)}<p>Update the requirement or context and regenerate this assessment.</p></div>}
      {reviewable && <div className="review-actions"><button disabled={isReviewing || approvalBlockers.length > 0} className="btn primary full" onClick={() => { setDialog('approve'); setError(''); }}>Approve Gate</button><button disabled={isReviewing} className="btn secondary full" onClick={() => { setDialog('changes'); setError(''); }}>Request Changes</button><button disabled={isReviewing} className="btn ghost full" onClick={() => { setDialog('reject'); setError(''); }}>Reject</button></div>}
      {!canReview && selectedVersion && <p>{selectedVersion.state !== 'PENDING_HUMAN_REVIEW' || historical ? 'This revision is read only. Generate a new revision to continue.' : 'Review is unavailable. Check the active workflow and your reviewer permissions.'}</p>}
    </section><section className="context-card"><div className="context-heading"><FileText className="icon" /><h3>Source provenance</h3></div><details><summary>Why was this generated this way?</summary><pre className="provenance-json">{JSON.stringify(selectedVersion?.input_context_snapshot || {}, null, 2)}</pre></details></section></aside>
    {dialog && <div className="hr-modal-overlay" role="dialog" aria-modal="true" aria-label={dialog === 'approve' ? 'Approve artifact revision' : dialog === 'reject' ? 'Reject artifact' : 'Request artifact changes'}><div className="hr-modal-content"><h2>{dialog === 'approve' ? 'Approve' : dialog === 'reject' ? 'Reject' : 'Request Changes on'} {artifact?.artifact_type} v{selectedVersion?.version_number}</h2>{dialog === 'approve' ? <p>Confirm approval of this exact artifact revision.</p> : <><p>Describe the changes needed for the next revision.</p><label className="field-label" htmlFor="review-comments">Review feedback</label><textarea id="review-comments" className="feedback" value={comments} onChange={(event) => setComments(event.target.value)} disabled={isReviewing} /></>}{error && <p role="alert" className="error-text">{error}</p>}<div className="modal-footer"><button className="btn secondary" disabled={isReviewing} onClick={() => setDialog(null)}>Cancel</button><button className="btn primary" disabled={isReviewing} onClick={dialog === 'approve' ? () => void submit(() => onApprove(selectedVersion.version_number)) : decide}>{dialog === 'approve' ? 'Confirm approval' : dialog === 'reject' ? 'Confirm rejection' : 'Submit Change Request'}</button></div></div></div>}
  </div>;
}
