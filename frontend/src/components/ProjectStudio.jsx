import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Check, ChevronRight, Clock, Lock, Sparkles } from 'lucide-react';
import { requestJson } from '../api';
import { useApiResource } from '../hooks/useApiResource';
import BottomCards from './BottomCards';
import DiffViewer from './DiffViewer';
import TraceabilityCard from './TraceabilityCard';
import DeploymentPackageView from './DeploymentPackageView';
import RequirementsWorkspace from './RequirementsWorkspace';
import ConnectionSettings from './ConnectionSettings';
import SandboxWorkspace from './SandboxWorkspace';
import QualificationWorkspace from './QualificationWorkspace';
import { StatusBadge } from './ProjectDirectory';
import { dateLabel, label } from '../utils/product';

export default function ProjectStudio({ projectId, identity, erpProfiles = [], onHome, onConnections, onRequirementDirtyChange }) {
  const base = `/api/projects/${encodeURIComponent(projectId)}`;
  const projectResource = useApiResource(base);
  const project = projectResource.data;
  const workflow = useApiResource(project ? `${base}/workflow` : null);
  const artifactResource = useApiResource(project ? `${base}/artifacts` : null);
  const jobs = useApiResource(project ? `${base}/generation-jobs` : null);
  const packageResource = useApiResource(project ? `${base}/package` : null);
  const inputHistory = useApiResource(project ? `${base}/input-revisions` : null);
  const stages = workflow.data?.stages || [];
  const params = new URLSearchParams(window.location.search);
  const [stageId, setStageId] = useState(params.get('stage') || '');
  const [tab, setTab] = useState(params.get('tab') || 'requirements');
  const [revision, setRevision] = useState(Number(params.get('revision')) || null);
  useEffect(() => {
    const update = () => { const query = new URLSearchParams(window.location.search); setStageId(query.get('stage') || ''); setTab(query.get('tab') || 'requirements'); setRevision(Number(query.get('revision')) || null); };
    window.addEventListener('popstate', update); return () => window.removeEventListener('popstate', update);
  }, []);
  const selectedStage = stages.find((stage) => stage.stage === stageId) || stages.find((stage) => stage.stage === workflow.data?.current_stage) || stages[0];
  const artifact = artifactResource.data?.find((item) => item.artifact_type === selectedStage?.stage);
  const versions = useApiResource(artifact ? `/api/artifacts/${artifact.id}/versions` : null);
  const selectedVersion = versions.data?.find((version) => version.version_number === revision) || versions.data?.[0] || null;
  const validations = useApiResource(artifact && selectedVersion ? `/api/artifacts/${artifact.id}/versions/${selectedVersion.version_number}/validations` : null);
  const [mutationError, setMutationError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [requirementDirty, setRequirementDirty] = useState(false);
  const reportRequirementDirty = useCallback((dirty) => {
    setRequirementDirty(dirty);
    onRequirementDirtyChange?.(dirty);
  }, [onRequirementDirtyChange]);
  const pending = useRef(false);
  const completedJobs = useRef(new Set());
  const client = identity.clients.find((item) => item.id === project?.client_id);
  const canEdit = identity.capabilities.manage_clients || !!client?.permissions.create_request;
  const permission = { FUNCTIONAL_REVIEWER: 'review_functional', TECHNICAL_REVIEWER: 'review_technical', TESTER: 'test' }[selectedStage?.review_role];
  const canReview = artifact?.gate_status === 'PENDING_REVIEW' && (identity.capabilities.manage_clients || !!client?.permissions[permission]);
  const activeJobs = (Array.isArray(jobs.data) ? jobs.data : jobs.data?.jobs || []).filter((job) => ['QUEUED', 'RUNNING'].includes(job.status));
  const refresh = () => { projectResource.reload(); workflow.reload(); artifactResource.reload(); versions.reload(); validations.reload(); jobs.reload(); packageResource.reload(); inputHistory.reload(); };
  const reloadWorkflow = workflow.reload, reloadArtifacts = artifactResource.reload, reloadProject = projectResource.reload;
  const reloadVersions = versions.reload, reloadValidations = validations.reload;
  useEffect(() => {
    const list = Array.isArray(jobs.data) ? jobs.data : jobs.data?.jobs || [];
    const terminal = list.filter((job) => !['QUEUED', 'RUNNING'].includes(job.status));
    if (terminal.some((job) => !completedJobs.current.has(job.id))) {
      terminal.forEach((job) => completedJobs.current.add(job.id));
      reloadWorkflow(); reloadArtifacts(); reloadProject(); reloadVersions(); reloadValidations();
    }
    if (!activeJobs.length) return;
    const timer = window.setTimeout(jobs.reload, 2000);
    return () => window.clearTimeout(timer);
  }, [jobs.data, activeJobs.length, jobs.reload, reloadWorkflow, reloadArtifacts, reloadProject, reloadVersions, reloadValidations]);
  const routeTo = (nextTab, nextStage = selectedStage?.stage, nextRevision = null) => {
    if (tab === 'requirements' && nextTab !== tab && requirementDirty && !window.confirm('Discard unsaved requirement edits? Save the requirement revision to keep them.')) return;
    if (tab === 'requirements' && nextTab !== tab) reportRequirementDirty(false);
    const query = new URLSearchParams(); query.set('tab', nextTab); if (nextStage) query.set('stage', nextStage); if (nextRevision) query.set('revision', String(nextRevision));
    window.history.pushState({}, '', `${window.location.pathname}?${query}`); setTab(nextTab); setStageId(nextStage || ''); setRevision(nextRevision);
  };
  const generate = async (generationStage = selectedStage) => {
    if (requirementDirty) { setMutationError('Save the requirement revision before generating.'); return; }
    if (!generationStage?.can_generate || !canEdit || pending.current || activeJobs.length) return;
    pending.current = true; setSubmitting(true); setMutationError('');
    try { await requestJson(`${base}/generate`, { method: 'POST', body: JSON.stringify({ stage: generationStage.stage }) }); refresh(); routeTo('workspace', generationStage.stage); }
    catch (cause) { setMutationError(cause.message); }
    finally { pending.current = false; setSubmitting(false); }
  };
  const review = async (decision, number, comments) => {
    if (!artifact || !selectedVersion || !canReview || pending.current || selectedVersion.version_number !== number || artifact.current_version !== number) throw new Error('This revision is unavailable for review.');
    pending.current = true; setReviewing(true); setMutationError('');
    try { await requestJson(`/api/reviews/artifacts/${artifact.id}/versions/${number}/review`, { method: 'POST', body: JSON.stringify({ decision, comments }) }); refresh(); }
    catch (cause) { setMutationError(cause.message); throw cause; }
    finally { pending.current = false; setReviewing(false); }
  };
  const error = mutationError || projectResource.error || workflow.error || artifactResource.error || versions.error || validations.error || jobs.error;
  if (!project) return <div className="page"><div className="workspace-card locked-workspace">{projectResource.loading ? <p role="status">Loading project…</p> : <><h1>Project unavailable</h1><p role="alert">{projectResource.error || 'The selected project is unavailable for your identity.'}</p><button className="btn secondary" onClick={projectResource.reload}>Retry</button><button className="btn ghost" onClick={onHome}>All projects</button></>}</div></div>;
  const approved = stages.filter((stage) => stage.gate_status === 'APPROVED').length;
  return <div className="page studio-page">
    <div className="breadcrumbs"><button className="text-link" onClick={onHome}><ArrowLeft className="icon" />All projects</button><span>/</span><span>Engineering Studio</span></div>
    <div className="studio-heading"><div><div className="eyebrow">{project.client_name} <span>·</span> {label(project.project_type)} INTEGRATION</div><h1>{project.name}</h1><div className="project-facts"><span>{project.erp_name} <b>v{project.erp_version}</b></span><span className="fact-divider" /><span><Clock className="icon" />Due {dateLabel(project.due_date)}</span><span className="fact-divider" /><span>Saved on server</span></div></div><div className="studio-status"><StatusBadge status={project.workflow_status || project.business_status || project.status} /><small>{approved} of {stages.length} configured gates approved</small></div></div>
    {error && <div role="alert" className="notice red">{error}<button className="btn ghost" onClick={refresh}>Retry</button></div>}
    <nav className="stage-strip" aria-label="Project workflow">{[
      { name: 'Requirements', tab: 'requirements', stages: stages.filter((stage) => stage.stage === 'CONTEXT_ANALYSIS') },
      { name: 'FDD', tab: 'workspace', stages: stages.filter((stage) => stage.stage === 'FDD') },
      { name: 'TDD', tab: 'workspace', stages: stages.filter((stage) => stage.stage === 'TDD') },
      { name: 'Deliverable', tab: 'files', stages: stages.filter((stage) => !['CONTEXT_ANALYSIS', 'FDD', 'TDD'].includes(stage.stage)) },
      { name: 'Sandbox', tab: 'sandbox', stages: [], ready: !!packageResource.data?.candidate_id }, { name: 'Release', tab: 'release', stages: [], ready: !!packageResource.data?.candidate_id, approved: !!packageResource.data?.release_id },
    ].map((group, index) => {
      const selected = tab === group.tab && (group.tab !== 'workspace' || group.stages.some((stage) => stage.stage === selectedStage?.stage)) || tab === 'workspace' && ['Requirements', 'Deliverable'].includes(group.name) && group.stages.some((stage) => stage.stage === selectedStage?.stage);
      const approved = group.approved || group.stages.length > 0 && group.stages.every((stage) => stage.gate_status === 'APPROVED');
      const ready = group.ready || group.stages.some((stage) => stage.can_generate && stage.gate_status !== 'APPROVED');
      const locked = index > 0 && !ready && (!group.stages.length || group.stages.every((stage) => stage.gate_status === 'LOCKED'));
      return <button key={group.name} aria-current={selected ? 'step' : undefined} className={`stage-step ${selected ? 'selected' : ''} ${approved ? 'approved' : ''} ${locked ? 'locked' : ''}`} onClick={() => routeTo(group.tab, group.stages[0]?.stage)}><span className="stage-number">{approved ? <Check className="icon" /> : locked ? <Lock className="icon" /> : index + 1}</span><span><strong>{group.name}</strong><small>{approved ? 'Approved' : locked ? 'Locked' : ready && group.stages[0]?.gate_status === 'LOCKED' ? 'Ready' : group.stages[0] ? label(group.stages[0].gate_status) : 'Ready to begin'}</small></span>{index < 5 && <ChevronRight className="icon stage-arrow" />}</button>;
    })}</nav>
    <nav className="studio-tabs" aria-label="Studio workspaces">{[['requirements', 'Requirements'], ['workspace', 'Workspace'], ['history', 'History'], ['sources', 'Source details'], ['files', 'Deliverable files'], ['sandbox', 'Sandbox'], ['release', 'Release']].map(([id, name]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => routeTo(id)}>{name}</button>)}<span className="tab-note"><Lock className="icon" />Human approval at every gate</span></nav>
    {activeJobs.length > 0 && <div className="notice blue" role="status">{activeJobs.map((job) => `${label(job.stage)}: ${label(job.status)}`).join(' · ')}. Generation continues on the server across navigation.</div>}
    {(Array.isArray(jobs.data) ? jobs.data : jobs.data?.jobs || []).filter((job) => ['FAILED', 'STALE'].includes(job.status)).slice(0, 1).map((job) => <div key={job.id} className="notice amber">{label(job.stage)} {label(job.status)} · {job.error_code || 'Review the current inputs before retrying.'}</div>)}
    {tab === 'requirements' && <><RequirementsWorkspace erpProfiles={erpProfiles} key={`${project.id}:${project.requirement_version}`} project={project} canEdit={canEdit} busy={submitting} onDirtyChange={reportRequirementDirty} onSaved={() => { reportRequirementDirty(false); refresh(); }} /><div className="studio-generate-bar"><span>Save the requirement scope, then analyze the exact revision.</span><button className="btn primary" disabled={!canEdit || !stages[0]?.can_generate || submitting || activeJobs.length > 0 || !project.business_requirement?.trim() || requirementDirty} onClick={() => { void generate(stages[0]); }}><Sparkles className="icon" />Analyze requirements</button></div></>}
    {tab === 'workspace' && <><label className="configured-stage-select">Configured engineering stage<select aria-label="Configured engineering stage" value={selectedStage?.stage || ''} onChange={(event) => routeTo('workspace', event.target.value)}>{stages.map((stage) => <option key={stage.stage} value={stage.stage}>{stage.label || label(stage.stage)}</option>)}</select></label><div className="studio-generate-bar"><span>{selectedStage?.gate_status === 'LOCKED' && !selectedStage?.can_generate ? 'This stage is waiting for upstream approval.' : selectedStage?.description || 'Review or generate this configured stage.'}</span><button className="btn primary" disabled={!canEdit || !selectedStage?.can_generate || submitting || activeJobs.length > 0} onClick={() => { void generate(); }}><Sparkles className="icon" />{submitting ? 'Starting…' : `Generate ${selectedStage?.label || label(selectedStage?.stage)}`}</button></div><BottomCards key={artifact?.id || selectedStage?.stage || 'empty'} artifact={artifact} versions={versions.data || []} selectedVersion={selectedVersion} onSelectVersion={(number) => routeTo('workspace', selectedStage.stage, number)} validations={validations.data || []} canReview={canReview} isReviewing={reviewing} approvalBlockers={selectedStage?.approval_blockers || []} onApprove={(number) => review('APPROVED', number, 'Approved by the authenticated reviewer.')} onRequestChanges={(number, _actor, comments) => review('REQUEST_CHANGES', number, comments)} onReject={(number, _actor, comments) => review('REJECTED', number, comments)} onOpenDiff={() => setShowDiff(true)} /></>}
    {tab === 'history' && <section className="workspace-card"><h2>Artifact revision history</h2><p className="input-note">Select a stage above, then browse its saved revisions. Historical content is read only.</p><div className="history-list">{(versions.data || []).map((version) => <button className="history-row" key={version.id || version.version_number} onClick={() => routeTo('workspace', selectedStage.stage, version.version_number)}><strong>{selectedStage?.label || label(selectedStage?.stage)} v{version.version_number}</strong><span>{label(version.state)}</span><small>{dateLabel(version.generated_at)}</small></button>)}{!versions.loading && !versions.data?.length && <p>No revisions have been generated for this stage.</p>}</div><h3>Requirement and context history</h3>{inputHistory.error && <p role="alert">{inputHistory.error}</p>}{(inputHistory.data || []).map((item) => <details key={item.id} className="package-manifest"><summary>Input revision {item.revision} · {dateLabel(item.created_at)}</summary><pre className="provenance-json">{JSON.stringify(item.snapshot, null, 2)}</pre></details>)}</section>}
    {tab === 'sources' && <TraceabilityCard projectId={project.id} />}
    {tab === 'files' && <DeploymentPackageView projectId={project.id} workflowStages={stages} identity={identity} clientId={project.client_id} />}
    {tab === 'sandbox' && <><QualificationWorkspace project={project} identity={identity} onChanged={refresh} /><ConnectionSettings clientId={project.client_id} installationId={project.erp_installation_id} environmentId={project.erp_environment_id} identity={identity} /><SandboxWorkspace project={project} identity={identity} onChanged={refresh} /><button className="btn secondary" onClick={onConnections}>Manage client environments</button></>}
    {tab === 'release' && <><QualificationWorkspace project={project} identity={identity} onChanged={refresh} /><SandboxWorkspace project={project} identity={identity} mode="release" onChanged={refresh} /></>}
    {showDiff && artifact && <DiffViewer artifact={artifact} versions={versions.data || []} onClose={() => setShowDiff(false)} />}
  </div>;
}
