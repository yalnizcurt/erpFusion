import { cloneElement, useId, useRef, useState } from 'react';
import type { FormEvent, ReactElement, ReactNode } from 'react';
import { Building2, CheckCircle2, Database, Plus, Server, ShieldAlert } from 'lucide-react';
import { requestJson } from '../api';
import type { Client, CurrentIdentity, ERPEnvironment, ERPInstallation, PublishedERPProfile } from '../contracts/identity';
import { canManageEnvironment } from '../contracts/identity';
import { useApiResource } from '../hooks/useApiResource';
import { useClientDirectory } from '../hooks/useClientDirectory';
import ClientDirectoryControls from './ClientDirectoryControls';
import ClientMemberships from './ClientMemberships';
import ConnectionSettings from './ConnectionSettings';

const emptyClient = { client_key: '', display_name: '', legal_name: '', description: '' };
const emptyInstallation = {
  installation_key: '', display_name: '', erp_profile_id: '', edition: '', product_version: '', external_tenant_reference: '', configuration: {},
};
const emptyEnvironment = { environment_key: '', display_name: '', environment_type: 'SANDBOX', custody: 'UNVERIFIED', execution_mode: 'ASSISTED', endpoint_url: '', configuration: {} };
const inputStyle = { width: '100%', padding: '9px 10px', border: '1px solid #cbd5e1', borderRadius: 6, font: 'inherit', color: '#0f172a', background: '#fff' };
const cardStyle = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 9, padding: 18, minWidth: 0 };

function Field({ label, children, hint }: { label: string; children: ReactElement<{ id?: string }>; hint?: string }) {
  const id = useId();
  return <div style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569', fontWeight: 600 }}>
    <label htmlFor={id}>{label}</label>{cloneElement(children, { id })}{hint && <small style={{ color: '#64748b', fontWeight: 400 }}>{hint}</small>}
  </div>;
}

function TextInput({ id, value, onChange, placeholder, required = false }: {
  id?: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean;
}) {
  return <input id={id} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} required={required} style={inputStyle} />;
}

export default function ClientWorkspace({ erpProfiles = [], identity }: {
  erpProfiles?: PublishedERPProfile[]; identity: CurrentIdentity;
}) {
  const clients = useClientDirectory();
  const [selectedClientId, setSelectedClientId] = useState('');
  const installations = useApiResource<ERPInstallation[]>(selectedClientId ? `/api/clients/${selectedClientId}/installations` : null);
  const [selectedInstallationId, setSelectedInstallationId] = useState('');
  const [connectionEnvironmentId, setConnectionEnvironmentId] = useState('');
  const selectedClient = clients.data?.find((item) => item.id === selectedClientId);
  const ownedInstallations = installations.data?.filter((item) => item.client_id === selectedClientId) ?? [];
  const selectedInstallation = ownedInstallations.find((item) => item.id === selectedInstallationId);
  const environments = useApiResource<ERPEnvironment[]>(selectedClient && selectedInstallation
    ? `/api/clients/${selectedClient.id}/installations/${selectedInstallation.id}/environments` : null);
  const ownedEnvironments = environments.data?.filter((item) => item.client_id === selectedClientId && item.installation_id === selectedInstallationId) ?? [];
  const [clientForm, setClientForm] = useState(emptyClient);
  const [installationForm, setInstallationForm] = useState(emptyInstallation);
  const [environmentForm, setEnvironmentForm] = useState(emptyEnvironment);
  const [dialog, setDialog] = useState<'client' | 'installation' | 'environment' | null>(null);
  const [busy, setBusy] = useState(false);
  const submissionPending = useRef(false);
  const [notice, setNotice] = useState('');
  const [mutationError, setMutationError] = useState('');
  const error = mutationError || clients.error || installations.error || environments.error;
  const manageEnvironment = selectedClient ? canManageEnvironment(identity, selectedClient.id) : false;
  const publishedProfiles = erpProfiles.filter((profile) => profile.profile_version_id);

  const selectClient = (id: string) => {
    if (submissionPending.current) return;
    setConnectionEnvironmentId('');
    setSelectedClientId(id);
    setSelectedInstallationId('');
    setDialog(null);
    setInstallationForm(emptyInstallation);
    setEnvironmentForm(emptyEnvironment);
    setNotice('');
    setMutationError('');
  };
  const selectInstallation = (id: string) => {
    if (submissionPending.current) return;
    setConnectionEnvironmentId('');
    setSelectedInstallationId(id);
    setDialog(null);
    setEnvironmentForm(emptyEnvironment);
    setNotice('');
    setMutationError('');
  };
  const submit = async <T,>(event: FormEvent, path: string, body: unknown, after: (data: T) => void) => {
    event.preventDefault();
    if (submissionPending.current) return;
    submissionPending.current = true;
    setBusy(true); setMutationError(''); setNotice('');
    try {
      const data = await requestJson<T>(path, { method: 'POST', body: JSON.stringify(body) });
      after(data); setDialog(null); setNotice('Saved successfully.');
    } catch (cause) { setMutationError(cause instanceof Error ? cause.message : 'Unable to save.'); }
    finally { submissionPending.current = false; setBusy(false); }
  };
  const createClient = (event: FormEvent) => {
    if (!identity.capabilities.manage_clients) { event.preventDefault(); return; }
    void submit<Client>(event, '/api/clients', clientForm, (client) => {
      clients.changeSearch(client.display_name); clients.reload(); setClientForm(emptyClient);
      setSelectedClientId(client.id); setSelectedInstallationId('');
    });
  };
  const createInstallation = (event: FormEvent) => {
    if (!selectedClient || !manageEnvironment || !publishedProfiles.some((profile) => profile.id === installationForm.erp_profile_id)) {
      event.preventDefault(); setMutationError('Select an authorized client and a published ERP profile.'); return;
    }
    void submit<ERPInstallation>(event, `/api/clients/${selectedClient.id}/installations`, installationForm, (installation) => {
      installations.reload(); setSelectedInstallationId(installation.id); setInstallationForm(emptyInstallation);
    });
  };
  const createEnvironment = (event: FormEvent) => {
    if (!selectedClient || !selectedInstallation || !manageEnvironment) { event.preventDefault(); return; }
    void submit<ERPEnvironment>(event, `/api/clients/${selectedClient.id}/installations/${selectedInstallation.id}/environments`, environmentForm, () => {
      environments.reload(); setEnvironmentForm(emptyEnvironment);
    });
  };

  return <section style={{ padding: 24, display: 'grid', gap: 18 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
      <div><h1 style={{ margin: '5px 0', fontSize: 23 }}>Clients & ERP environments</h1><p style={{ color: '#64748b', fontSize: 13 }}>Manage the client, ERP installation, and environment used by each integration request.</p></div>
      {identity.capabilities.manage_clients && <button className="btn btn-primary" onClick={() => { setDialog('client'); setMutationError(''); }}><Plus size={15} /> Add client</button>}
    </div>
    {error && <div role="alert" style={{ padding: 12, color: '#991b1b', background: '#fef2f2', borderRadius: 7 }}><ShieldAlert size={17} /> {error}</div>}
    {notice && <div role="status" style={{ padding: 12, color: '#166534', background: '#f0fdf4', borderRadius: 7 }}><CheckCircle2 size={17} /> {notice}</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(200px, .8fr) minmax(0, 2fr)', gap: 18, alignItems: 'start' }}>
      <div style={cardStyle}><h2 style={{ fontSize: 16 }}>Client directory</h2>
        <ClientDirectoryControls directory={clients} onChange={() => selectClient('')} disabled={busy} />
        {clients.loading && <p role="status">Loading clients…</p>}
        {!clients.loading && !clients.data?.length && !clients.error && <p>{clients.search || clients.offset ? 'No clients match this page.' : 'No clients are visible for this identity.'}</p>}
        {clients.data?.map((client) => <button key={client.id} disabled={busy} aria-pressed={selectedClientId === client.id} onClick={() => selectClient(client.id)} style={{ width: '100%', textAlign: 'left', border: 0, padding: 14, background: selectedClientId === client.id ? '#eff6ff' : '#fff', cursor: 'pointer' }}><strong style={{ display: 'block' }}>{client.display_name}</strong><small>{client.client_key}</small></button>)}
      </div>
      <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
        {!selectedClient && <div style={cardStyle}>Select a client to manage its ERP installations.</div>}
        {selectedClient && <>
          <div style={cardStyle}><Building2 size={20} color="#0284c7" /><h2 style={{ fontSize: 17 }}>{selectedClient.display_name}</h2><small>{selectedClient.client_key} · {selectedClient.status}</small></div>
          {manageEnvironment && <ClientMemberships key={selectedClient.id} clientId={selectedClient.id} />}
          <div style={cardStyle}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2 style={{ fontSize: 16 }}>ERP installations</h2>{manageEnvironment && <button className="btn btn-secondary" disabled={busy} onClick={() => { setInstallationForm(emptyInstallation); setDialog('installation'); setMutationError(''); }}><Plus size={14} /> Add installation</button>}</div>
            {installations.loading && <p role="status">Loading installations…</p>}
            {!installations.loading && !ownedInstallations.length && !installations.error && <p>No ERP installation is registered for this client.</p>}
            {ownedInstallations.map((installation) => <button key={installation.id} disabled={busy} aria-pressed={selectedInstallationId === installation.id} onClick={() => selectInstallation(installation.id)} style={{ display: 'flex', gap: 10, width: '100%', textAlign: 'left', padding: 12, marginTop: 8, border: '1px solid #e2e8f0', borderRadius: 7, background: selectedInstallationId === installation.id ? '#f0f9ff' : '#fff', cursor: 'pointer' }}><Database size={17} color="#0284c7" /><span><strong style={{ display: 'block' }}>{installation.display_name}</strong><small>{installation.edition || 'ERP'} · {installation.product_version || 'Version not set'}</small></span></button>)}
          </div>
          {selectedInstallation && <div style={cardStyle}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2 style={{ fontSize: 16 }}>Execution environments</h2>{manageEnvironment && <button className="btn btn-secondary" disabled={busy} onClick={() => { setEnvironmentForm(emptyEnvironment); setDialog('environment'); setMutationError(''); }}><Plus size={14} /> Add environment</button>}</div>
            {environments.loading && <p role="status">Loading environments…</p>}
            {!environments.loading && !ownedEnvironments.length && !environments.error && <p>Add a sandbox or UAT environment before testing a generated package.</p>}
            {ownedEnvironments.map((environment) => <div key={environment.id} style={{ display: 'flex', gap: 10, padding: 12, marginTop: 8, background: '#f8fafc', borderRadius: 7, overflowWrap: 'anywhere' }}><Server size={17} /><span><strong style={{ display: 'block' }}>{environment.display_name}</strong><small>{environment.environment_type} · {environment.endpoint_url || 'Endpoint not configured'}</small></span><button className="btn secondary" style={{ marginLeft: 'auto' }} onClick={() => setConnectionEnvironmentId(environment.id)}>Connection</button></div>)}
          </div>}
          {selectedInstallation && connectionEnvironmentId && ownedEnvironments.some((environment) => environment.id === connectionEnvironmentId) && <ConnectionSettings key={connectionEnvironmentId} clientId={selectedClient.id} installationId={selectedInstallation.id} environmentId={connectionEnvironmentId} identity={identity} endpointUrl={ownedEnvironments.find((environment) => environment.id === connectionEnvironmentId)?.endpoint_url || ''} />}
        </>}
      </div>
    </div>
    {dialog === 'client' && identity.capabilities.manage_clients && <FormDialog title="Add client" onClose={() => setDialog(null)} onSubmit={createClient} busy={busy} error={mutationError}>
      <Field label="Client key"><TextInput value={clientForm.client_key} onChange={(value) => setClientForm({ ...clientForm, client_key: value })} placeholder="acme-corp" required /></Field>
      <Field label="Display name"><TextInput value={clientForm.display_name} onChange={(value) => setClientForm({ ...clientForm, display_name: value })} placeholder="Acme Corporation" required /></Field>
      <Field label="Legal name"><TextInput value={clientForm.legal_name} onChange={(value) => setClientForm({ ...clientForm, legal_name: value })} placeholder="Optional legal entity name" /></Field>
    </FormDialog>}
    {dialog === 'installation' && selectedClient && manageEnvironment && <FormDialog title={`Add ERP installation · ${selectedClient.display_name}`} onClose={() => setDialog(null)} onSubmit={createInstallation} busy={busy} error={mutationError}>
      <Field label="ERP profile"><select value={installationForm.erp_profile_id} onChange={(event) => setInstallationForm({ ...installationForm, erp_profile_id: event.target.value })} required style={inputStyle}><option value="">Select a published ERP profile</option>{publishedProfiles.map((profile) => <option key={profile.profile_version_id} value={profile.id}>{profile.display_name || profile.name} · v{profile.profile_version}</option>)}</select></Field>
      <Field label="Installation key"><TextInput value={installationForm.installation_key} onChange={(value) => setInstallationForm({ ...installationForm, installation_key: value })} placeholder="primary-finance" required /></Field>
      <Field label="Display name"><TextInput value={installationForm.display_name} onChange={(value) => setInstallationForm({ ...installationForm, display_name: value })} placeholder="Finance ERP tenant" required /></Field>
      <Field label="Edition"><TextInput value={installationForm.edition} onChange={(value) => setInstallationForm({ ...installationForm, edition: value })} placeholder="Cloud / Private / On-premises" /></Field>
      <Field label="Product version"><TextInput value={installationForm.product_version} onChange={(value) => setInstallationForm({ ...installationForm, product_version: value })} placeholder="2026 R1" /></Field>
      <Field label="Tenant reference"><TextInput value={installationForm.external_tenant_reference} onChange={(value) => setInstallationForm({ ...installationForm, external_tenant_reference: value })} placeholder="Customer-controlled tenant identifier" /></Field>
    </FormDialog>}
    {dialog === 'environment' && selectedClient && selectedInstallation && manageEnvironment && <FormDialog title={`Add environment · ${selectedInstallation.display_name}`} onClose={() => setDialog(null)} onSubmit={createEnvironment} busy={busy} error={mutationError}>
      <Field label="Environment key"><TextInput value={environmentForm.environment_key} onChange={(value) => setEnvironmentForm({ ...environmentForm, environment_key: value })} placeholder="sandbox" required /></Field>
      <Field label="Display name"><TextInput value={environmentForm.display_name} onChange={(value) => setEnvironmentForm({ ...environmentForm, display_name: value })} placeholder="Integration sandbox" required /></Field>
      <Field label="Environment type"><select value={environmentForm.environment_type} onChange={(event) => setEnvironmentForm({ ...environmentForm, environment_type: event.target.value })} style={inputStyle}>{['DEVELOPMENT', 'SANDBOX', 'TEST', 'UAT', 'PRODUCTION'].map((type) => <option key={type}>{type}</option>)}</select></Field>
      <Field label="Environment custody"><select value={environmentForm.custody} onChange={(event) => setEnvironmentForm({ ...environmentForm, custody: event.target.value })} style={inputStyle}><option value="UNVERIFIED">Unverified · execution blocked</option><option value="CUSTOMER">Customer</option>{identity.capabilities.manage_clients && <option value="ERPFUSION_MANAGED">HighStudio managed</option>}</select></Field>
      <Field label="Execution mode"><select value={environmentForm.execution_mode} onChange={(event) => setEnvironmentForm({ ...environmentForm, execution_mode: event.target.value })} style={inputStyle}><option value="ASSISTED">Assisted manual</option><option value="SIMULATED">Simulator · development only</option><option value="REMOTE">Remote API · qualification required</option></select></Field>
      <Field label="Endpoint URL" hint="Credentials belong in the connection workflow."><TextInput value={environmentForm.endpoint_url} onChange={(value) => setEnvironmentForm({ ...environmentForm, endpoint_url: value })} placeholder="https://erp.example.test" /></Field>
    </FormDialog>}
  </section>;
}

function FormDialog({ title, onClose, onSubmit, children, busy, error }: {
  title: string; onClose: () => void; onSubmit: (event: FormEvent) => void; children: ReactNode; busy: boolean; error: string;
}) {
  return <div role="dialog" aria-modal="true" aria-label={title} style={{ position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(15,23,42,.4)', display: 'grid', placeItems: 'center', padding: 20 }}><form onSubmit={onSubmit} style={{ width: 'min(520px,100%)', maxHeight: '90vh', overflowY: 'auto', display: 'grid', gap: 15, padding: 22, background: '#fff', borderRadius: 10 }}><h2 style={{ fontSize: 18 }}>{title}</h2>{error && <p role="alert" style={{ color: '#991b1b' }}>{error}</p>}{children}<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><button type="button" disabled={busy} onClick={onClose} className="btn btn-secondary">Cancel</button><button type="submit" disabled={busy} className="btn btn-primary">{busy ? 'Saving…' : 'Save'}</button></div></form></div>;
}
