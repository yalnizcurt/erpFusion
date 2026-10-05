import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Boxes, Plus, ShieldCheck, Upload, X } from 'lucide-react';
import { apiFetch } from '../api';
import IntegrationPatterns from './IntegrationPatterns';

const TABS = [
  ['Overview', 'Overview'], ['Prompts', 'Prompts'], ['Standard Packages', 'PACKAGE'],
  ['Integration Patterns', 'Patterns'],
  ['Knowledge', 'KNOWLEDGE'], ['Validation Rules', 'Validation'], ['Generation Strategy', 'Strategy'],
  ['Versions', 'Versions'], ['Feedback', 'Feedback'], ['Usage', 'Usage'], ['Audit', 'Audit'], ['Global Prompts', 'Global'],
];

const defaultStages = `CONTEXT_ANALYSIS\nFDD\nTDD\nSQL\nCODE_GENERATION\nRELEASE`;

function makeConfiguration(stagesText) {
  const stages = stagesText.split('\n').map((value) => value.trim().toUpperCase()).filter(Boolean);
  return {
    workflow: { stages: stages.map((type, index) => ({
      type, depends_on: index ? [stages[index - 1]] : [], adapter: 'generic_json', prompt_stage: type,
      label: type.replaceAll('_', ' '), task: `Produce the ${type.replaceAll('_', ' ').toLowerCase()} artifact as structured JSON.`,
    })) },
    generation: { strategy: 'configured_adapters' },
    validation: { schema_conformity: false, rules: [] },
  };
}

export default function ERPAdmin({ onBack, identity, onRegistryChanged }) {
  const canEdit = identity?.capabilities.configure_erp === true;
  const canPublish = identity?.capabilities.publish_erp === true;
  const detailSequence = useRef(0);
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [version, setVersion] = useState(null);
  const [tab, setTab] = useState('Overview');
  const [prompts, setPrompts] = useState([]);
  const [assets, setAssets] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [feedbackQueue, setFeedbackQueue] = useState([]);
  const [audit, setAudit] = useState([]);
  const [usage, setUsage] = useState(null);
  const [globalPrompts, setGlobalPrompts] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [profileSearch, setProfileSearch] = useState('');
  const [profileStatus, setProfileStatus] = useState('ALL');
  const [profileForm, setProfileForm] = useState({ name: '', vendor: '', version: '', description: '', stages: defaultStages });
  const [configText, setConfigText] = useState('');
  const [promptForm, setPromptForm] = useState({ name: '', scope: 'STAGE', stage: '', content: '' });
  const [assetForm, setAssetForm] = useState({ name: '', description: '', package_type: '', text_content: '' });
  const [globalForm, setGlobalForm] = useState({ name: '', stage: '*', content: '' });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const api = useCallback(async (url, options = {}) => {
    const mutation = options.method && options.method.toUpperCase() !== 'GET';
    const publication = /\/(publish|retire|promote)(?:\?|$)/.test(url);
    if (mutation && !(publication ? canPublish : canEdit)) throw new Error('Your identity does not permit this administrative action.');
    const headers = { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers };
    const response = await apiFetch(url, { ...options, headers });
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
    if (mutation) onRegistryChanged?.();
    return data;
  }, [canEdit, canPublish, onRegistryChanged]);

  const loadProfiles = useCallback(async () => {
    if (!canEdit && !canPublish) return;
    try {
      const list = await api('/api/erp-profiles/admin');
      setProfiles(list);
      setSelected((current) => current ? (list.find((item) => item.id === current.id) || current) : current);
      setError('');
    } catch (e) { setError(e.message); }
  }, [canEdit, canPublish, api]);

  const loadDetail = async (profile, selectedVersion = null) => {
    if (!profile) return;
    const sequence = ++detailSequence.current;
    setSelected(profile);
    const versions = profile.versions || [];
    const activeVersion = selectedVersion || versions.find((x) => x.status === 'DRAFT' || x.status === 'REVIEW') || versions[0];
    setVersion(activeVersion || null);
    setPrompts([]); setAssets([]); setFeedback([]); setAudit([]); setUsage(null); setConfigText('');
    if (!activeVersion) return;
    try {
      const [promptList, assetList, feedbackList, auditList, usageSummary] = await Promise.all([
        api(`/api/erp-profiles/${profile.id}/prompts?version=${activeVersion.version}`),
        api(`/api/erp-profiles/${profile.id}/versions/${activeVersion.version}/assets`),
        api(`/api/erp-profiles/${profile.id}/versions/${activeVersion.version}/feedback`),
        api(`/api/erp-profiles/${profile.id}/versions/${activeVersion.version}/audit`),
        api(`/api/erp-profiles/${profile.id}/usage`),
      ]);
      if (sequence !== detailSequence.current) return;
      setPrompts(promptList); setAssets(assetList); setFeedback(feedbackList); setAudit(auditList);
      setUsage(usageSummary);
      setConfigText(JSON.stringify(activeVersion.configuration || {}, null, 2));
      setPromptForm((current) => ({ ...current, stage: current.stage || activeVersion.supported_artifact_types?.[0] || '' }));
    } catch (e) { if (sequence === detailSequence.current) setError(e.message); }
  };

  useEffect(() => { loadProfiles(); }, [loadProfiles]);
  useEffect(() => {
    if (selected && version) loadDetail(selected, version);
  // selection/version changes load the profile's attached registries
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version?.id]);

  const showNotice = (message) => { setNotice(message); setError(''); window.setTimeout(() => setNotice(''), 4000); };

  const createProfile = async (event) => {
    event.preventDefault(); setBusy(true);
    try {
      const configuration = makeConfiguration(profileForm.stages);
      const created = await api('/api/erp-profiles', { method: 'POST', body: JSON.stringify({
        name: profileForm.name, display_name: profileForm.name, vendor: profileForm.vendor,
        version: profileForm.version, description: profileForm.description,
        supported_artifact_types: configuration.workflow.stages.map((x) => x.type), configuration,
      }) });
      await loadProfiles();
      const list = await api('/api/erp-profiles/admin');
      setProfiles(list);
      const profile = list.find((x) => x.id === created.id);
      setShowCreate(false); setTab('Overview');
      await loadDetail(profile, profile.versions?.[0]);
      showNotice('Draft ERP profile created. Configure and publish prompts before publishing this profile.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const saveConfiguration = async () => {
    try {
      const configuration = JSON.parse(configText);
      const updated = await api(`/api/erp-profiles/${selected.id}/versions/${version.version}`, {
        method: 'PUT', body: JSON.stringify({ configuration, supported_artifact_types: (configuration.workflow?.stages || []).map((item) => item.type).filter(Boolean) }),
      });
      await loadProfiles();
      await loadDetail(selected, { ...version, ...updated });
      showNotice('Profile configuration saved.');
    } catch (e) { setError(e instanceof SyntaxError ? 'Configuration must be valid JSON.' : e.message); }
  };

  const addPrompt = async (event) => {
    event.preventDefault();
    try {
      const prompt = await api(`/api/erp-profiles/${selected.id}/versions/${version.version}/prompts`, {
        method: 'POST', body: JSON.stringify(promptForm),
      });
      setPrompts((items) => [prompt, ...items]);
      setPromptForm((x) => ({ ...x, name: '', content: '' }));
      showNotice('Draft prompt created. Publish it before generating artifacts.');
    } catch (e) { setError(e.message); }
  };

  const publishPrompt = async (item) => {
    try {
      await api(`/api/erp-profiles/${selected.id}/prompts/${item.id}/publish`, { method: 'POST' });
      await loadDetail(selected, version); showNotice(`Published ${item.name} v${item.version}.`);
    } catch (e) { setError(e.message); }
  };

  const retirePrompt = async (item) => {
    try {
      await api(`/api/erp-profiles/${selected.id}/prompts/${item.id}/retire`, { method: 'POST' });
      await loadDetail(selected, version); showNotice(`Retired ${item.name} v${item.version} from this draft profile version.`);
    } catch (e) { setError(e.message); }
  };

  const addTextAsset = async (event, kind) => {
    event.preventDefault();
    try {
      const result = await api(`/api/erp-profiles/${selected.id}/versions/${version.version}/assets`, {
        method: 'POST', body: JSON.stringify({ ...assetForm, asset_kind: kind }),
      });
      setAssets((items) => [result, ...items]);
      setAssetForm({ name: '', description: '', package_type: '', text_content: '' });
      showNotice(`${kind === 'PACKAGE' ? 'Package' : 'Knowledge asset'} draft added.`);
    } catch (e) { setError(e.message); }
  };

  const uploadAsset = async (event, kind) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const list = await api(`/api/erp-profiles/${selected.id}/versions/${version.version}/assets/upload?${new URLSearchParams({ asset_kind: kind, name: data.get('name'), package_type: data.get('package_type') || '', description: data.get('description') || '' })}`, { method: 'POST', body: data });
      setAssets((items) => [...list, ...items]); form.reset(); showNotice('Files uploaded as draft asset versions.');
    } catch (e) { setError(e.message); }
  };

  const publishAsset = async (asset) => {
    try {
      await api(`/api/erp-profiles/${selected.id}/assets/${asset.asset_id}/versions/${asset.version}/publish`, { method: 'POST' });
      await loadDetail(selected, version); showNotice(`${asset.name} v${asset.version} published.`);
    } catch (e) { setError(e.message); }
  };

  const retireAsset = async (asset) => {
    try {
      await api(`/api/erp-profiles/${selected.id}/assets/${asset.asset_id}/versions/${asset.version}/retire`, { method: 'POST' });
      await loadDetail(selected, version); showNotice(`Retired ${asset.name} v${asset.version} from this draft profile version.`);
    } catch (e) { setError(e.message); }
  };

  const newVersion = async () => {
    setBusy(true); setTab('Overview');
    try {
      const created = await api(`/api/erp-profiles/${selected.id}/versions`, { method: 'POST' });
      const list = await api('/api/erp-profiles/admin'); setProfiles(list);
      const profile = list.find((x) => x.id === selected.id); setSelected(profile);
      await loadDetail(profile, created); showNotice(`Created profile v${created.version} as draft.`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const publishProfile = async () => {
    setBusy(true);
    try {
      const result = await api(`/api/erp-profiles/${selected.id}/versions/${version.version}/publish`, { method: 'POST' });
      const list = await api('/api/erp-profiles/admin'); setProfiles(list);
      const profile = list.find((x) => x.id === selected.id); setSelected(profile);
      await loadDetail(profile, profile.versions.find((x) => x.version === result.profile_version));
      showNotice('ERP profile version published and available for new requests.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const retireProfileVersion = async (item) => {
    try {
      await api(`/api/erp-profiles/${selected.id}/versions/${item.version}/retire`, { method: 'POST' });
      await loadProfiles();
      showNotice(`ERP profile version ${item.version} retired.`);
    } catch (e) { setError(e.message); }
  };

  const addGlobalPrompt = async (event) => {
    event.preventDefault();
    try {
      const item = await api('/api/erp-profiles/global-prompts', { method: 'POST', body: JSON.stringify(globalForm) });
      setGlobalPrompts((xs) => [item, ...xs]); setGlobalForm({ name: '', stage: '*', content: '' });
      showNotice('Global prompt draft created.');
    } catch (e) { setError(e.message); }
  };

  const loadGlobalPrompts = async () => {
    try { setGlobalPrompts(await api('/api/erp-profiles/global-prompts')); } catch (e) { setError(e.message); }
  };

  const loadFeedbackQueue = async () => {
    try { setFeedbackQueue(await api('/api/erp-profiles/feedback')); } catch (e) { setError(e.message); }
  };

  const canManageFeedback = (item, administratorOnly = false) => identity?.capabilities.manage_clients
    || identity?.clients.some((client) => client.id === item.client_id
      && client.roles.some((role) => role === 'CLIENT_ADMIN' || (!administratorOnly && role === 'CONSULTANT')));

  const promoteFeedback = async (item, scope = 'ERP') => {
    if (!canPublish || !canManageFeedback(item, true)) return;
    try {
      await api(`/api/projects/${item.project_id}/feedback/${item.id}/promote`, {
        method: 'POST', body: JSON.stringify({ scope, ...(scope === 'ERP' ? { profile_id: item.profile_id } : {}) }),
      });
      await loadFeedbackQueue();
      await loadDetail(selected, version);
      showNotice('Reviewer guidance promoted to the selected ERP profile.');
    } catch (e) { setError(e.message); }
  };

  const ignoreFeedback = async (item) => {
    if (!canEdit || !canManageFeedback(item)) return;
    try {
      await api(`/api/projects/${item.project_id}/feedback/${item.id}/ignore`, { method: 'POST' });
      await loadFeedbackQueue();
    } catch (e) { setError(e.message); }
  };

  const publishGlobalPrompt = async (item) => {
    try {
      await api(`/api/erp-profiles/global-prompts/${item.id}/publish`, { method: 'POST' });
      await loadGlobalPrompts();
    } catch (e) { setError(e.message); }
  };

  const panel = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: 20 };
  const input = { width: '100%', border: '1px solid #cbd5e1', borderRadius: 6, padding: '9px 11px', font: 'inherit', fontSize: 13, color: '#1e293b', background: '#fff' };
  const label = { fontSize: 12, fontWeight: 650, color: '#475569', display: 'block', marginBottom: 6 };
  const primary = { border: 0, borderRadius: 6, background: '#fc7500', color: '#fff', fontWeight: 650, padding: '9px 13px', cursor: 'pointer', fontSize: 12 };
  const visibleProfiles = profiles.filter((item) => {
    const search = profileSearch.trim().toLowerCase();
    const matchesSearch = !search || `${item.display_name} ${item.name} ${item.vendor}`.toLowerCase().includes(search);
    const matchesStatus = profileStatus === 'ALL' || item.status === profileStatus;
    return matchesSearch && matchesStatus;
  });

  return <div style={{ minHeight: '100%', background: '#f4f7fa', padding: '24px 32px', color: '#1e293b' }}>
    <div style={{ maxWidth: 1280, margin: '0 auto' }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {onBack && <button className="btn btn-secondary" onClick={onBack}><ArrowLeft size={14} /> Back to Engineering</button>}
          <div><div style={{ fontSize: 11, color: '#64748b', fontWeight: 700, letterSpacing: '.08em' }}>ADMINISTRATION</div><h1 style={{ fontSize: 23 }}>ERP Profiles</h1></div>
        </div>
        <button disabled={!canEdit || busy} style={primary} onClick={() => { setShowCreate(true); setError(''); }}><Plus size={14} style={{ verticalAlign: 'middle', marginRight: 5 }} /> Add ERP</button>
      </header>

      <section style={{ ...panel, padding: 14, marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
        <ShieldCheck size={17} color="#0096e6" />
        <div style={{ flex: 1, fontSize: 12 }}>Authenticated as <strong>{identity?.user_id}</strong>. Configuration and publication follow your assigned permissions.</div>
        <button className="btn btn-blue" onClick={loadProfiles}>Refresh registry</button>
      </section>

      {(notice || error) && <div style={{ padding: '10px 14px', borderRadius: 7, marginBottom: 14, background: error ? '#fef2f2' : '#ecfdf5', color: error ? '#b91c1c' : '#047857', fontSize: 13 }}>{error || notice}</div>}

      {showCreate && <div style={{ ...panel, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}><h2 style={{ fontSize: 16 }}>Add ERP profile</h2><button className="btn btn-secondary" onClick={() => setShowCreate(false)}><X size={14} /></button></div>
        <form onSubmit={createProfile} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {['name', 'vendor', 'version', 'description'].map((key) => <div key={key}><label style={label}>{key === 'name' ? 'ERP name' : key[0].toUpperCase() + key.slice(1)}</label><input style={input} required={key !== 'description'} value={profileForm[key]} onChange={(e) => setProfileForm({ ...profileForm, [key]: e.target.value })} /></div>)}
          <div style={{ gridColumn: '1 / -1' }}><label style={label}>Workflow artifact stages (one per line)</label><textarea style={{ ...input, minHeight: 110, fontFamily: 'var(--font-mono)' }} value={profileForm.stages} onChange={(e) => setProfileForm({ ...profileForm, stages: e.target.value })} /></div>
          <div style={{ gridColumn: '1 / -1', textAlign: 'right' }}><button style={primary} disabled={busy}>{busy ? 'Creating…' : 'Create draft profile'}</button></div>
        </form>
      </div>}

      <div style={{ display: 'grid', gridTemplateColumns: '270px minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
        <aside style={{ ...panel, padding: 10 }}>
          <div style={{ padding: '8px 10px', fontSize: 11, color: '#64748b', fontWeight: 700 }}>PROFILE REGISTRY</div>
          <div style={{ padding: '0 8px 8px', display: 'grid', gap: 6 }}><input style={{ ...input, padding: '7px 9px', fontSize: 12 }} placeholder="Search ERP profiles" value={profileSearch} onChange={(e) => setProfileSearch(e.target.value)} /><select style={{ ...input, padding: '7px 9px', fontSize: 12 }} value={profileStatus} onChange={(e) => setProfileStatus(e.target.value)}><option value="ALL">All statuses</option>{['DRAFT', 'REVIEW', 'PUBLISHED', 'RETIRED'].map((status) => <option key={status}>{status}</option>)}</select></div>
          {visibleProfiles.map((item) => <button key={item.id} onClick={() => { setTab('Overview'); loadDetail(item); }} style={{ display: 'block', textAlign: 'left', width: '100%', padding: '11px 10px', border: 0, borderRadius: 6, cursor: 'pointer', background: selected?.id === item.id ? '#eff8ff' : 'transparent', color: '#1e293b', marginBottom: 3 }}>
            <strong style={{ display: 'block', fontSize: 13 }}>{item.display_name || item.name}</strong><span style={{ fontSize: 11, color: '#64748b' }}>{item.vendor}{item.version_label ? ` · ${item.version_label}` : ''} · {item.versions?.length || 0} versions</span><small style={{ display: 'block', marginTop: 4, color: item.status === 'PUBLISHED' ? '#047857' : '#92400e' }}>{item.status}</small>
          </button>)}
          {!visibleProfiles.length && <div style={{ padding: 12, color: '#64748b', fontSize: 12 }}>{profiles.length ? 'No profiles match these filters.' : 'No ERP profiles are available for your identity.'}</div>}
        </aside>

        <section style={{ ...panel, minHeight: 620 }}>
          {selected && version ? <>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, borderBottom: '1px solid #e2e8f0', paddingBottom: 16, marginBottom: 14 }}>
              <div><div style={{ color: '#64748b', fontSize: 11, fontWeight: 700 }}>{selected.vendor} · {selected.version_label}</div><h2 style={{ fontSize: 20 }}>{selected.display_name || selected.name}</h2><span style={{ fontSize: 12, color: '#64748b' }}>Profile v{version.version} · <b>{version.status}</b></span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <select aria-label="Profile version" disabled={busy} value={version.version} onChange={(e) => loadDetail(selected, selected.versions.find((x) => x.version === Number(e.target.value)))} style={{ ...input, width: 140 }}>{selected.versions?.map((v) => <option key={v.id} value={v.version}>Version {v.version} · {v.status}</option>)}</select>
                <button className="btn btn-secondary" onClick={newVersion} disabled={!canEdit || busy || ['DRAFT', 'REVIEW'].includes(selected.versions?.[0]?.status)}>New version</button>
                {version.status !== 'PUBLISHED' && <button style={primary} disabled={!canPublish || busy} onClick={publishProfile}>Publish version</button>}
              </div>
            </div>
            <nav style={{ display: 'flex', flexWrap: 'wrap', gap: 4, borderBottom: '1px solid #e2e8f0', paddingBottom: 10, marginBottom: 18 }}>
              {TABS.map(([title, value]) => <button key={title} disabled={busy} onClick={() => { setTab(value); if (value === 'Global') loadGlobalPrompts(); if (value === 'Feedback') loadFeedbackQueue(); }} style={{ border: 0, borderRadius: 5, background: tab === value ? '#eaf6ff' : 'transparent', color: tab === value ? '#0077b6' : '#475569', fontSize: 11, fontWeight: 650, padding: '7px 9px', cursor: 'pointer' }}>{title}</button>)}
            </nav>
            {version.status === 'PUBLISHED' && <div style={{ padding: 10, marginBottom: 12, borderRadius: 6, background: '#fffbeb', color: '#92400e', fontSize: 12 }}>This version is immutable. Create a new version to make configuration changes.</div>}
            {tab === 'Patterns' && <IntegrationPatterns key={selected.id} profile={selected} canEdit={canEdit} canPublish={canPublish} onRegistryChanged={onRegistryChanged} />}

            {tab === 'Overview' && <div><p style={{ color: '#64748b', fontSize: 13, marginBottom: 12 }}>Stages run one after another in the listed order. Each stage waits for the previous stage and any additional configured dependencies to be approved. Published versions stay pinned to existing requests.</p><label style={label}>Profile configuration</label><textarea disabled={!canEdit || busy || version.status === 'PUBLISHED'} value={configText} onChange={(e) => setConfigText(e.target.value)} style={{ ...input, minHeight: 380, fontFamily: 'var(--font-mono)', fontSize: 12 }} /><button style={{ ...primary, marginTop: 10 }} disabled={!canEdit || busy || version.status === 'PUBLISHED'} onClick={saveConfiguration}>Save configuration</button></div>}

            {tab === 'Prompts' && <div><h3 style={{ fontSize: 15, marginBottom: 10 }}>Prompt Studio</h3><form onSubmit={addPrompt} style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}><input style={input} placeholder="Prompt name" required value={promptForm.name} onChange={(e) => setPromptForm({ ...promptForm, name: e.target.value })} /><select style={input} value={promptForm.scope} onChange={(e) => setPromptForm({ ...promptForm, scope: e.target.value })}><option value="STAGE">Stage</option><option value="ERP">ERP-wide</option></select><select style={input} value={promptForm.stage} onChange={(e) => setPromptForm({ ...promptForm, stage: e.target.value })}>{(version.supported_artifact_types || []).map((stage) => <option key={stage}>{stage}</option>)}</select></div>
              <textarea style={{ ...input, minHeight: 130, fontFamily: 'var(--font-mono)', fontSize: 12 }} required placeholder="Write the governed system instructions for this scope and stage." value={promptForm.content} onChange={(e) => setPromptForm({ ...promptForm, content: e.target.value })} />
              <div><button style={primary} disabled={!canEdit || busy || version.status === 'PUBLISHED'}><Plus size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />Add prompt version</button></div>
            </form><div style={{ display: 'grid', gap: 8 }}>{prompts.map((item) => <article key={item.id} style={{ border: '1px solid #e2e8f0', borderRadius: 7, padding: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}><div><b>{item.name}</b> <span style={{ color: '#64748b', fontSize: 12 }}>· {item.scope} · {item.stage} · v{item.version} · {item.status}</span></div>{item.status === 'DRAFT' && <button className="btn btn-blue" disabled={!canPublish || busy} onClick={() => publishPrompt(item)}>Publish</button>}{item.status === 'PUBLISHED' && version.status !== 'PUBLISHED' && <button className="btn btn-secondary" disabled={!canPublish || busy} onClick={() => retirePrompt(item)}>Retire from draft</button>}</div><pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: '#475569', maxHeight: 120, overflow: 'auto', marginTop: 8 }}>{item.content}</pre></article>)}</div></div>}

            {(tab === 'PACKAGE' || tab === 'KNOWLEDGE') && <div><h3 style={{ fontSize: 15, marginBottom: 10 }}>{tab === 'PACKAGE' ? 'Standard Package Library' : 'Knowledge Hub'}</h3><form onSubmit={(e) => addTextAsset(e, tab)} style={{ display: 'grid', gap: 9, marginBottom: 15 }}>
              <input style={input} required placeholder={tab === 'PACKAGE' ? 'Package name' : 'Knowledge asset name'} value={assetForm.name} onChange={(e) => setAssetForm({ ...assetForm, name: e.target.value })} />
              {tab === 'PACKAGE' && <input style={input} placeholder="Package type (source, template, archive, example…)" value={assetForm.package_type} onChange={(e) => setAssetForm({ ...assetForm, package_type: e.target.value })} />}
              <input style={input} placeholder="Purpose / description" value={assetForm.description} onChange={(e) => setAssetForm({ ...assetForm, description: e.target.value })} />
              <textarea style={{ ...input, minHeight: 110, fontFamily: 'var(--font-mono)', fontSize: 12 }} placeholder="Paste approved text/code or add a short reference excerpt" value={assetForm.text_content} onChange={(e) => setAssetForm({ ...assetForm, text_content: e.target.value })} />
              <div><button style={primary} disabled={!canEdit || busy || version.status === 'PUBLISHED'}><Plus size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />Add text asset</button></div>
            </form><form onSubmit={(e) => uploadAsset(e, tab)} encType="multipart/form-data" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: 12, background: '#f8fafc', borderRadius: 7, marginBottom: 18 }}>
              <input name="name" style={input} placeholder="Asset name" required /><input name="package_type" style={input} placeholder="Package type (optional)" /><input name="description" style={{ ...input, gridColumn: '1 / -1' }} placeholder="Description" /><input name="files" type="file" multiple style={{ gridColumn: '1 / -1', fontSize: 12 }} required /><button style={{ ...primary, justifySelf: 'start' }} disabled={!canEdit || busy || version.status === 'PUBLISHED'}><Upload size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />Upload files</button>
            </form><div style={{ display: 'grid', gap: 8 }}>{assets.filter((a) => a.asset_kind === tab).map((item) => <article key={item.id} style={{ border: '1px solid #e2e8f0', borderRadius: 7, padding: 12, display: 'flex', justifyContent: 'space-between', gap: 12 }}><div><b>{item.name}</b> <span style={{ color: '#64748b', fontSize: 12 }}>v{item.version} · {item.status}{item.file_name ? ` · ${item.file_name}` : ''}</span><p style={{ fontSize: 12, color: '#64748b' }}>{item.description || item.package_type || 'Approved ERP asset'}</p></div><div>{item.status === 'DRAFT' && <button className="btn btn-blue" disabled={!canPublish || busy} onClick={() => publishAsset(item)}>Publish</button>}{item.status === 'PUBLISHED' && version.status !== 'PUBLISHED' && <button className="btn btn-secondary" disabled={!canPublish || busy} onClick={() => retireAsset(item)}>Retire from draft</button>}</div></article>)}</div></div>}

            {tab === 'Validation' && <div><h3 style={{ fontSize: 15, marginBottom: 8 }}>Validation configuration</h3><p style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>Configure common rules as JSON. Supported rule types include required_keys, regex, and max_length. Strategy validators are selected per workflow stage.</p><textarea disabled={!canEdit || busy || version.status === 'PUBLISHED'} value={configText} onChange={(e) => setConfigText(e.target.value)} style={{ ...input, minHeight: 370, fontFamily: 'var(--font-mono)', fontSize: 12 }} /><button style={{ ...primary, marginTop: 10 }} disabled={!canEdit || busy || version.status === 'PUBLISHED'} onClick={saveConfiguration}>Save validation configuration</button></div>}

            {tab === 'Strategy' && <div><h3 style={{ fontSize: 15, marginBottom: 8 }}>Generation strategy</h3><p style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>Each stage selects a configured adapter. Generic JSON generation works without ERP-specific code; specialized adapters are explicit integrations.</p><textarea disabled={!canEdit || busy || version.status === 'PUBLISHED'} value={configText} onChange={(e) => setConfigText(e.target.value)} style={{ ...input, minHeight: 370, fontFamily: 'var(--font-mono)', fontSize: 12 }} /><button style={{ ...primary, marginTop: 10 }} disabled={!canEdit || busy || version.status === 'PUBLISHED'} onClick={saveConfiguration}>Save generation strategy</button></div>}

            {tab === 'Versions' && <div><h3 style={{ fontSize: 15, marginBottom: 12 }}>Profile version history</h3>{selected.versions?.map((item) => <div key={item.id} style={{ padding: 12, border: '1px solid #e2e8f0', borderRadius: 7, marginBottom: 7, display: 'flex', justifyContent: 'space-between' }}><div><b>Version {item.version}</b> <span style={{ fontSize: 12, color: '#64748b' }}>{item.status} · {item.created_at ? new Date(item.created_at).toLocaleString() : ''}</span></div><div><button className="btn btn-secondary" onClick={() => loadDetail(selected, item)}>Open</button>{item.status === 'PUBLISHED' && <button className="btn btn-secondary" style={{ marginLeft: 8 }} disabled={!canPublish || busy} onClick={() => retireProfileVersion(item)}>Retire</button>}</div></div>)}</div>}
            {tab === 'Feedback' && <div><h3 style={{ fontSize: 15, marginBottom: 12 }}>Reviewer feedback and ERP guidance</h3><h4 style={{ fontSize: 12, margin: '18px 0 8px' }}>Project feedback awaiting a human promotion decision</h4>{feedbackQueue.filter((item) => item.status === 'APPROVED' && item.profile_id === selected.id).map((item) => <div key={item.id} style={{ padding: 12, border: '1px solid #e2e8f0', borderRadius: 7, marginBottom: 7 }}><b>{item.project_name} · {item.stage || 'All stages'}</b><p style={{ fontSize: 13 }}>{item.content}</p><button className="btn btn-blue" disabled={!canPublish || !canManageFeedback(item, true) || busy} onClick={() => promoteFeedback(item)}>Promote to ERP guidance</button><button className="btn btn-secondary" style={{ marginLeft: 8 }} disabled={!canPublish || !canManageFeedback(item, true) || busy} onClick={() => promoteFeedback(item, 'GLOBAL')}>Promote globally</button><button className="btn btn-secondary" style={{ marginLeft: 8 }} disabled={!canEdit || !canManageFeedback(item) || busy} onClick={() => ignoreFeedback(item)}>Ignore</button></div>)}<h4 style={{ fontSize: 12, margin: '18px 0 8px' }}>Approved ERP guidance</h4>{feedback.map((item) => <div key={item.id} style={{ padding: 12, border: '1px solid #e2e8f0', borderRadius: 7, marginBottom: 7 }}><b>{item.stage || 'All stages'}</b><p style={{ fontSize: 13 }}>{item.content}</p></div>)}{!feedback.length && !feedbackQueue.some((item) => item.status === 'APPROVED' && item.profile_id === selected.id) && <p style={{ color: '#64748b', fontSize: 13 }}>No feedback is available for this ERP profile.</p>}</div>}
            {tab === 'Audit' && <div><h3 style={{ fontSize: 15, marginBottom: 12 }}>Administrative audit</h3>{audit.map((item) => <div key={item.id} style={{ padding: 10, borderBottom: '1px solid #e2e8f0', fontSize: 12 }}><b>{item.action}</b> · {item.actor} · {new Date(item.created_at).toLocaleString()}<pre style={{ whiteSpace: 'pre-wrap', color: '#64748b' }}>{JSON.stringify(item.details)}</pre></div>)}</div>}
            {tab === 'Usage' && <div><h3 style={{ fontSize: 15, marginBottom: 12 }}>Profile usage</h3><div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}><div style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 18 }}><div style={{ color: '#64748b', fontSize: 12 }}>Integration requests pinned to this profile</div><strong style={{ fontSize: 28 }}>{usage?.integration_requests ?? '—'}</strong></div><div style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 18 }}><div style={{ color: '#64748b', fontSize: 12 }}>Generation runs</div><strong style={{ fontSize: 28 }}>{usage?.generation_runs ?? '—'}</strong></div></div></div>}
            {tab === 'Global' && <div><h3 style={{ fontSize: 15, marginBottom: 10 }}>Global Prompt Registry</h3><form onSubmit={addGlobalPrompt} style={{ display: 'grid', gap: 8, marginBottom: 16 }}><input style={input} required placeholder="Prompt name" value={globalForm.name} onChange={(e) => setGlobalForm({ ...globalForm, name: e.target.value })} /><input style={input} required placeholder="Stage or * for all stages" value={globalForm.stage} onChange={(e) => setGlobalForm({ ...globalForm, stage: e.target.value })} /><textarea style={{ ...input, minHeight: 100, fontFamily: 'var(--font-mono)' }} required placeholder="Global engineering rules" value={globalForm.content} onChange={(e) => setGlobalForm({ ...globalForm, content: e.target.value })} /><button disabled={!canEdit || busy} style={{ ...primary, justifySelf: 'start' }}>Add global prompt</button></form>{globalPrompts.map((item) => <div key={item.id} style={{ padding: 10, border: '1px solid #e2e8f0', borderRadius: 7, marginBottom: 7 }}><b>{item.name}</b> · {item.stage} · v{item.version} · {item.status}{item.status === 'DRAFT' && <button className="btn btn-blue" style={{ marginLeft: 10 }} disabled={!canPublish || busy} onClick={() => publishGlobalPrompt(item)}>Publish</button>}</div>)}</div>}
          </> : <div style={{ minHeight: 500, display: 'grid', placeItems: 'center', color: '#64748b', textAlign: 'center' }}><div><Boxes size={34} color="#0096e6" style={{ marginBottom: 10 }} /><h2 style={{ color: '#1e293b', fontSize: 17 }}>Select an ERP profile</h2><p style={{ fontSize: 13 }}>Create and govern ERP behavior through profile data and versioned assets.</p></div></div>}
        </section>
      </div>
    </div>
  </div>;
}
