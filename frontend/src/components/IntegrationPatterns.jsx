import { useRef, useState } from 'react';
import { requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';

const models = { ERP_NATIVE: 'NATIVE_ARTIFACT', API_INTEGRATION: 'REMOTE_API', FILE_BASED: 'FILE_EXCHANGE', EXTERNAL_RUNTIME: 'EXTERNAL_RUNTIME', ASSISTED: 'ASSISTED' };
const initialContract = { generation_rules: { strategy: 'baseline_json', strategy_version: '1', stages: [], baseline_required: true, allowed_files: [], allowed_modifications: [] }, adapter_bindings: {}, required_capabilities: [], optional_capabilities: [], supported_environments: ['ERPFUSION_SANDBOX', 'CUSTOMER_TEST', 'CUSTOMER_UAT'], qualification_policy: { allowed_modes: ['ASSISTED'], required_assurance: ['ASSISTED_MANUAL'] }, testing: { version: '', required_cases: [] }, compatibility: {} };
const initialForm = (profile) => ({ profile_version_id: profile.versions.find((v) => v.status === 'PUBLISHED')?.id || '', runtime_type: 'ASSISTED', direction: 'OUTBOUND', deliverable_type: 'SOURCE_BUNDLE', qualification_strategy: 'ASSISTED', delivery_method: 'CUSTOMER_CONTROLLED', baseline_asset_version_ids: [] });

export default function IntegrationPatterns({ profile, canEdit, canPublish, onRegistryChanged }) {
  const registry = useApiResource(`/api/integration-patterns?erp_profile_id=${profile.id}&include_drafts=true`);
  const [patternId, setPatternId] = useState('');
  const [editing, setEditing] = useState(null);
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('ALL');
  const [form, setForm] = useState(() => initialForm(profile));
  const [contract, setContract] = useState(JSON.stringify(initialContract, null, 2));
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const assets = useApiResource(`/api/integration-patterns/baseline-assets?erp_profile_id=${profile.id}`);
  const update = (field, value) => setForm((previous) => ({ ...previous, [field]: value }));
  const mutate = async (path, body, message, method = 'POST') => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const result = await requestJson(`/api/integration-patterns${path}`, { method, body: JSON.stringify(body) });
      registry.reload(); onRegistryChanged?.(); setNotice(message);
      if (editing?.id === result.id) setEditing(result);
      return result;
    } catch (cause) { setError(cause.message); }
    finally { pending.current = false; setBusy(false); }
  };
  const open = (pattern, version, clone = false) => {
    setPatternId(pattern.id); setKey(pattern.key); setName(pattern.name); setEditing(clone ? null : version);
    setForm(Object.fromEntries(Object.keys(form).map((field) => [field, version[field]])));
    setContract(JSON.stringify(version.configuration, null, 2)); setError(''); setNotice('');
  };
  const save = async (event) => {
    event.preventDefault();
    let configuration;
    try { configuration = JSON.parse(contract); } catch { setError('Pattern contract must be valid JSON.'); return; }
    let identifier = patternId;
    if (!identifier) {
      const result = await mutate('', { erp_profile_id: profile.id, key, name }, 'Pattern created.');
      if (!result) return;
      identifier = result.id; setPatternId(identifier);
    }
    const result = await mutate(`/${identifier}/versions${editing ? `/${editing.id}` : ''}`, { ...form, configuration }, 'Draft pattern version saved. Publish only after reviewing its baseline and qualification policy.', editing ? 'PUT' : 'POST');
    if (result) setEditing(result);
  };
  const immutable = editing && !['DRAFT', 'REVIEW'].includes(editing.status);
  return <div className="pattern-studio">
    <h3>HighRadius integration patterns</h3>
    <p>A product catalogue entry grants no runtime support. Patterns pin intelligence and baseline versions; installed adapters and environment qualification determine executable capabilities.</p>
    {(error || registry.error || assets.error) && <div className="notice red" role="alert">{error || registry.error || assets.error}</div>}
    {notice && <div className="notice blue" role="status">{notice}</div>}
    <div className="workspace-bottom"><input aria-label="Search integration patterns" placeholder="Search patterns" value={search} onChange={(e) => setSearch(e.target.value)} /><select aria-label="Pattern status" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="ALL">All statuses</option>{['DRAFT', 'REVIEW', 'PUBLISHED', 'RETIRED'].map((status) => <option key={status}>{status}</option>)}</select><button className="btn secondary" disabled={!canEdit || busy} onClick={() => { setPatternId(''); setEditing(null); setKey(''); setName(''); setForm(initialForm(profile)); setContract(JSON.stringify(initialContract, null, 2)); setError(''); setNotice(''); }}>Add integration pattern</button></div>
    {(registry.data || []).filter((p) => `${p.name} ${p.key}`.toLowerCase().includes(search.toLowerCase())).map((pattern) => <article className="package-manifest" key={pattern.id}><h4>{pattern.name} · {pattern.provider}</h4>{pattern.versions.filter((v) => filter === 'ALL' || v.status === filter).map((version) => <div className="history-row" key={version.id}><span>v{version.version} · {version.status}<br />{version.runtime_type} · {version.deliverable_type}<br />{version.implementation_status} · qualification is environment-specific</span><div><button className="btn secondary" onClick={() => open(pattern, version)}>Open</button><button className="btn secondary" disabled={!canEdit || busy} onClick={() => open(pattern, version, true)}>New version from this</button>{['DRAFT', 'REVIEW'].includes(version.status) && <button className="btn primary" disabled={!canPublish || busy} onClick={() => { void mutate(`/${pattern.id}/versions/${version.id}/publish`, {}, 'Pattern version published. Existing projects keep their pinned versions.'); }}>Publish</button>}{version.status === 'PUBLISHED' && <button className="btn secondary" disabled={!canPublish || busy} onClick={() => { void mutate(`/${pattern.id}/versions/${version.id}/retire`, {}, 'Retired for new selection; pinned history remains.'); }}>Retire</button>}</div></div>)}</article>)}
    <form onSubmit={save} className="workspace-card">
      <h4>{editing ? `Pattern v${editing.version} · ${editing.status}` : patternId ? 'New pattern version' : 'New integration pattern'}</h4>
      {immutable && <p className="notice amber">Published contracts are immutable. Choose “New version from this” to make changes.</p>}
      <fieldset disabled={!canEdit || busy || immutable} style={{ border: 0, minWidth: 0, display: 'grid', gap: 12 }}>
        {!patternId && <><label className="field-label">Pattern key<input required value={key} pattern="[a-z0-9][a-z0-9._-]*" maxLength="80" onChange={(e) => setKey(e.target.value)} /></label><label className="field-label">Pattern name<input required value={name} maxLength="255" onChange={(e) => setName(e.target.value)} /></label></>}
        <label className="field-label">Pinned ERP intelligence version<select required value={form.profile_version_id} onChange={(e) => { update('profile_version_id', e.target.value); update('baseline_asset_version_ids', []); }}><option value="">Select published intelligence</option>{profile.versions.filter((v) => v.status === 'PUBLISHED' || v.id === form.profile_version_id).map((v) => <option key={v.id} value={v.id}>Profile v{v.version} · {v.status}</option>)}</select></label>
        <label className="field-label">Runtime model<select value={form.runtime_type} onChange={(e) => setForm({ ...form, runtime_type: e.target.value, qualification_strategy: models[e.target.value] })}>{Object.keys(models).map((model) => <option key={model}>{model}</option>)}</select></label>
        <label className="field-label">Direction<select value={form.direction} onChange={(e) => update('direction', e.target.value)}>{['OUTBOUND', 'INBOUND', 'BIDIRECTIONAL'].map((direction) => <option key={direction}>{direction}</option>)}</select></label>
        <label className="field-label">Deliverable type<input required value={form.deliverable_type} onChange={(e) => update('deliverable_type', e.target.value)} /></label>
        <label className="field-label">Qualification strategy<select value={form.qualification_strategy} onChange={(e) => update('qualification_strategy', e.target.value)}>{Object.values(models).map((strategy) => <option key={strategy}>{strategy}</option>)}</select></label>
        <label className="field-label">Delivery method<input required value={form.delivery_method} onChange={(e) => update('delivery_method', e.target.value)} /></label>
        <label className="field-label">Approved baseline asset versions<select multiple value={form.baseline_asset_version_ids} onChange={(e) => update('baseline_asset_version_ids', Array.from(e.target.selectedOptions, (option) => option.value))}>{assets.data?.filter((a) => a.asset_kind === 'PACKAGE' && a.status === 'PUBLISHED').map((a) => <option key={a.id} value={a.id}>{a.name} · v{a.version} · {a.id}</option>)}</select></label>
        <p>Use published Standard Package assets containing named UTF-8 source files: <code>{'{"files":[{"name":"mapping.json","content":"..."}]}'}</code>. Native archives need an implemented build adapter; this text contract does not make them importable.</p>
        <label className="field-label">Pattern contract (generation rules, capabilities, test plan, assurance)<textarea className="provenance-json" rows="18" required value={contract} onChange={(e) => setContract(e.target.value)} /></label>
        <button className="btn primary" type="submit">Save draft pattern version</button>
      </fieldset>
    </form>
  </div>;
}
