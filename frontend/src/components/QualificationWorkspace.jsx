import { useEffect, useRef, useState } from 'react';
import { downloadApiFile, requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';
import ConnectionSettings from './ConnectionSettings';

export default function QualificationWorkspace({ project, identity, onChanged }) {
  const base = `/api/projects/${project.id}`;
  const targets = useApiResource(`/api/clients/${project.client_id}/installations/${project.erp_installation_id}/environments`);
  const [targetId, setTargetId] = useState(project.erp_environment_id || '');
  const target = targets.data?.find((item) => item.id === targetId);
  const capabilities = useApiResource(targetId ? `${base}/executions/capabilities/${targetId}` : null);
  const attempts = useApiResource(`${base}/executions`);
  const pkg = useApiResource(`${base}/package`);
  const [scenario, setScenario] = useState('SUCCESS');
  const [parameters, setParameters] = useState('{}');
  const [custody, setCustody] = useState(null);
  const [mode, setMode] = useState(null);
  const selectedCustody = custody ?? (target?.custody === 'ERPFUSION_MANAGED' ? 'ERPFUSION_MANAGED' : 'CUSTOMER');
  const selectedMode = mode ?? target?.execution_mode ?? 'ASSISTED';
  const [targetAck, setTargetAck] = useState(false);
  const [qualificationAck, setQualificationAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [failureContext, setFailureContext] = useState(null);
  const [remediationStage, setRemediationStage] = useState('');
  const [reconciliation, setReconciliation] = useState({ outcome: 'REQUIRES_EXTERNAL_REVIEW', evidence_note: '' });
  const pending = useRef(false);
  const roles = identity.clients?.find((client) => client.id === project.client_id)?.roles || [];
  const admin = identity.capabilities?.manage_clients || roles.includes('CLIENT_ADMIN');
  const tester = admin || roles.includes('TESTER');
  const engineer = admin || roles.some((role) => ['CONSULTANT', 'TECHNICAL_REVIEWER'].includes(role));
  const pattern = pkg.data?.manifest?.integration_pattern;
  const rows = attempts.data?.attempts || [];
  const running = rows.some((row) => ['QUEUED', 'DISPATCHING', 'REMOTE_RUNNING', 'COLLECTING_EVIDENCE'].includes(row.status));
  const reload = () => { attempts.reload(); capabilities.reload(); pkg.reload(); targets.reload(); onChanged?.(); };
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(attempts.reload, 2500);
    return () => window.clearInterval(timer);
  }, [running, attempts.reload]);
  const selectTarget = (identifier) => {
    setTargetId(identifier); setCustody(null); setMode(null);
    setTargetAck(false); setQualificationAck(false); setFailureContext(null); setRemediationStage('');
  };

  const action = async (path, body, success) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try { const result = await requestJson(`${base}/executions${path}`, { method: 'POST', body: JSON.stringify(body) }); setNotice(success); setTargetAck(false); setQualificationAck(false); reload(); return result; }
    catch (cause) { setError(cause.message); }
    finally { pending.current = false; setBusy(false); }
  };
  const request = () => {
    let values;
    try { values = JSON.parse(parameters); if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error(); } catch { setError('Execution parameters must be a JSON object.'); return; }
    void action('', { candidate_id: pkg.data.candidate_id, environment_id: targetId, idempotency_key: crypto.randomUUID(),
      operation: capabilities.data?.mode === 'SIMULATED' ? 'QUALIFY_CANDIDATE' : 'RUN_REPORT', parameters: values,
      ...(capabilities.data?.mode === 'SIMULATED' ? { scenario } : {}) }, 'Execution requested. Review its candidate, target and operation, then approve it separately.');
  };
  const download = async (row, file) => {
    try { await downloadApiFile(`${base}/executions/${row.id}/evidence/${file.name}`, file.name); }
    catch (cause) { setError(cause.message); }
  };
  const showRemediation = async (row) => {
    try { setError(''); setRemediationStage(''); setFailureContext(await requestJson(`${base}/executions/${row.id}/remediation-context`)); }
    catch (cause) { setError(cause.message); }
  };
  return <section className="workspace-card qualification-workspace">
    <div className="section-title"><div><h2>Deliverable qualification</h2><p>The selected pattern defines the qualification method. Human approval is required before dispatch.</p></div><button className="btn secondary" onClick={reload} disabled={busy}>Refresh qualification</button></div>
    {pattern ? <div className="notice slate"><strong>{pattern.name} · v{pattern.version}</strong>{pattern.runtime_type} · {pattern.deliverable_type} · {pattern.qualification_strategy}<br />{pattern.baseline_versions?.length || 0} pinned baseline versions · {pattern.configuration?.generation_rules?.strategy} v{pattern.configuration?.generation_rules?.strategy_version}</div> : <div className="notice amber">This project has no selected integration pattern. Historical generation and assisted evidence remain available; automatic execution requires a published pattern.</div>}
    {error && <div className="notice red" role="alert">{error}</div>}{notice && <div className="notice blue" role="status">{notice}</div>}
    <label className="field-label">Qualification target<select value={targetId} onChange={(event) => selectTarget(event.target.value)}>{!targetId && <option value="">Select an environment</option>}{targets.data?.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.environment_type} · {item.custody || 'UNVERIFIED'} · {item.execution_mode || 'ASSISTED'}</option>)}</select></label>
    <div className="notice slate">Allowed: HighStudio managed sandbox, customer TEST and customer UAT. Customer DEV and PROD cannot receive packages through this portal. Production deployment is the customer’s responsibility.</div>
    {admin && target && <details className="package-manifest"><summary>Review environment ownership and execution mode</summary>
      <label className="field-label">Environment custody<select value={selectedCustody} onChange={(event) => { setCustody(event.target.value); setTargetAck(false); setQualificationAck(false); }}><option value="CUSTOMER">Customer</option>{identity.capabilities?.manage_clients && <option value="ERPFUSION_MANAGED">HighStudio managed</option>}</select></label>
      <label className="field-label">Execution mode<select value={selectedMode} onChange={(event) => { setMode(event.target.value); setTargetAck(false); setQualificationAck(false); }}><option value="ASSISTED">Assisted manual</option><option value="SIMULATED">Simulated · development only</option><option value="REMOTE">Remote API</option></select></label>
      <label className="acknowledge"><input type="checkbox" checked={targetAck} onChange={(event) => setTargetAck(event.target.checked)} />I confirm ownership and intended environment. This does not verify native installation or production readiness.</label>
      <button className="btn secondary" disabled={busy || !targetAck} onClick={() => { void action('/target-review', { environment_id: targetId, custody: selectedCustody, execution_mode: selectedMode, acknowledge: true }, 'Target scope recorded. Qualify the supported capabilities next.'); }}>Save target review</button>
    </details>}
    {(capabilities.data?.blockers || []).map((blocker) => <div className="notice amber" key={blocker}>{blocker}</div>)}
    {capabilities.error && <div className="notice red">{capabilities.error}</div>}
    {capabilities.data?.mode === 'SIMULATED' && <div className="notice amber"><strong>SIMULATED qualification</strong>No ERP network connection, native installation or ERP execution occurs. A passing simulation is never live ERP evidence.</div>}
    {capabilities.data?.adapter === 'oracle_fusion_publisher' && <><div className="notice amber">Remote mode can check access and run an existing approved Publisher report. Installation and exact candidate identity verification are unqualified. A successful report cannot qualify this generated candidate for release.</div><ConnectionSettings clientId={project.client_id} installationId={target?.installation_id} environmentId={targetId} identity={identity} endpointUrl={target?.endpoint_url || ''} /></>}
    {!!capabilities.data?.capabilities?.length && <div className="history-list">{capabilities.data.capabilities.map((cap) => <div className="history-row" key={cap.name}><strong>{cap.name}</strong><span>{cap.qualified ? 'Qualified for this target' : cap.implemented ? 'Implemented · qualification required' : 'Not implemented'}</span></div>)}</div>}
    {admin && capabilities.data?.adapter && <><label className="acknowledge"><input type="checkbox" checked={qualificationAck} onChange={(event) => setQualificationAck(event.target.checked)} />I approve the implemented capabilities for this exact pattern and environment. This approval does not establish live ERP qualification.</label><button className="btn secondary" disabled={busy || !qualificationAck} onClick={() => { void action('/qualifications', { environment_id: targetId, acknowledge_environment_scope: true, acknowledge_existing_report_only: true }, 'Capability qualification recorded for 24 hours.'); }}>Approve target capabilities</button>{capabilities.data.qualification_id && <button className="btn secondary" disabled={busy || !qualificationAck} onClick={() => { void action(`/qualifications/${capabilities.data.qualification_id}/revoke`, { acknowledge: true }, 'Capability qualification revoked.'); }}>Revoke target qualification</button>}</>}
    {!pkg.data?.candidate_id && <p>Prepare the exact candidate below after all engineering gates are approved.</p>}
    {capabilities.data?.mode === 'SIMULATED' && <label className="field-label">Simulator scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}>{['SUCCESS', 'AUTHENTICATION_FAILED', 'PERMISSION_DENIED', 'INVALID_REPORT', 'INVALID_PARAMETER', 'PACKAGE_REJECTED', 'QUERY_ERROR', 'JOB_FAILED', 'TIMEOUT', 'NETWORK_ERROR', 'RATE_LIMITED', 'UNKNOWN_OUTCOME', 'OUTPUT_TOO_LARGE'].map((item) => <option key={item}>{item}</option>)}</select></label>}
    <label className="field-label">Execution parameters (JSON)<textarea rows="3" value={parameters} onChange={(event) => setParameters(event.target.value)} /></label>
    <button className="btn primary" disabled={busy || !tester || !capabilities.data?.actor_can_execute || !pkg.data?.candidate_id || !capabilities.data?.available || (capabilities.data?.mode === 'SIMULATED' && !capabilities.data?.qualification_ready)} onClick={request}>{capabilities.data?.mode === 'REMOTE' ? 'Request existing report observation' : 'Request deliverable test'}</button>
    <h3 className="subheading">Execution attempts and evidence</h3>
    {!rows.length && <p>No execution attempts. Assisted evidence remains available below.</p>}
    {rows.map((row) => <details className="package-manifest" key={row.id}><summary>{row.simulated ? 'SIMULATED' : 'REMOTE'} · {row.status} · {row.verdict} · {new Date(row.created_at).toLocaleString()}</summary>
      <p>Attempt {row.id}<br />Candidate {row.candidate_id}<br /><code>{row.candidate_checksum}</code><br />Environment {row.environment_id}<br />Operation {row.operation} · adapter {row.adapter} v{row.adapter_version}</p>
      <p>Pattern version {row.integration_pattern_version_id}</p><details><summary>Exact execution request and test-plan binding</summary><pre className="provenance-json">{JSON.stringify(row.request, null, 2)}</pre></details>
      <p>Assurance: {row.assurance?.join(', ') || 'None yet'}</p>
      {row.failure?.safe_message && <div className="notice red">{row.failure.safe_message}</div>}
      {row.status === 'UNKNOWN_OUTCOME' && <div className="notice amber">Delivery outcome is unknown. Human reconciliation is required; this attempt will never be automatically resent.</div>}
      {row.status === 'UNKNOWN_OUTCOME' && tester && !row.result?.reconciliation && <fieldset disabled={busy} style={{ border: 0 }}><label className="field-label">Reconciliation outcome<select value={reconciliation.outcome} onChange={(event) => setReconciliation({ ...reconciliation, outcome: event.target.value })}>{['REQUIRES_EXTERNAL_REVIEW', 'CONFIRMED_NO_EXECUTION', 'CONFIRMED_FAILED'].map((outcome) => <option key={outcome}>{outcome}</option>)}</select></label><label className="field-label">Human reconciliation evidence<textarea required minLength="1" maxLength="4000" value={reconciliation.evidence_note} onChange={(event) => setReconciliation({ ...reconciliation, evidence_note: event.target.value })} /></label><button className="btn secondary" disabled={!reconciliation.evidence_note.trim()} onClick={() => { void action(`/${row.id}/reconcile`, { ...reconciliation, acknowledge: true }, 'Reconciliation recorded as assisted evidence. This does not turn the unknown attempt into a passing test.'); }}>Record human reconciliation</button></fieldset>}
      {row.result?.reconciliation && <p>Assisted reconciliation: {row.result.reconciliation.outcome}</p>}
      {row.status === 'AWAITING_APPROVAL' && tester && <button className="btn primary" disabled={busy} onClick={() => { void action(`/${row.id}/approve`, { acknowledge: true }, 'Approved. The execution worker will process this exact request.'); }}>Approve this exact test</button>}
      {['AWAITING_APPROVAL', 'QUEUED'].includes(row.status) && tester && <button className="btn secondary" disabled={busy} onClick={() => { void action(`/${row.id}/cancel`, { acknowledge: true }, 'Execution cancelled before dispatch.'); }}>Cancel before dispatch</button>}
      {row.result?.files?.map((file) => <button className="btn secondary" key={file.name} onClick={() => { void download(row, file); }}>Download {file.name}</button>)}
      {row.status === 'COMPLETED' && row.verdict === 'PASSED' && tester && <button className="btn primary" disabled={busy} onClick={() => { void action(`/${row.id}/sign-off`, { acknowledge: true }, row.simulated ? 'Simulated release signed. It is not ERP-qualified.' : 'Release sign-off recorded.'); }}>Sign off {row.simulated ? 'simulated ' : ''}evidence</button>}
      {['FAILED', 'UNKNOWN_OUTCOME', 'BLOCKED', 'SUPERSEDED'].includes(row.status) && (tester || engineer) && <button className="btn secondary" onClick={() => { void showRemediation(row); }}>Review safe failure context</button>}
    </details>)}
    {failureContext && <details className="package-manifest" open><summary>Sanitized remediation context · review required</summary><pre className="provenance-json">{JSON.stringify(failureContext, null, 2)}</pre><p>A correction creates a new revision and invalidates downstream approvals. Failed evidence remains in history.</p>{engineer && <><label className="field-label">Stage to revise<select value={remediationStage} onChange={(event) => setRemediationStage(event.target.value)}><option value="">Select the engineering stage</option>{Object.keys(pkg.data?.manifest?.artifacts || {}).map((stage) => <option key={stage} value={stage}>{stage}</option>)}</select></label><button className="btn primary" disabled={busy || !remediationStage} onClick={() => { void action(`/${failureContext.attempt_id}/remediate`, { stage: remediationStage, acknowledge: true }, 'Correction queued with sanitized failure context. Review and approve the new revision before testing a new candidate.'); }}>Generate correction for review</button></>}</details>}
  </section>;
}
