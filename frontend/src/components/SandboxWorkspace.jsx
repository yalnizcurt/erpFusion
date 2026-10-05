import { useMemo, useState } from 'react';
import { Check, Download, PackageCheck, RefreshCw, ShieldCheck, TestTube2 } from 'lucide-react';
import { downloadApiFile, requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';

const hash = async (value) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))), (byte) => byte.toString(16).padStart(2, '0')).join('');
const pretty = (value) => JSON.stringify(value, null, 2);
const clientRoles = (identity, clientId) => identity?.clients?.find((client) => client.id === clientId)?.roles || [];

export default function SandboxWorkspace({ project, identity, mode = 'sandbox', onChanged }) {
  const base = `/api/projects/${project.id}`;
  const pkg = useApiResource(`${base}/package`);
  const releasesResource = useApiResource(`${base}/package/releases`);
  const evidenceResource = useApiResource(`${base}/sandbox/evidence`);
  const environments = useApiResource(project.client_id && project.erp_installation_id
    ? `/api/clients/${project.client_id}/installations/${project.erp_installation_id}/environments` : null);
  const connection = useApiResource(project.client_id && project.erp_installation_id && project.erp_environment_id
    ? `/api/clients/${project.client_id}/installations/${project.erp_installation_id}/environments/${project.erp_environment_id}/connection` : null);
  const roles = clientRoles(identity, project.client_id);
  const canBuild = !!identity?.capabilities?.manage_clients || roles.some((role) => ['CLIENT_ADMIN', 'CONSULTANT', 'TECHNICAL_REVIEWER'].includes(role));
  const canTest = !!identity?.capabilities?.manage_clients || roles.some((role) => ['CLIENT_ADMIN', 'TESTER'].includes(role));
  const environment = environments.data?.find((item) => item.id === project.erp_environment_id);
  const targetAllowed = environment?.status === 'ACTIVE' && ((environment.custody === 'ERPFUSION_MANAGED' && environment.environment_type === 'SANDBOX') || (environment.custody === 'CUSTOMER' && ['TEST', 'UAT'].includes(environment.environment_type)));
  const connectionRequired = evidenceResource.data?.manual_connection_required !== false;
  const connectionReady = !connectionRequired || !!connection.data?.configured;
  const patternBinding = pkg.data?.manifest;
  const baselineVersions = patternBinding?.baseline_versions || [];
  const evidence = evidenceResource.data?.evidence || [];
  const plan = evidenceResource.data?.test_plan;
  const [candidate, setCandidate] = useState(null);
  const [caseValues, setCaseValues] = useState({});
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const currentCandidate = candidate?.id === pkg.data?.candidate_id
    ? candidate
    : pkg.data?.candidate_id && (pkg.data?.candidate_checksum || pkg.data?.checksum)
      ? { id: pkg.data.candidate_id, checksum: pkg.data.candidate_checksum || pkg.data.checksum }
      : null;
  const latestEvidence = evidence.find((item) => item.candidate_id === currentCandidate?.id && item.environment_id === project.erp_environment_id);
  const releaseId = pkg.data?.release_id;
  const releases = releasesResource.data?.releases || [];
  const isRelease = mode === 'release';
  const blockers = useMemo(() => evidenceResource.data?.blockers || pkg.data?.blockers || [], [evidenceResource.data, pkg.data]);

  const refresh = () => {
    pkg.reload(); evidenceResource.reload(); releasesResource.reload(); environments.reload(); connection.reload();
    onChanged?.({ ready: !!pkg.data?.available, candidateId: pkg.data?.candidate_id || null, releaseId: pkg.data?.release_id || null });
  };
  const prepareCandidate = async () => {
    setPending(true); setError(''); setNotice('');
    try {
      const result = await requestJson(`${base}/package/candidates`, { method: 'POST', body: '{}' });
      setCandidate(result); setNotice('Source bundle checksum confirmed. Download and review the source files, then build and install them with the ERP’s approved tooling before recording results.');
      refresh();
    } catch (cause) { setError(cause.message); }
    finally { setPending(false); }
  };

  const recordEvidence = async (event) => {
    event.preventDefault();
    if (!currentCandidate || !plan || !connectionReady || !targetAllowed || !acknowledged) return;
    setPending(true); setError(''); setNotice('');
    try {
      const cases = await Promise.all(plan.required_cases.map(async (testCase) => {
        const value = caseValues[testCase.id] || {};
        const actual = JSON.parse(value.actual || 'null');
        return {
          id: testCase.id,
          status: value.status || 'NOT_RUN',
          expected: testCase.expected,
          actual,
          evidence_note: value.observation,
          evidence_sha256: await hash(value.observation),
        };
      }));
      await requestJson(`${base}/sandbox/evidence`, { method: 'POST', body: JSON.stringify({
        candidate_id: currentCandidate.id,
        environment_id: project.erp_environment_id,
        candidate_checksum: currentCandidate.checksum,
        reviewed_source_checksum: currentCandidate.checksum,
        connection_version: connection.data?.configuration_version || null,
        test_plan_sha256: evidenceResource.data.test_plan_sha256,
        cases,
        acknowledge_assisted_evidence: true,
      }) });
      setNotice('Manual evidence recorded. The checksum identifies the reviewed source bundle only; installed bytes, native build, and runtime were not independently verified.');
      setCaseValues({}); setAcknowledged(false); refresh();
    } catch (cause) { setError(cause instanceof SyntaxError ? 'Each actual result must be valid JSON.' : cause.message); }
    finally { setPending(false); }
  };

  const signOff = async (item) => {
    setPending(true); setError(''); setNotice('');
    try {
      const result = await requestJson(`${base}/sandbox/evidence/${item.id}/sign-off`, { method: 'POST', body: JSON.stringify({ acknowledge_assisted_evidence: true }) });
      setNotice(`Release signed: ${result.id}. The immutable release ZIP is ready to download.`);
      refresh();
    } catch (cause) { setError(cause.message); }
    finally { setPending(false); }
  };

  const download = async (id, kind) => {
    setPending(true); setError('');
    try { await downloadApiFile(`${base}/package/${kind}s/${id}/download`, `${kind}-${id}.zip`); }
    catch (cause) { setError(cause.message); }
    finally { setPending(false); }
  };

  const loading = pkg.loading || evidenceResource.loading || releasesResource.loading || environments.loading || connection.loading;
  if (loading && !pkg.data) return <section className="workspace-card" role="status">Loading package and sandbox evidence…</section>;

  return <div className="studio-layout sandbox-workspace">
    <section className="workspace-card">
      <div className="section-title"><span className="section-icon"><TestTube2 className="icon" /></span><div><h2>{isRelease ? 'Release sign-off' : 'Sandbox testing'}</h2><p>Evidence is bound to the approved candidate and this project’s configured environment.</p></div><button className="btn secondary" onClick={refresh} disabled={pending}><RefreshCw className="icon" />Refresh</button></div>
      <div className="notice amber"><strong>Manual assisted testing</strong>Review the deliverable and perform the selected pattern’s approved qualification steps. Installation applies only to patterns with an ERP-native artifact. A source ZIP is not a qualified native package. Human observations do not independently verify remote bytes or execution.</div>
      {error && <div className="notice red" role="alert">{error}</div>}
      {notice && <div className="notice green" role="status">{notice}</div>}
      {pkg.error && <div className="notice red" role="alert">{pkg.error}</div>}
      {evidenceResource.error && <div className="notice red" role="alert">{evidenceResource.error}</div>}
      {connection.error && <div className="notice amber" role="alert">Connection details unavailable: {connection.error}</div>}
      <div className="environment-tile"><ShieldCheck className="environment-icon" /><div><strong>{environment?.display_name || 'Project environment'}</strong><small>{environment?.environment_type || 'Environment type unavailable'} · {project.erp_environment_id || 'No environment selected'}</small></div><span className={`badge ${targetAllowed ? 'green' : 'amber'}`}>{targetAllowed ? 'Allowed qualification target' : environment ? 'Blocked or unverified target' : 'Checking target'}</span></div>
      {connectionRequired
        ? <div className="notice blue">Evidence binds the reviewed source bundle checksum, environment ID, connection configuration version {connection.data?.configuration_version ?? 'unavailable'}, and the current secret version on the server. The checksum does not identify installed bytes. Secret version is not exposed by the connection API.</div>
        : <div className="notice blue">Evidence binds the reviewed source bundle checksum, pattern version {patternBinding?.integration_pattern_version_id || 'unavailable'}, approved baselines {baselineVersions.map((item) => `${item.asset_id} v${item.version}`).join(', ') || 'none'}, and target environment {environment?.display_name || project.erp_environment_id || 'unavailable'}. The checksum does not identify installed bytes. {connection.data?.configured ? `Configured connection version ${connection.data.configuration_version ?? 'unavailable'} and its current secret are bound on the server.` : 'No ERP connection or secret is required for this assisted evidence.'}</div>}
      {!!blockers.length && <div className="notice amber"><strong>Candidate / release blockers</strong>{blockers.map((item) => <p key={item}>{item}</p>)}</div>}

      <div className="workspace-bottom"><span>{currentCandidate ? <>Candidate <code>{currentCandidate.id}</code><br />SHA-256 <code>{currentCandidate.checksum}</code></> : pkg.data?.candidate_id ? <>Current candidate: {pkg.data.candidate_id}. Refresh it to confirm its checksum.</> : 'No current candidate prepared.'}</span>{(!currentCandidate || !pkg.data?.candidate_id) && <button className="btn primary" disabled={!canBuild || pending || !pkg.data?.available} onClick={() => { void prepareCandidate(); }}><PackageCheck className="icon" />{pending ? 'Working…' : 'Prepare exact candidate'}</button>}</div>
      {currentCandidate && <button className="btn secondary" disabled={pending} onClick={() => { void download(currentCandidate.id, 'candidate'); }}><Download className="icon" />Download source bundle ZIP</button>}

      {!isRelease && <form onSubmit={recordEvidence}>
        <h3 className="subheading">Configured test plan · {plan?.version || 'unavailable'}</h3>
        {!plan?.required_cases?.length && <p role="status">No approved test plan is available.</p>}
        {plan?.required_cases?.map((testCase) => {
          const value = caseValues[testCase.id] || {};
          return <div className="test-row" key={testCase.id} style={{ alignItems: 'stretch', flexDirection: 'column' }}>
            <div><strong>{testCase.id}</strong><small>Expected: <code>{pretty(testCase.expected)}</code></small></div>
            <label className="field-label">Observed result (JSON)<textarea required rows="3" value={value.actual ?? ''} onChange={(event) => setCaseValues({ ...caseValues, [testCase.id]: { ...value, actual: event.target.value } })} placeholder="Enter the result you observed after running this case" /></label>
            <label className="field-label">Outcome<select required value={value.status || 'NOT_RUN'} onChange={(event) => setCaseValues({ ...caseValues, [testCase.id]: { ...value, status: event.target.value } })}><option value="NOT_RUN">Not run</option><option value="PASSED">Passed</option><option value="FAILED">Failed</option><option value="BLOCKED">Blocked</option></select></label>
            <label className="field-label">Observation / evidence note<textarea required minLength="1" maxLength="4000" rows="2" value={value.observation || ''} onChange={(event) => setCaseValues({ ...caseValues, [testCase.id]: { ...value, observation: event.target.value } })} placeholder="What you observed while building or testing in the ERP sandbox" /></label>
          </div>;
        })}
        <label className="acknowledge"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />I reviewed the deliverable with the displayed checksum and ran the pattern’s approved test cases in this authorized environment. Any required native build/import was performed using approved tooling. These observations are human attestations, not independent machine verification.</label>
        <button className="btn primary" type="submit" disabled={!canTest || pending || !currentCandidate || !plan?.required_cases?.length || !connectionReady || !targetAllowed || environment?.execution_mode === 'SIMULATED' || !acknowledged}>Record assisted test evidence</button>
      </form>}
    </section>

    <aside className="context-panel">
      <section className="context-card"><div className="context-heading"><Check className="icon" /><h3>Evidence history</h3></div>
        {!evidence.length && <p>No test attestations recorded.</p>}
        {evidence.map((item) => <div className="event-log" key={item.id}><div><span>{new Date(item.created_at).toLocaleString()} · {item.method}</span><strong>{item.status} · {item.id}</strong><small>Candidate {item.candidate_id}<br />SHA-256 {item.candidate_checksum}<br />Environment {item.environment_id} · connection v{item.connection_version ?? 'not required'}</small>{item.status === 'PASSED' && item.method === 'ASSISTED_MANUAL' && !item.execution_attempt_id && <button className="btn primary full" disabled={!canTest || pending || evidenceResource.data?.assisted_release_allowed === false || item.id !== latestEvidence?.id || !currentCandidate || !connectionReady || item.connection_version !== (connection.data?.configuration_version || null) || !targetAllowed || releaseId} onClick={() => { void signOff(item); }}>Sign off this evidence</button>}</div></div>)}
      </section>
      <section className="context-card"><div className="context-heading"><PackageCheck className="icon" /><h3>Release history</h3></div>
        {!releases.length && <p>No signed release history.</p>}
        {releases.map((release) => <div className="event-log" key={release.id}><div><span>{new Date(release.created_at).toLocaleString()} {release.id === releaseId ? '· Current' : ''}</span><strong>Release {release.id}</strong><small>Candidate {release.candidate_id}<br />Evidence {release.evidence_id}<br />SHA-256 {release.checksum}</small><button className="btn primary full" disabled={pending} onClick={() => { void download(release.id, 'release'); }}><Download className="icon" />Download immutable release ZIP</button></div></div>)}
      </section>
      {isRelease && <div className="notice blue">Sign-off is available only for the latest passing evidence bound to the current candidate and unchanged pattern-specific target and any required connection bindings. The release ZIP contains the candidate, test report, and signed release manifest.</div>}
    </aside>
  </div>;
}
