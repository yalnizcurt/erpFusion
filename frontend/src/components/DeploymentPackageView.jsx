import React, { useEffect, useState } from 'react';
import { Download, FileCode2, FileOutput, PackageCheck } from 'lucide-react';
import { downloadApiFile, requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';

function toDownloadableFiles(stage, version) {
  const content = version?.content;
  if (!content || typeof content !== 'object') return [];

  const files = [];
  const add = (name, body, type = 'text/plain') => {
    if (typeof body !== 'string' || !body.trim()) return;
    files.push({ stage, revision: version.version_number, name: String(name), body, type });
  };

  // Strategies may return an explicit file collection, regardless of ERP or language.
  for (const key of ['output_files', 'generated_files', 'files']) {
    if (!Array.isArray(content[key])) continue;
    content[key].forEach((file, index) => {
      if (typeof file === 'string') {
        add(file, file);
        return;
      }
      if (!file || typeof file !== 'object') return;
      const name = file.file_name || file.filename || file.name || `${stage.toLowerCase()}-${index + 1}`;
      const body = file.content ?? file.text ?? file.body;
      add(name, body, file.mime_type || file.type || 'text/plain');
    });
  }

  // The initial PL/SQL strategy returns spec/body source fields; preserve their real extensions.
  const packageName = String(content.package_name || stage.toLowerCase()).replace(/[^a-zA-Z0-9_-]/g, '_');
  if (typeof content.pks_content === 'string') add(`${packageName}.pks`, content.pks_content);
  if (typeof content.pkb_content === 'string') add(`${packageName}.pkb`, content.pkb_content);

  // Some configured strategies return a filename-to-content object instead of a file array.
  const configuredFiles = content.files_by_name;
  if (configuredFiles && typeof configuredFiles === 'object' && !Array.isArray(configuredFiles)) {
    Object.entries(configuredFiles).forEach(([name, body]) => add(name, body));
  }

  for (const field of ['full_mode_sql', 'delta_mode_sql', 'selective_mode_sql', 'sql_content', 'grants_and_synonyms_sql', 'verification_script_sql', 'rollback_script_sql']) {
    if (typeof content[field] === 'string') add(`${stage.toLowerCase()}-${field}.sql`, content[field]);
  }
  if (typeof content.run_instructions_markdown === 'string') add('installation-instructions.md', content.run_instructions_markdown);

  return files.filter((file, index, all) => all.findIndex((other) => other.name === file.name) === index);
}

async function sha256(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function canPrepare(identity, clientId) {
  const roles = identity?.clients?.find((client) => client.id === clientId)?.roles || [];
  return !!identity?.capabilities?.manage_clients || roles.some((role) => ['CLIENT_ADMIN', 'CONSULTANT', 'TECHNICAL_REVIEWER'].includes(role));
}

export default function DeploymentPackageView({ projectId, workflowStages = [], identity, clientId }) {
  const resource = useApiResource(projectId ? `/api/projects/${projectId}/package` : null);
  const releasesResource = useApiResource(projectId ? `/api/projects/${projectId}/package/releases` : null);
  const files = resource.data?.files || [];
  const [selected, setSelected] = useState('');
  const file = files.find((item) => item.name === selected) || files[0] || null;
  const stage = workflowStages.find((item) => item.stage === file?.stage);
  const version = useApiResource(stage?.artifact_id && file ? `/api/artifacts/${stage.artifact_id}/versions/${file.revision}` : null);
  const body = file && version.data ? toDownloadableFiles(file.stage, version.data).find((item) => item.name === file.name)?.body : null;
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const [previewHash, setPreviewHash] = useState(null);
  const [fileDownloading, setFileDownloading] = useState(false);
  const releases = releasesResource.data?.releases || [];
  const mayPrepare = canPrepare(identity, clientId || resource.data?.manifest?.client_id);
  const hasCurrentPackage = !!resource.data?.candidate_id;
  useEffect(() => {
    let active = true;
    if (body) void sha256(body).then((checksum) => { if (active) setPreviewHash({ body, checksum }); });
    return () => { active = false; };
  }, [body, file?.sha256]);
  const bodyChecksum = previewHash?.body === body ? previewHash.checksum : '';
  const download = async () => {
    setDownloading(true); setError('');
    try {
      if (!hasCurrentPackage) {
        if (!resource.data?.available || !mayPrepare) throw new Error('An authorized project member must prepare the source bundle first.');
        await requestJson(`/api/projects/${projectId}/package/candidates`, { method: 'POST', body: '{}' });
      }
      await downloadApiFile(`/api/projects/${projectId}/package/download`, `project-${projectId}-package.zip`);
      resource.reload();
    }
    catch (cause) { setError(cause.message); }
    finally { setDownloading(false); }
  };
  const downloadSource = async () => {
    setFileDownloading(true); setError('');
    try {
      if (!resource.data?.candidate_id || !file) throw new Error('The source bundle is not available for individual file download.');
      await downloadApiFile(`/api/projects/${projectId}/package/candidates/${resource.data.candidate_id}/files?name=${encodeURIComponent(file.name)}`, file.name.split('/').pop() || file.name);
    } catch (cause) { setError(cause.message); }
    finally { setFileDownloading(false); }
  };
  const downloadRelease = async (release) => {
    setDownloading(true); setError('');
    try { await downloadApiFile(release.download_url || `/api/projects/${projectId}/package/releases/${release.id}/download`, `release-${release.id}.zip`); }
    catch (cause) { setError(cause.message); }
    finally { setDownloading(false); }
  };
  const packageButtonLabel = hasCurrentPackage
    ? resource.data?.release_id ? 'Download immutable release ZIP' : 'Download source bundle ZIP'
    : mayPrepare ? 'Prepare source bundle' : 'Source bundle not prepared';
  return <section className="workspace-card package-workspace">
    <div className="section-title"><span className="section-icon"><PackageCheck className="icon" /></span><div><h2>{resource.data?.kind === 'release' ? 'Tested release' : 'Source bundle'}</h2><p>Complete source archive from the exact approved revisions.</p></div><button className="btn primary" disabled={!resource.data?.available || (!hasCurrentPackage && !mayPrepare) || downloading} onClick={() => { void download(); }}><Download className="icon" />{downloading ? 'Working…' : packageButtonLabel}</button></div>
    {(error || resource.error) && <div className="notice red" role="alert">{error || resource.error}</div>}
    {resource.loading ? <p role="status">Loading package manifest…</p> : <>
      {!resource.data?.available && <div className="notice amber"><strong>Package download is blocked.</strong>{(resource.data?.blockers || ['Approve the required package revisions first.']).map((blocker, index) => <p key={index}>{typeof blocker === 'string' ? blocker : JSON.stringify(blocker)}</p>)}</div>}
      {files.length > 0 ? <div className="package-layout"><nav aria-label="Package files" className="file-tree">{files.map((item) => <button key={item.name} className={file?.name === item.name ? 'selected' : ''} onClick={() => setSelected(item.name)}><FileCode2 className="icon" /><span>{item.name}<small>{item.stage} · v{item.revision}</small></span></button>)}</nav><div className="file-preview"><div className="document-toolbar"><strong>{file?.name}</strong><small>{file?.size_bytes} bytes</small><button className="btn secondary" disabled={!file || !resource.data?.candidate_id || fileDownloading} onClick={() => { void downloadSource(); }}><Download className="icon" />Download exact source file</button></div><pre className="code-container">{version.loading ? 'Loading file preview…' : version.error || body || 'Source unavailable in the artifact response. Download the complete source bundle for this configured file.'}</pre><p className="input-note">Server SHA-256: {file?.sha256}{body && bodyChecksum === file?.sha256 ? ' · preview matches' : body ? ' · preview checksum differs' : ''}</p></div></div> : <div className="empty-table"><FileOutput className="icon" /><p>No package files are available.</p></div>}
      <details className="package-manifest"><summary>Manifest & provenance</summary><pre className="provenance-json">{JSON.stringify(resource.data?.manifest || {}, null, 2)}</pre></details>
    </>}
    {releases.length > 0 && <section className="context-card"><div className="context-heading"><PackageCheck className="icon" /><h3>Release history</h3></div>{releases.map((release) => <div className="revision-row" key={release.id}><span className="revision-icon"><PackageCheck className="icon" /></span><span><strong>{release.id}</strong><small>{new Date(release.created_at).toLocaleString()} · SHA-256 {release.checksum}</small></span><button className="btn secondary" disabled={downloading} onClick={() => { void downloadRelease(release); }}><Download className="icon" />Download</button></div>)}</section>}
  </section>;
}
