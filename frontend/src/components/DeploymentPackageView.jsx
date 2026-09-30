import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Download, FileCode2, FileOutput, LoaderCircle, PackageCheck } from 'lucide-react';
import { apiUrl } from '../api';

function cleanFilename(value) {
  return String(value || 'generated-artifact').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim() || 'generated-artifact';
}

function toDownloadableFiles(stage, version) {
  const content = version?.content;
  if (!content || typeof content !== 'object') return [];

  const files = [];
  const add = (name, body, type = 'text/plain') => {
    if (typeof body !== 'string' || !body.trim()) return;
    files.push({ stage, revision: version.version_number, name: cleanFilename(name), body, type });
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
  const packageName = cleanFilename(content.package_name || stage.toLowerCase());
  if (typeof content.pks_content === 'string') add(`${packageName}.pks`, content.pks_content);
  if (typeof content.pkb_content === 'string') add(`${packageName}.pkb`, content.pkb_content);

  // Some configured strategies return a filename-to-content object instead of a file array.
  const configuredFiles = content.files_by_name;
  if (configuredFiles && typeof configuredFiles === 'object' && !Array.isArray(configuredFiles)) {
    Object.entries(configuredFiles).forEach(([name, body]) => add(name, body));
  }

  return files.filter((file, index, all) => all.findIndex((other) => other.name === file.name) === index);
}

function downloadFile(file) {
  const url = URL.createObjectURL(new Blob([file.body], { type: file.type || 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function DeploymentPackageView({ projectId, workflowStages = [] }) {
  const [approvedArtifacts, setApprovedArtifacts] = useState({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [selectedFileName, setSelectedFileName] = useState('');

  useEffect(() => {
    let cancelled = false;
    async function loadApprovedArtifacts() {
      setApprovedArtifacts({});
      setLoadError('');
      if (!projectId || workflowStages.length === 0) return;
      const approved = workflowStages.filter((item) => item.gate_status === 'APPROVED' && item.artifact_id && item.current_version > 0);
      setLoading(true);
      try {
        const entries = await Promise.all(approved.map(async (item) => {
          const response = await fetch(apiUrl(`/api/artifacts/${item.artifact_id}/versions/${item.current_version}`));
          if (!response.ok) throw new Error(`Could not load approved ${item.stage} revision.`);
          return [item.stage, await response.json()];
        }));
        if (!cancelled) setApprovedArtifacts(Object.fromEntries(entries));
      } catch (error) {
        if (!cancelled) setLoadError(error.message || 'Could not load approved release artifacts.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadApprovedArtifacts();
    return () => { cancelled = true; };
  }, [projectId, workflowStages]);

  const files = useMemo(() => Object.entries(approvedArtifacts)
    .flatMap(([stage, version]) => toDownloadableFiles(stage, version))
    .sort((left, right) => left.name.localeCompare(right.name)), [approvedArtifacts]);
  const selectedFile = files.find((file) => file.name === selectedFileName) || files[0] || null;
  const approvedCount = workflowStages.filter((item) => item.gate_status === 'APPROVED').length;
  const releaseReady = workflowStages.length > 0 && approvedCount === workflowStages.length;

  useEffect(() => {
    if (files.length && !files.some((file) => file.name === selectedFileName)) setSelectedFileName(files[0].name);
    if (!files.length) setSelectedFileName('');
  }, [files, selectedFileName]);

  return <section className="hr-card" style={{ margin: '16px 24px', padding: '20px 24px' }}>
    <header style={{ display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid var(--border-light)', paddingBottom: 14, marginBottom: 14 }}>
      <PackageCheck size={20} color="var(--hr-orange)" />
      <div><h2 style={{ fontSize: 15 }}>Release artifacts</h2><p style={{ fontSize: 12, color: 'var(--text-muted)' }}>Download generated files from the request’s pinned ERP profile after every workflow gate is approved.</p></div>
      <span style={{ marginLeft: 'auto', color: releaseReady ? '#059669' : '#b45309', fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap' }}>
        {releaseReady ? 'All gates approved' : `${approvedCount} / ${workflowStages.length} gates approved`}
      </span>
    </header>

    {loading ? <div style={{ minHeight: 220, display: 'grid', placeItems: 'center', color: '#64748b' }}><LoaderCircle size={20} className="spin" /> Loading approved artifacts…</div>
      : loadError ? <div role="alert" style={{ padding: 14, color: '#b91c1c', background: '#fef2f2', borderRadius: 7 }}>{loadError}</div>
        : !releaseReady ? <div style={{ minHeight: 220, display: 'grid', placeItems: 'center', textAlign: 'center', color: '#64748b' }}><div><FileOutput size={30} /><p style={{ marginTop: 8, fontWeight: 600 }}>Release downloads unlock after the final gate is approved.</p><small>Review and approve each configured stage in order to publish the generated files.</small></div></div>
          : !files.length ? <div style={{ minHeight: 220, display: 'grid', placeItems: 'center', textAlign: 'center', color: '#64748b' }}><div><FileOutput size={30} /><p style={{ marginTop: 8, fontWeight: 600 }}>No downloadable files were produced.</p><small>Check the published ERP generation strategy and its configured output files.</small></div></div>
            : <div className="release-artifacts-layout" style={{ display: 'grid', gridTemplateColumns: 'minmax(200px, 270px) minmax(0, 1fr)', gap: 16 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8, color: '#475569', fontSize: 12, fontWeight: 700 }}><CheckCircle2 size={15} color="#059669" /> Approved files</div>
                <nav aria-label="Generated release files" style={{ display: 'grid', alignContent: 'start', gap: 7 }}>
                  {files.map((file) => <button key={`${file.stage}:${file.name}`} onClick={() => setSelectedFileName(file.name)} className="btn btn-secondary" style={{ justifyContent: 'space-between', textAlign: 'left', background: selectedFile?.name === file.name ? '#fff3e8' : '#f8fafc' }}><span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{file.name}</span><small style={{ color: '#64748b', marginLeft: 8 }}>{file.stage} v{file.revision}</small></button>)}
                </nav>
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}><FileCode2 size={16} color="var(--hr-orange)" /><strong style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis' }}>{selectedFile?.name}</strong></div>
                  <button className="btn btn-blue" disabled={!selectedFile} onClick={() => selectedFile && downloadFile(selectedFile)}><Download size={14} /> Download file</button>
                </div>
                <pre style={{ padding: 14, borderRadius: 6, background: '#0f172a', color: '#e2e8f0', minHeight: 280, maxHeight: '65vh', overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 12 }}>{selectedFile?.body}</pre>
              </div>
            </div>}
    {workflowStages.length > 0 && <div style={{ marginTop: 12, fontSize: 11, color: '#64748b' }}>Release files come from the approved revisions of this request’s pinned ERP profile version.</div>}
  </section>;
}
