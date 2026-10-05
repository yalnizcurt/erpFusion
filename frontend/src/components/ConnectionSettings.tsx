import { useEffect, useRef, useState } from 'react';
import { Plug, ShieldCheck } from 'lucide-react';
import { APIError, requestJson } from '../api';
import type { CurrentIdentity } from '../contracts/identity';

type Connection = {
  adapter: string;
  source_url: string; expected_tenant: string; report_path: string; approved_hosts: string[]; permitted_operations: string[];
  configuration_version: number; configured: boolean;
  last_verification: { network: string; authentication: string; tenant: string; permissions: string; report_execution: string; import_capability: string; diagnostic_code: string; checked_at: string; expires_at: string; latency_ms: number | null; current: boolean } | null;
};
const empty = { adapter: 'metadata_only', source_url: '', expected_tenant: '', report_path: '', approved_hosts: '', permitted_operations: ['PING', 'RUN_REPORT'] };
export default function ConnectionSettings({ clientId, installationId, environmentId, identity, endpointUrl = '' }: {
  clientId: string | null; installationId: string | null; environmentId: string | null; identity: CurrentIdentity; endpointUrl?: string;
}) {
  const base = clientId && installationId && environmentId ? `/api/clients/${clientId}/installations/${installationId}/environments/${environmentId}/connection` : null;
  const [connection, setConnection] = useState<Connection | null>(null);
  const [form, setForm] = useState({ ...empty, source_url: endpointUrl });
  const [credentials, setCredentials] = useState({ username: '', password: '' });
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [configure, setConfigure] = useState(false);
  const [rotate, setRotate] = useState(false);
  const pending = useRef(false);
  const membership = identity.clients.find((client) => client.id === clientId);
  const canConfigure = identity.capabilities.manage_clients || !!membership?.roles.includes('CLIENT_ADMIN');
  const canPing = canConfigure || !!membership?.permissions.test;
  useEffect(() => {
    if (!base) return;
    let active = true;
    const controller = new AbortController();
    void requestJson<Connection>(base, { signal: controller.signal }).then((data) => {
      if (!active) return;
      setConnection(data); setForm({ adapter: data.adapter || 'oracle_fusion_publisher', source_url: data.source_url, expected_tenant: data.expected_tenant, report_path: data.report_path, approved_hosts: data.approved_hosts.join(', '), permitted_operations: data.permitted_operations }); setLoaded(true);
    }).catch((cause: unknown) => {
      if (!active) return;
      if (!(cause instanceof APIError && cause.status === 404)) setError(cause instanceof Error ? cause.message : 'Connection could not be loaded.');
      setConnection(null); setLoaded(true);
    });
    return () => { active = false; controller.abort(); };
  }, [base, revision]);
  const mutate = async (path: string, method: string, body?: unknown) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await requestJson(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      setCredentials({ username: '', password: '' }); setConfigure(false); setRotate(false);
      setLoaded(false); setRevision((value) => value + 1); setNotice(path.endsWith('/ping') ? 'Connection check recorded. Review each capability result.' : 'Saved. Run a connection check to verify the current configuration.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Connection operation failed.'); }
    finally { pending.current = false; setBusy(false); }
  };
  const verification = connection?.last_verification;
  return <section className="workspace-card connection-card"><div className="section-title"><span className="section-icon"><Plug className="icon" /></span><div><h2>Sandbox connection</h2><p>Verify reachability, authentication and supported capabilities.</p></div></div>
    {error && <div role="alert" className="notice red">{error}</div>}{notice && <div role="status" className="notice blue">{notice}</div>}
    {!base ? <p>A client installation and execution environment are required.</p> : !loaded ? <p role="status">Loading connection configuration…</p> : <>
      <div className="connection-summary"><span className={`badge ${connection?.configured ? 'blue' : 'amber'}`}>{connection?.configured ? 'Credentials configured' : 'Credentials not configured'}</span>{connection && <small>Configuration v{connection.configuration_version}</small>}</div>
      <dl><dt>Source ERP endpoint</dt><dd>{connection?.source_url || 'Not configured'}</dd>{connection?.adapter !== 'metadata_only' && <><dt>Publisher report</dt><dd>{connection?.report_path || 'Not configured'}</dd><dt>Expected tenant</dt><dd>{connection?.expected_tenant || 'Not configured'}</dd></>}</dl>
      <div className="connection-actions">{canConfigure && <button className="btn secondary" disabled={busy} onClick={() => setConfigure((value) => !value)}>{connection ? 'Edit connection' : 'Configure connection'}</button>}{canConfigure && connection?.adapter !== 'metadata_only' && connection && <button className="btn secondary" disabled={busy} onClick={() => setRotate((value) => !value)}>{connection.configured ? 'Replace credentials' : 'Configure credentials'}</button>}{canPing && <button className="btn primary" disabled={!connection || connection.adapter === 'metadata_only' || !connection.configured || busy} onClick={() => { if (base) void mutate(`${base}/ping`, 'POST'); }}><ShieldCheck className="icon" />{busy ? 'Working…' : 'Ping / Check connection'}</button>}</div>
      {configure && canConfigure && <form className="connection-form" onSubmit={(event) => { event.preventDefault(); if (base) void mutate(base, 'PUT', { ...form, permitted_operations: form.adapter === 'metadata_only' ? [] : form.permitted_operations, approved_hosts: form.approved_hosts.split(',').map((host) => host.trim()).filter(Boolean) }); }}>
        <label>Connection adapter<select value={form.adapter} onChange={(event) => setForm({ ...form, adapter: event.target.value })}><option value="metadata_only">Metadata only · execution not implemented</option><option value="oracle_fusion_publisher">Oracle Fusion Publisher · existing report APIs</option></select></label><div className="notice slate">Only installed and qualified capabilities are executable. Metadata-only records do not connect to the ERP.</div>
        <label>Source ERP URL<input type="url" required value={form.source_url} onChange={(event) => setForm({ ...form, source_url: event.target.value })} placeholder="https://tenant.oraclecloud.com" /></label>
        {form.adapter === 'oracle_fusion_publisher' && <><label>Expected tenant<input required value={form.expected_tenant} onChange={(event) => setForm({ ...form, expected_tenant: event.target.value })} /></label>
        <label>Approved hostnames<input required value={form.approved_hosts} onChange={(event) => setForm({ ...form, approved_hosts: event.target.value })} placeholder="tenant.oraclecloud.com" /></label>
        <label>Publisher report path<input required value={form.report_path} onChange={(event) => setForm({ ...form, report_path: event.target.value })} placeholder="/Custom/Finance/report.xdo" /></label></>}
        <button className="btn primary" disabled={busy}>Save connection</button>
      </form>}
      {rotate && canConfigure && <form className="connection-form" onSubmit={(event) => { event.preventDefault(); if (base) void mutate(`${base}/credentials`, 'PUT', credentials); }}><p className="notice slate">Credentials are written to the configured secret store and cannot be read back here.</p><label>Integration username<input autoComplete="off" required value={credentials.username} onChange={(event) => setCredentials({ ...credentials, username: event.target.value })} /></label><label>Integration password<input type="password" autoComplete="new-password" required value={credentials.password} onChange={(event) => setCredentials({ ...credentials, password: event.target.value })} /></label><button className="btn primary" disabled={busy}>Save credentials</button></form>}
      {verification ? <div className="connection-evidence"><h3>Latest verification</h3><p className="input-note">{new Date(verification.checked_at).toLocaleString()} · {verification.latency_ms == null ? 'Latency unavailable' : `${verification.latency_ms} ms`} · {verification.current ? 'Current evidence' : 'Expired or invalidated evidence'}</p><div className="capability-grid">{[['network', 'Network / TLS'], ['authentication', 'Authentication'], ['tenant', 'Tenant identity'], ['permissions', 'Read permissions'], ['report_execution', 'Report execution'], ['import_capability', 'Import / deployment']].map(([key, title]) => <div key={key}><strong>{title}</strong><span className={`badge ${verification[key as keyof typeof verification] === 'VERIFIED' && verification.current ? 'green' : 'amber'}`}>{String(verification[key as keyof typeof verification])}</span></div>)}</div><p className="input-note">Diagnostic: {verification.diagnostic_code}. Evidence expires {new Date(verification.expires_at).toLocaleString()}.</p></div> : <div className="notice slate">No connection verification evidence recorded.</div>}
      <p className="input-note">Ping is a server check. It does not install packages or change ERP records. A verified network alone does not confirm tenant identity or grant deployment permission.</p>
    </>}
  </section>;
}
