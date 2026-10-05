import React from 'react';
import { Play, Plus } from 'lucide-react';

export default function FilterControlBar({
  projects = [],
  activeProject,
  onSelectProject,
  onNewProject,
  selectedStage,
  onGenerate,
  isGenerating,
  canGenerate = true,
  selectionDisabled = false,
  loadingProjects = false,
  projectSearch = '',
  onSearchProjects,
  projectOffset = 0,
  hasNextProjects = false,
  onPreviousProjects,
  onNextProjects,
  erpProfiles = [],
  requestFilters = { erp_profile_id: '', request_status: '' },
  onChangeRequestFilters,
}) {
  return (
    <div
      className="filter-control-bar"
      style={{
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '8px',
        padding: '10px 18px',
        margin: '16px 24px 0 24px',
        boxShadow: '0 2px 8px -1px rgba(0, 0, 0, 0.05)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        flexWrap: 'wrap',
      }}
    >
      {/* 1. Project Selector & New Project */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flexWrap: 'wrap' }}>
        {onSearchProjects && <input type="search" aria-label="Search integration requests" placeholder="Search requests" value={projectSearch} maxLength={255} disabled={selectionDisabled} onChange={(event) => onSearchProjects(event.target.value)} style={{ width: 160, padding: '6px 10px', border: '1px solid #cbd5e1', borderRadius: 6 }} />}
        <select
          aria-label="Integration request"
          disabled={selectionDisabled || loadingProjects || !projects.length}
          value={activeProject?.id || ''}
          onChange={(e) => onSelectProject && onSelectProject(e.target.value)}
          style={{
            width: 'min(300px, 100%)',
            maxWidth: '100%',
            fontSize: '13px',
            padding: '6px 12px',
            border: '1px solid #cbd5e1',
            borderRadius: '6px',
            background: '#ffffff',
            color: '#1e293b',
            outline: 'none',
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {!projects.length && <option value="">{loadingProjects ? 'Loading requests…' : 'No requests match'}</option>}
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        {onChangeRequestFilters && <>
          <select aria-label="Filter requests by ERP" value={requestFilters.erp_profile_id} disabled={selectionDisabled}
            onChange={(event) => onChangeRequestFilters({ ...requestFilters, erp_profile_id: event.target.value })}
            style={{ maxWidth: 180, padding: '6px 10px', border: '1px solid #cbd5e1', borderRadius: 6 }}>
            <option value="">All ERPs</option>
            {Array.from(new Map(erpProfiles.map((profile) => [profile.id, profile])).values()).map((profile) => <option key={profile.id} value={profile.id}>{profile.display_name || profile.name}</option>)}
          </select>
          <select aria-label="Filter requests by status" value={requestFilters.request_status} disabled={selectionDisabled}
            onChange={(event) => onChangeRequestFilters({ ...requestFilters, request_status: event.target.value })}
            style={{ padding: '6px 10px', border: '1px solid #cbd5e1', borderRadius: 6 }}>
            <option value="">All active records</option><option value="ACTIVE">In progress</option><option value="COMPLETED">Completed</option>
          </select>
        </>}
        {onPreviousProjects && <button className="btn btn-secondary" aria-label="Previous integration requests" disabled={selectionDisabled || loadingProjects || projectOffset === 0} onClick={onPreviousProjects}>‹</button>}
        {onNextProjects && <button className="btn btn-secondary" aria-label="Next integration requests" disabled={selectionDisabled || loadingProjects || !hasNextProjects} onClick={onNextProjects}>›</button>}
        {onNewProject && (
          <button
            onClick={onNewProject}
            disabled={selectionDisabled}
            title="Create new integration project"
            style={{
              padding: '6px 10px',
              fontSize: '12px',
              fontWeight: 600,
              background: '#f8fafc',
              color: '#334155',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              transition: 'all 0.15s ease',
            }}
          >
            <Plus size={13} />
            <span>New</span>
          </button>
        )}
      </div>

      {/* 2. Active Stage Label */}
      <span style={{ fontSize: '12px', color: '#64748b' }}>
        Active Stage: <strong style={{ color: selectedStage ? '#1e293b' : '#b45309', fontWeight: 600 }}>
          {selectedStage ? selectedStage.replaceAll('_', ' ') : 'Not configured'}
        </strong>
      </span>

      {/* 3. Generate Button */}
      <button
        onClick={onGenerate}
        disabled={isGenerating || !canGenerate}
        title={!selectedStage ? 'No workflow stage is available for this request' : !canGenerate ? 'Upstream stage must be APPROVED first' : 'Generate artifact with AI'}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          background: !canGenerate ? '#94a3b8' : '#fc7500',
          color: '#ffffff',
          border: 'none',
          borderRadius: '6px',
          padding: '6px 16px',
          fontSize: '13px',
          fontWeight: 600,
          cursor: isGenerating || !canGenerate ? 'not-allowed' : 'pointer',
          opacity: isGenerating ? 0.7 : 1,
          fontFamily: 'inherit',
          transition: 'all 0.15s ease',
        }}
      >
        <Play size={14} fill="#ffffff" />
        <span>{isGenerating ? 'Generating...' : 'Generate'}</span>
      </button>
    </div>
  );
}
