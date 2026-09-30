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
      }}
    >
      {/* 1. Project Selector & New Project */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <select
          value={activeProject?.id || ''}
          onChange={(e) => onSelectProject && onSelectProject(e.target.value)}
          style={{
            minWidth: '250px',
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
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        {onNewProject && (
          <button
            onClick={onNewProject}
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
