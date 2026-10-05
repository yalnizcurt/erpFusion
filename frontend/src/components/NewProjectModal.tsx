import { useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { X, Plus, Sparkles } from 'lucide-react';
import type { CurrentIdentity, ERPEnvironment, ERPInstallation, IntegrationRequestCreate, PublishedERPProfile } from '../contracts/identity';
import { canCreateRequest } from '../contracts/identity';
import { useApiResource } from '../hooks/useApiResource';
import { useClientDirectory } from '../hooks/useClientDirectory';
import ClientDirectoryControls from './ClientDirectoryControls';

const inputStyle = { width: '100%', padding: '9px 12px', borderRadius: 6, background: '#fff', border: '1px solid #cbd5e1', color: '#1e293b', fontSize: 13 };
interface PatternVersion { id: string; version: number; profile_version_id: string; runtime_type: string; deliverable_type: string; implementation_status: string }
interface Pattern { id: string; name: string; versions: PatternVersion[] }

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return <div><label htmlFor={id} style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 6 }}>{label}</label>{children}</div>;
}

export default function NewProjectModal({ onClose, onCreateProject, erpProfiles = [], identity }: {
  onClose: () => void;
  onCreateProject: (body: IntegrationRequestCreate) => Promise<void>;
  erpProfiles?: PublishedERPProfile[];
  identity: CurrentIdentity;
}) {
  const clients = useClientDirectory();
  const [clientId, setClientId] = useState('');
  const [installationId, setInstallationId] = useState('');
  const [environmentId, setEnvironmentId] = useState('');
  const [profileVersionId, setProfileVersionId] = useState('');
  const [patternVersionId, setPatternVersionId] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [projectType, setProjectType] = useState<'STANDARD' | 'CUSTOM'>('CUSTOM');
  const [dueDate, setDueDate] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState('');
  const availableClients = clients.data?.filter((item) => canCreateRequest(identity, item.id)) ?? [];
  const client = availableClients.find((item) => item.id === clientId);
  const installations = useApiResource<ERPInstallation[]>(client ? `/api/clients/${client.id}/installations` : null);
  const availableInstallations = installations.data?.filter((item) => item.client_id === clientId && item.status === 'ACTIVE') ?? [];
  const installation = availableInstallations.find((item) => item.id === installationId);
  const environments = useApiResource<ERPEnvironment[]>(client && installation
    ? `/api/clients/${client.id}/installations/${installation.id}/environments` : null);
  const availableEnvironments = environments.data?.filter((item) => item.client_id === clientId && item.installation_id === installationId && item.status === 'ACTIVE') ?? [];
  const environment = availableEnvironments.find((item) => item.id === environmentId);
  const availableProfiles = erpProfiles.filter((item) => item.id === installation?.erp_profile_id && item.profile_version_id);
  const profile = availableProfiles.find((item) => item.profile_version_id === profileVersionId);
  const patterns = useApiResource<Pattern[]>(installation ? `/api/integration-patterns?erp_profile_id=${installation.erp_profile_id}` : null);
  const selectedPattern = patterns.data?.flatMap((pattern) => pattern.versions.map((version) => ({ ...version, name: pattern.name }))).find((version) => version.id === patternVersionId);
  const hasPatterns = !!patterns.data?.some((pattern) => pattern.versions.length);
  const selectedIntelligence = selectedPattern?.profile_version_id || profile?.profile_version_id;
  const loadError = clients.error || installations.error || environments.error || patterns.error;

  const selectClient = (id: string) => {
    setClientId(id); setInstallationId(''); setEnvironmentId(''); setProfileVersionId(''); setPatternVersionId(''); setError('');
  };
  const selectInstallation = (id: string) => {
    setInstallationId(id); setEnvironmentId(''); setProfileVersionId(''); setPatternVersionId(''); setError('');
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending.current) return;
    if (!client || !installation || !environment || !selectedIntelligence || patterns.loading || patterns.error || (hasPatterns && !selectedPattern)) {
      setError(hasPatterns ? 'Select an authorized client, its installation and environment, and a published integration pattern version.' : 'Select an authorized client, its installation and environment, and a matching published ERP profile.'); return;
    }
    if (!name.trim()) { setError('Provide a project name.'); return; }
    pending.current = true; setSubmitting(true); setError('');
    try {
      await onCreateProject({
        name: name.trim(), description: description.trim(), business_requirement: '',
        erp_schema_context: {}, project_type: projectType, due_date: dueDate || null, erp_profile_version_id: selectedIntelligence,
        ...(selectedPattern ? { integration_pattern_version_id: selectedPattern.id } : {}),
        client_id: client.id, erp_installation_id: installation.id, erp_environment_id: environment.id,
      });
      onClose();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Failed to create project.'); }
    finally { pending.current = false; setSubmitting(false); }
  };

  return <div role="dialog" aria-modal="true" aria-labelledby="new-project-title" style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,.45)', display: 'grid', placeItems: 'center', zIndex: 200, padding: 24 }}>
    <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0', boxShadow: '0 20px 25px rgba(0,0,0,.1)', width: 'min(750px,100%)', maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid #e2e8f0', background: '#f8fafc' }}><h3 id="new-project-title" style={{ fontSize: 15 }}><Sparkles size={18} color="#fc7500" /> Create New ERP Integration Project</h3><button aria-label="Close project form" disabled={submitting} onClick={onClose} style={{ background: 'none', border: 0, cursor: 'pointer' }}><X size={18} /></button></div>
      <form onSubmit={(event) => { void submit(event); }} style={{ padding: 20, overflowY: 'auto' }}>
        {(error || loadError) && <div role="alert" style={{ padding: 12, marginBottom: 16, background: '#fef2f2', color: '#991b1b', borderRadius: 6 }}>{error || loadError}</div>}
        <fieldset disabled={submitting} style={{ border: 0, display: 'grid', gap: 16, minWidth: 0 }}>
          <ClientDirectoryControls directory={clients} onChange={() => selectClient('')} disabled={submitting} />
          <Field id="request-client" label="Client *"><select id="request-client" value={clientId} onChange={(event) => selectClient(event.target.value)} disabled={clients.loading} required style={inputStyle}><option value="">{clients.loading ? 'Loading clients…' : 'Select a client'}</option>{availableClients.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></Field>
          {!clients.loading && !availableClients.length && <p style={{ color: '#64748b', fontSize: 12 }}>{clients.search || clients.offset ? 'No authorized clients match this page. Adjust the search or return to the previous page.' : 'You need a client membership with request creation permission. Ask a client administrator to grant access.'}</p>}
          <Field id="request-installation" label="ERP installation *"><select id="request-installation" value={installation?.id || ''} onChange={(event) => selectInstallation(event.target.value)} disabled={!client || installations.loading} required style={inputStyle}><option value="">{installations.loading ? 'Loading installations…' : 'Select this client’s ERP installation'}</option>{availableInstallations.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></Field>
          {client && !installations.loading && !availableInstallations.length && !installations.error && <p style={{ color: '#64748b', fontSize: 12 }}>Register an ERP installation for this client in Clients & ERP environments.</p>}
          <Field id="request-environment" label="Execution environment *"><select id="request-environment" value={environment?.id || ''} onChange={(event) => setEnvironmentId(event.target.value)} disabled={!installation || environments.loading} required style={inputStyle}><option value="">{environments.loading ? 'Loading environments…' : 'Select an execution environment'}</option>{availableEnvironments.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.environment_type}</option>)}</select></Field>
          {installation && !environments.loading && !availableEnvironments.length && !environments.error && <p style={{ color: '#64748b', fontSize: 12 }}>Register an environment for the selected installation before creating a request.</p>}
          {hasPatterns ? <><Field id="request-pattern" label="Integration pattern and version *"><select id="request-pattern" required disabled={patterns.loading} value={selectedPattern?.id || ''} onChange={(event) => setPatternVersionId(event.target.value)} style={inputStyle}><option value="">Select an approved integration pattern</option>{patterns.data?.flatMap((pattern) => pattern.versions.map((version) => <option key={version.id} value={version.id}>{pattern.name} · v{version.version} · {version.implementation_status}</option>))}</select></Field>{selectedPattern && <p className="notice slate">{selectedPattern.runtime_type} · {selectedPattern.deliverable_type}. ERP intelligence and baseline versions are pinned by this pattern. Runtime qualification is environment-specific.</p>}</> : <Field id="request-profile" label="ERP profile version *"><select id="request-profile" value={profile?.profile_version_id || ''} onChange={(event) => setProfileVersionId(event.target.value)} disabled={!installation} required style={inputStyle}><option value="">Select a matching published ERP profile</option>{availableProfiles.map((item) => <option key={item.profile_version_id} value={item.profile_version_id}>{item.display_name || item.name} · Profile v{item.profile_version}</option>)}</select></Field>}
          {installation && patterns.loading && <p role="status">Loading approved integration patterns…</p>}
          {installation && !patterns.loading && !hasPatterns && !availableProfiles.length && <p style={{ color: '#b45309', fontSize: 12 }}>This installation has no published ERP profile available. Ask an administrator to publish its configuration.</p>}
          <Field id="new-project-name" label="Project Name *"><input id="new-project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Supplier Invoice Integration" required maxLength={255} style={inputStyle} /></Field>
          <Field id="request-description" label="Description"><input id="request-description" value={description} onChange={(event) => setDescription(event.target.value)} style={inputStyle} /></Field>
          <Field id="request-type" label="Integration type"><select id="request-type" value={projectType} onChange={(event) => setProjectType(event.target.value as 'STANDARD' | 'CUSTOM')} style={inputStyle}><option value="CUSTOM">Custom</option><option value="STANDARD">Standard</option></select></Field>
          <Field id="request-due" label="Due date"><input id="request-due" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} style={inputStyle} /></Field>
          <p className="notice slate">Save a draft, then upload your consulting requirement document in Studio. {hasPatterns ? 'The selected pattern pins ERP intelligence and approved baseline versions.' : 'The ERP profile version is pinned to this project. Without a pattern, automatic qualification is unavailable.'}</p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}><button type="button" onClick={onClose} className="btn btn-secondary">Cancel</button><button type="submit" id="btn-submit-create-project" disabled={submitting || !client || !installation || !environment || !selectedIntelligence || patterns.loading || !!patterns.error || (hasPatterns && !selectedPattern)} className="btn btn-primary"><Plus size={15} />{submitting ? 'Creating…' : 'Create Project'}</button></div>
        </fieldset>
      </form>
    </div>
  </div>;
}
