import React from 'react';
import {
  FileOutput,
  CheckCircle, 
  Clock, 
  Lock, 
  AlertTriangle,
  RefreshCw,
  Cpu,
} from 'lucide-react';

export default function PipelineOverviewCard({
  artifacts = [],
  stages: workflowStages = [],
  activeProject,
  validations = [],
  selectedVersion,
  selectedStage,
  onSelectStage,
  isGenerating,
}) {
  const getArtifact = (type) => artifacts.find((a) => a.artifact_type === type);

  const stages = workflowStages.map((stage, index) => ({
    type: stage.stage,
    gate: `Gate ${index + 1}`,
    label: stage.label || stage.stage.replaceAll('_', ' '),
    desc: stage.depends_on?.length ? `Requires approval of ${stage.depends_on.join(', ')}` : 'First configured stage',
  }));
  const stageStatusByType = new Map(workflowStages.map((stage) => [stage.stage, stage.gate_status]));
  const approvedCount = stages.filter((stage) => {
    const prerequisitesPassed = (workflowStages.find((item) => item.stage === stage.type)?.depends_on || [])
      .every((dependency) => stageStatusByType.get(dependency) === 'APPROVED');
    return prerequisitesPassed && stageStatusByType.get(stage.type) === 'APPROVED';
  }).length;
  const progressPercent = stages.length ? Math.round((approvedCount / stages.length) * 100) : 0;
  const validationState = validations.some((item) => item.status === 'FAIL')
    ? 'Failed'
    : validations.some((item) => item.status === 'WARN')
      ? 'Warnings'
      : validations.length ? 'Passed' : 'Not run';
  const schemaContext = activeProject?.erp_schema_context || {};
  const schemaObjects = schemaContext.entities || schemaContext.tables || schemaContext.objects || [];
  const schemaObjectCount = Array.isArray(schemaObjects) ? schemaObjects.length : 0;
  const schemaFieldCount = Array.isArray(schemaObjects)
    ? schemaObjects.reduce((count, object) => count + (object.columns || object.fields || []).length, 0)
    : 0;

  const getStatusBadge = (status, isCurrentGenerating) => {
    if (isCurrentGenerating) {
      return (
        <span className="badge badge-generating">
          <RefreshCw size={11} className="spin" />
          GENERATING
        </span>
      );
    }
    switch (status) {
      case 'APPROVED':
        return (
          <span className="badge badge-approved">
            <CheckCircle size={11} />
            APPROVED
          </span>
        );
      case 'PENDING_REVIEW':
        return (
          <span className="badge badge-pending">
            <Clock size={11} />
            PENDING REVIEW
          </span>
        );
      case 'INVALIDATED':
        return (
          <span className="badge badge-invalidated">
            <AlertTriangle size={11} />
            INVALIDATED
          </span>
        );
      case 'READY':
        return (
          <span className="badge badge-ready">
            <FileOutput size={11} />
            READY TO GENERATE
          </span>
        );
      default:
        return (
          <span className="badge badge-locked">
            <Lock size={11} />
            LOCKED
          </span>
        );
    }
  };

  return (
    <div className="pipeline-overview" style={{
      display: 'grid',
      gridTemplateColumns: '1fr 310px',
      gap: '16px',
      margin: '16px 24px 0 24px',
    }}>
      {/* Left Card: Configured Stage Gate Architecture & Progression */}
      <div className="hr-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column' }}>
        {/* Top Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h2 style={{ fontSize: '14px', fontWeight: '700', color: '#1e293b' }}>
                Engineering Pipeline & Stage Gate Governance
              </h2>
              <span className="badge badge-approved" style={{ fontSize: '10px' }}>
              {stages.length ? 'Strict Ordering' : 'Configuration required'}
              </span>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
              Upstream gates must be APPROVED before downstream stages unlock. AI proposes; deterministic engines validate; humans govern.
            </p>
          </div>

          {/* Progress Indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Progress: <strong style={{ color: 'var(--hr-orange)' }}>{progressPercent}%</strong> ({approvedCount}/{stages.length})
            </span>
            <div style={{
              width: '90px',
              height: '6px',
              background: '#e2e8f0',
              borderRadius: '3px',
              overflow: 'hidden'
            }}>
              <div style={{
                width: `${progressPercent}%`,
                height: '100%',
                background: 'var(--hr-orange)',
                transition: 'width 0.3s ease',
              }} />
            </div>
          </div>
        </div>

        {/* Configured stage cards */}
        <div className="pipeline-stage-grid" style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.min(Math.max(stages.length, 1), 3)}, minmax(0, 1fr))`,
          gap: '10px',
          flex: 1,
        }}>
          {stages.length === 0 ? (
            <div style={{ gridColumn: '1 / -1', alignSelf: 'center', textAlign: 'center', padding: '24px', color: '#64748b' }}>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                No workflow stages are available for this request
              </div>
              <div style={{ fontSize: '12px', lineHeight: 1.5 }}>
                This request has no resolvable published ERP profile version. Select a published profile for a new request, or upgrade this request before generating.
              </div>
            </div>
          ) : stages.map((stage) => {
            const art = getArtifact(stage.type);
            const workflowStage = workflowStages.find((item) => item.stage === stage.type);
            const prerequisitesPassed = (workflowStage?.depends_on || [])
              .every((dependency) => stageStatusByType.get(dependency) === 'APPROVED');
            const actualStatus = stageStatusByType.get(stage.type) || art?.gate_status || 'LOCKED';
            const canGenerate = workflowStage?.can_generate === true;
            const status = prerequisitesPassed
              ? actualStatus === 'LOCKED' && canGenerate ? 'READY' : actualStatus
              : 'LOCKED';
            const isSelected = selectedStage === stage.type;
            const currentGen = isGenerating && isSelected;

            return (
              <div
                key={stage.type}
                onClick={() => onSelectStage(stage.type)}
                style={{
                  padding: '12px 14px',
                  borderRadius: 'var(--radius-sm)',
                  background: isSelected ? 'var(--hr-orange-subtle)' : '#ffffff',
                  border: isSelected ? '1.5px solid var(--hr-orange)' : '1px solid #e2e8f0',
                  boxShadow: isSelected ? '0 2px 8px rgba(252, 117, 0, 0.15)' : 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '8px',
                }}
              >
                {/* Gate & Status */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '11px', fontWeight: '700', color: isSelected ? 'var(--hr-orange)' : '#64748b' }}>
                    {stage.gate}
                  </span>
                  {getStatusBadge(status, currentGen)}
                </div>

                {/* Title & Icon */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{
                    width: '26px',
                    height: '26px',
                    borderRadius: '4px',
                    background: isSelected ? 'rgba(252, 117, 0, 0.15)' : '#f1f5f9',
                    color: isSelected ? 'var(--hr-orange)' : '#475569',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    <FileOutput size={15} />
                  </div>
                  <div style={{
                    fontSize: '12.5px',
                    fontWeight: '600',
                    color: '#1e293b',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis'
                  }}>
                    {stage.label}
                  </div>
                </div>

                {/* Description */}
                <div style={{
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  lineHeight: '1.3',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden'
                }}>
                  {stage.desc}
                </div>

                {/* Footer: Version */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  paddingTop: '6px',
                  borderTop: '1px solid #f1f5f9',
                  fontSize: '10.5px',
                  color: '#64748b'
                }}>
                  <span>Revision:</span>
                  <span style={{ fontWeight: '700', color: art?.current_version > 0 ? '#0284c7' : '#94a3b8', fontFamily: 'var(--font-mono)' }}>
                    {art?.current_version > 0 ? `v${art.current_version}` : 'None'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right Card: Request health and live configuration */}
      <div className="hr-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 style={{ fontSize: '14px', fontWeight: '700', color: '#1e293b' }}>
            Integration Health
          </h2>
          <span className={`badge ${stages.length ? 'badge-approved' : 'badge-pending'}`} style={{ fontSize: '10px' }}>
            {stages.length ? 'Profile resolved' : 'Needs attention'}
          </span>
        </div>

        {/* Workflow configuration */}
        <div>
          <div style={{ fontSize: '11.5px', color: '#64748b' }}>Configured workflow</div>
          <div style={{ fontSize: '18px', fontWeight: '700', color: stages.length ? '#059669' : '#b45309', marginTop: '2px' }}>
            {stages.length ? `${stages.length} stages` : 'Unavailable'}
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8' }}>{activeProject?.erp_profile_version_id ? 'Pinned ERP profile version' : 'No ERP profile version pinned'}</div>
        </div>

        {/* Schema context supplied for this request */}
        <div>
          <div style={{ fontSize: '11.5px', color: '#64748b' }}>Request schema context</div>
          <div style={{ fontSize: '18px', fontWeight: '700', color: 'var(--hr-orange)', marginTop: '2px' }}>
            {schemaObjectCount} Objects • {schemaFieldCount} Fields
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8' }}>Provided with this integration request</div>
        </div>

        {/* Current artifact validation */}
        <div>
          <div style={{ fontSize: '11.5px', color: '#64748b' }}>Selected artifact validation</div>
          <div style={{ fontSize: '18px', fontWeight: '700', color: validationState === 'Passed' ? '#059669' : validationState === 'Failed' ? '#b91c1c' : '#b45309', marginTop: '2px' }}>
            {validationState}
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8' }}>{selectedVersion ? `Artifact revision v${selectedVersion.version_number}` : 'No generated revision selected'}</div>
        </div>

        {/* Model Spec */}
        <div style={{
          marginTop: 'auto',
          padding: '10px 12px',
          background: '#f8fafc',
          borderRadius: 'var(--radius-xs)',
          border: '1px solid #e2e8f0',
          fontSize: '11px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: '600', color: '#334155' }}>
            <Cpu size={14} color="#0096e6" />
            <span>Generation model</span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', color: '#0284c7', fontSize: '10.5px' }}>
            {selectedVersion?.ai_model_version || 'Shown after generation'}
          </div>
          <div style={{ color: '#64748b', fontSize: '10px' }}>
            Model metadata is recorded with each generated revision
          </div>
        </div>
      </div>
    </div>
  );
}
