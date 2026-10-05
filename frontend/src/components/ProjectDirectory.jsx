import React, { useState } from 'react';
import { ArrowLeft, ArrowRight, Clock, Download, FlaskConical, Layers, Plus, Search, Settings2, ShieldCheck } from 'lucide-react';
import { label, dateLabel } from '../utils/product';
import { useApiResource } from '../hooks/useApiResource';
import { downloadApiFile } from '../api';

export function StatusBadge({ status }) { return <span className={`badge ${status === 'COMPLETED' || status === 'APPROVED' ? 'green' : status?.includes('REVIEW') ? 'amber' : 'blue'}`}><span className="status-dot" />{label(status)}</span>; }

export default function ProjectDirectory({ profiles = [], profileError, onOpen, onCreate, selecting, directoryState, onDirectoryChange }) {
  const [localState, setLocalState] = useState({ filters: { search: '', erp_profile_id: '', project_type: '', request_status: '' }, offset: 0, sort: 'last_activity:desc' });
  const { filters, offset, sort } = directoryState || localState;
  const updateState = onDirectoryChange || setLocalState;
  const setFilters = (value) => updateState((old) => ({ ...old, filters: typeof value === 'function' ? value(old.filters) : value }));
  const setOffset = (value) => updateState((old) => ({ ...old, offset: value }));
  const setSort = (value) => updateState((old) => ({ ...old, sort: value }));
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState('');
  const [sortField, direction] = sort.split(':');
  const query = new URLSearchParams({ limit: '25', offset: String(offset), sort: sortField, direction });
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
  const resource = useApiResource(`/api/projects?${query}`);
  const projects = resource.data?.projects || [];
  const change = (name, value) => { setFilters((previous) => ({ ...previous, [name]: value })); setOffset(0); };
  const download = async (project) => {
    setError(''); setDownloading(project.id);
    try {
      if (!project.package_download_url?.startsWith(`/api/projects/${project.id}/package/`)) throw new Error('This project has no current package download. Open Studio to prepare an eligible source bundle.');
      await downloadApiFile(project.package_download_url, `${project.name}-${project.package_kind || 'package'}.zip`);
    }
    catch (cause) { setError(cause.message); }
    finally { setDownloading(''); }
  };
  const counts = resource.data?.summary;
  return <div className="page home-page">
    <div className="page-heading"><div><div className="eyebrow">INTEGRATION ENGINEERING</div><h1>{selecting ? 'Your engineering studio' : 'Integration projects'}</h1><p>{selecting ? 'Choose a project to pick up exactly where you left off.' : 'Every client. Every ERP. One place to manage delivery.'}</p></div>{onCreate && <button className="btn primary" onClick={onCreate}><Plus className="icon" />Create New</button>}</div>
    <div className="metrics">{[
      ['', 'All projects', resource.data?.total, Layers, 'Authorized projects'],
      ['PENDING_REVIEW', 'Awaiting review', counts?.awaiting_review, Clock, 'Human approval'],
      ['READY_FOR_SANDBOX', 'Ready for sandbox', counts?.ready_for_sandbox, FlaskConical, 'Approved candidates'],
      ['RELEASED', 'Released', counts?.completed, ShieldCheck, 'Tested releases'],
    ].map(([status, title, count, Icon, detail]) => <button key={title} className={`metric ${filters.request_status === status ? 'selected' : ''}`} onClick={() => change('request_status', status)}><span className="metric-label">{title}<Icon className="icon" /></span><strong>{count == null ? '—' : String(count).padStart(2, '0')}</strong><span className="metric-detail">{count == null ? 'Summary not available' : detail}</span></button>)}</div>
    {(error || resource.error || profileError) && <div className="notice red" role="alert">{error || resource.error || profileError}<button className="btn ghost" onClick={resource.reload}>Retry</button></div>}
    <section className="table-card" aria-labelledby="directory-title"><div className="table-heading"><div><h2 id="directory-title">{selecting ? 'Select a project' : 'Project directory'}<span className="count">{resource.data?.total ?? '—'}</span></h2><p>Track progress, resume work and download approved packages.</p></div><button className="btn ghost" onClick={() => { setFilters({ search: '', erp_profile_id: '', project_type: '', request_status: '' }); setOffset(0); }}><Settings2 className="icon" />Clear filters</button></div>
    <div className="filters"><label className="search-field"><Search className="icon" /><input aria-label="Search projects or clients" placeholder="Search projects or clients…" value={filters.search} onChange={(event) => change('search', event.target.value)} /></label>
      <select aria-label="Filter requests by ERP" value={filters.erp_profile_id} onChange={(event) => change('erp_profile_id', event.target.value)}><option value="">All ERPs</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.display_name || profile.name}</option>)}</select>
      <select aria-label="Filter project type" value={filters.project_type} onChange={(event) => change('project_type', event.target.value)}><option value="">All types</option><option value="STANDARD">Standard</option><option value="CUSTOM">Custom</option></select>
      <select aria-label="Sort projects" value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0); }}><option value="last_activity:desc">Recently updated</option><option value="name:asc">Project name</option><option value="due:asc">Due date</option></select>
      <select aria-label="Filter requests by status" value={filters.request_status} onChange={(event) => change('request_status', event.target.value)}><option value="">All statuses</option>{['ACTIVE', 'PENDING_REVIEW', 'CHANGES_REQUESTED', 'READY_FOR_SANDBOX', 'SANDBOX_BLOCKED', 'READY_FOR_RELEASE', 'RELEASED', 'COMPLETED', 'ARCHIVED'].map((status) => <option key={status} value={status}>{label(status)}</option>)}</select>
    </div>
    <div className="table-scroll"><table><thead><tr>{['CLIENT NAME', 'PROJECT NAME', 'ERP', 'TYPE', 'STATUS', 'DUE DATE', 'LAST UPDATED', 'PACKAGE'].map((name) => <th key={name}>{name}</th>)}<th><span className="sr-only">Open Studio</span></th></tr></thead><tbody>{resource.loading ? <tr><td colSpan={9}><div className="empty-table" role="status">Loading projects…</div></td></tr> : projects.map((project) => <tr key={project.id}>
      <td><div className="client-cell"><span className="client-avatar blue">{(project.client_name || '—').slice(0, 2).toUpperCase()}</span><span>{project.client_name || 'Client unavailable'}</span></div></td>
      <td><button className="project-link" onClick={() => onOpen(project.id)}>{project.name}</button><small>INT-{project.id.slice(0, 8).toUpperCase()}</small></td>
      <td><span className="erp-name">{project.erp_name || 'ERP unavailable'}</span><small>{project.erp_version ? `Profile v${project.erp_version}` : 'Pinned profile'}</small></td>
      <td><span className={`type-chip ${(project.project_type || 'CUSTOM').toLowerCase()}`}>{label(project.project_type || 'CUSTOM')}</span></td>
      <td><StatusBadge status={project.workflow_status || project.business_status || project.status} /><small>{label(project.current_stage)}</small></td><td>{dateLabel(project.due_date)}</td><td>{dateLabel(project.last_activity_at || project.updated_at)}</td>
      <td>{project.package_available ? <button className="download-link" disabled={!!downloading} onClick={() => { void download(project); }}><Download className="icon" />{downloading === project.id ? 'Downloading…' : project.package_kind === 'release' ? 'Release' : 'Source bundle'}</button> : <><span className="package-locked">—</span><small>After package approval</small></>}</td>
      <td><button className="row-open" title="Open Studio" aria-label={`Open Studio for ${project.name}`} onClick={() => onOpen(project.id)}><ArrowRight className="icon" /></button></td>
    </tr>)}{!resource.loading && !projects.length && <tr><td colSpan={9}><div className="empty-table">{resource.error ? 'Projects could not be loaded.' : 'No projects match these filters.'}</div></td></tr>}</tbody></table></div>
    <div className="table-footer"><span>Showing {projects.length ? offset + 1 : 0}–{offset + projects.length} of {resource.data?.total ?? '—'} projects</span><div><button className="page-button" aria-label="Previous projects" disabled={!offset || resource.loading} onClick={() => setOffset(Math.max(0, offset - 25))}><ArrowLeft className="icon" /></button><span>Page {Math.floor(offset / 25) + 1}</span><button className="page-button" aria-label="Next projects" disabled={resource.data?.next_offset == null || resource.loading} onClick={() => setOffset(resource.data.next_offset)}><ArrowRight className="icon" /></button></div></div></section>
    <div className="home-note"><ShieldCheck className="icon" />Approvals apply to exact revisions. Your history stays with the project.</div>
  </div>;
}
