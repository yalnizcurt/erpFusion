import React, { useState } from 'react';
import {
  Copy,
  Check,
  CheckCircle2,
  XCircle,
  RotateCcw,
  CheckCircle,
  BarChart2,
  FileDown,
  GitCompare,
} from 'lucide-react';
import { openArtifactAsPdf } from '../utils/generatePdf';

export default function BottomCards({
  artifact,
  versions = [],
  selectedVersion,
  onSelectVersion,
  validations = [],
  onApprove,
  onRequestChanges,
  onReject,
  onOpenDiff,
}) {
  const [activeTab, setActiveTab] = useState('doc');
  const [copied, setCopied] = useState(false);
  const [showChangesModal, setShowChangesModal] = useState(false);
  const [reviewComments, setReviewComments] = useState('');

  const content = selectedVersion?.content || {};
  const isPendingReview = selectedVersion?.state === 'PENDING_HUMAN_REVIEW';
  const metadata = selectedVersion?.input_context_snapshot || {};
  const validationState = validations.some((v) => v.status === 'FAIL') ? 'FAIL' : validations.some((v) => v.status === 'WARN') ? 'WARN' : validations.length ? 'PASS' : 'NOT RUN';

  const copyCode = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApprove = () => {
    if (window.confirm(`Approve ${artifact?.artifact_type} v${selectedVersion?.version_number}? This will advance the workflow gate.`)) {
      onApprove(selectedVersion?.version_number, 'Lead Architect');
    }
  };

  const handleRequestChanges = () => {
    if (!reviewComments.trim()) {
      alert('Please enter your feedback comments for the requested change.');
      return;
    }
    onRequestChanges(selectedVersion?.version_number, 'Lead Architect', reviewComments);
    setShowChangesModal(false);
    setReviewComments('');
  };

  const handleReject = () => {
    const reason = prompt('Please enter the reason for rejection:');
    if (reason) {
      onReject(selectedVersion?.version_number, 'Lead Architect', reason);
    }
  };

  return (
    <div className="bottom-cards-grid" style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
      gap: '16px',
      margin: '16px 24px 24px 24px',
    }}>
      {/* Left Card: Artifact Studio */}
      <div className="hr-card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: '700', color: '#1e293b' }}>
              Artifact Studio
            </h3>
            <span style={{ fontSize: '12px', color: '#64748b' }}>
              — Stage: {artifact?.artifact_type?.replace('_', ' ') || 'Context Analysis'}
            </span>
            {versions && versions.length > 0 && (
              <select
                aria-label="Select artifact version"
                value={selectedVersion?.version_number || ''}
                onChange={(e) => onSelectVersion && onSelectVersion(Number(e.target.value))}
                style={{
                  padding: '2px 8px',
                  fontSize: '11px',
                  fontWeight: '600',
                  borderRadius: '4px',
                  border: '1px solid #cbd5e1',
                  background: '#f8fafc',
                  color: '#1e293b',
                  cursor: 'pointer',
                  marginLeft: '4px',
                  outline: 'none',
                }}
              >
                {versions.map((v) => (
                  <option key={v.id || v.version_number} value={v.version_number}>
                    v{v.version_number} ({v.state})
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Sub-tabs + Action Buttons */}
          <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <button
              onClick={() => setActiveTab('doc')}
              style={{
                padding: '3px 8px',
                fontSize: '11px',
                fontWeight: activeTab === 'doc' ? '600' : '500',
                background: activeTab === 'doc' ? 'var(--hr-orange-subtle)' : 'transparent',
                color: activeTab === 'doc' ? 'var(--hr-orange)' : '#64748b',
                border: activeTab === 'doc' ? '1px solid var(--hr-orange-border)' : '1px solid transparent',
                borderRadius: '3px',
                cursor: 'pointer',
              }}
            >
              Document
            </button>
            <button
              onClick={() => setActiveTab('code')}
              style={{
                padding: '3px 8px',
                fontSize: '11px',
                fontWeight: activeTab === 'code' ? '600' : '500',
                background: activeTab === 'code' ? 'var(--hr-orange-subtle)' : 'transparent',
                color: activeTab === 'code' ? 'var(--hr-orange)' : '#64748b',
                border: activeTab === 'code' ? '1px solid var(--hr-orange-border)' : '1px solid transparent',
                borderRadius: '3px',
                cursor: 'pointer',
              }}
            >
              SQL / Code
            </button>
            <button
              onClick={() => setActiveTab('json')}
              style={{
                padding: '3px 8px',
                fontSize: '11px',
                fontWeight: activeTab === 'json' ? '600' : '500',
                background: activeTab === 'json' ? 'var(--hr-orange-subtle)' : 'transparent',
                color: activeTab === 'json' ? 'var(--hr-orange)' : '#64748b',
                border: activeTab === 'json' ? '1px solid var(--hr-orange-border)' : '1px solid transparent',
                borderRadius: '3px',
                cursor: 'pointer',
              }}
            >
              JSON
            </button>

            {/* Separator */}
            <div style={{ width: '1px', height: '18px', background: '#e2e8f0', margin: '0 4px' }} />

            {/* View as PDF Button */}
            <button
              onClick={() => artifact && selectedVersion && openArtifactAsPdf(artifact, selectedVersion)}
              disabled={!selectedVersion}
              title="Open document as PDF in new tab"
              style={{
                padding: '3px 10px',
                fontSize: '11px',
                fontWeight: '600',
                background: selectedVersion ? 'var(--hr-blue-primary)' : '#e2e8f0',
                color: selectedVersion ? '#ffffff' : '#94a3b8',
                border: 'none',
                borderRadius: '3px',
                cursor: selectedVersion ? 'pointer' : 'not-allowed',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.15s ease',
              }}
            >
              <FileDown size={12} />
              View as PDF
            </button>

            {/* Diff Button (moved here from FilterControlBar) */}
            {versions.length > 1 && (
              <button
                onClick={onOpenDiff}
                title="Compare version changes"
                style={{
                  padding: '3px 8px',
                  fontSize: '11px',
                  fontWeight: '500',
                  background: 'transparent',
                  color: '#64748b',
                  border: '1px solid #e2e8f0',
                  borderRadius: '3px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '3px',
                }}
              >
                <GitCompare size={12} />
                Diff
              </button>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, maxHeight: '340px', overflowY: 'auto', overflowX: 'hidden' }}>
          {selectedVersion ? (
            activeTab === 'doc' ? (
              <div style={{ fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {/* Stage Title */}
                <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: '4px', border: '1px solid #e2e8f0' }}>
                  <strong>{content.document_title || content.business_objective || artifact?.artifact_type}</strong>
                </div>

                {/* Table for FDD Attribute Mappings */}
                {content.attribute_mappings && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11.5px', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #cbd5e1', color: '#64748b' }}>
                        <th style={{ padding: '6px 8px' }}>Attribute</th>
                        <th style={{ padding: '6px 8px' }}>ERP Table</th>
                        <th style={{ padding: '6px 8px' }}>Column</th>
                        <th style={{ padding: '6px 8px' }}>Transformation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {content.attribute_mappings.map((m, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 8px', fontWeight: '500' }}>{m.business_attribute}</td>
                          <td style={{ padding: '6px 8px', color: '#0284c7', fontFamily: 'var(--font-mono)' }}>{m.source_table}</td>
                          <td style={{ padding: '6px 8px', color: '#334155', fontFamily: 'var(--font-mono)' }}>{m.source_column}</td>
                          <td style={{ padding: '6px 8px', color: '#059669', fontSize: '10.5px' }}>{m.transformation || 'Direct'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {/* Table for Context Analysis Identified Entities */}
                {content.identified_entities && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11.5px', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #cbd5e1', color: '#64748b' }}>
                        <th style={{ padding: '6px 8px' }}>Entity</th>
                        <th style={{ padding: '6px 8px' }}>ERP Table</th>
                        <th style={{ padding: '6px 8px' }}>Role</th>
                        <th style={{ padding: '6px 8px' }}>Columns</th>
                      </tr>
                    </thead>
                    <tbody>
                      {content.identified_entities.map((ent, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 8px', fontWeight: '500' }}>{ent.business_name}</td>
                          <td style={{ padding: '6px 8px', color: '#0284c7', fontFamily: 'var(--font-mono)' }}>{ent.erp_table}</td>
                          <td style={{ padding: '6px 8px' }}>
                            <span className="badge badge-locked">{ent.role}</span>
                          </td>
                          <td style={{ padding: '6px 8px', color: '#64748b' }}>
                            {ent.relevant_columns?.map((c) => c.column_name).join(', ')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {/* SQL Extraction query preview */}
                {content.extraction_sql && (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontWeight: '600', color: '#334155' }}>Generated SQL</span>
                      <button
                        onClick={() => copyCode(content.extraction_sql)}
                        style={{ background: 'none', border: 'none', color: '#0284c7', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                      >
                        {copied ? <Check size={12} color="#059669" /> : <Copy size={12} />}
                        <span>{copied ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                    <pre className="code-container" style={{ maxHeight: '180px', fontSize: '11px' }}>
                      {content.extraction_sql}
                    </pre>
                  </div>
                )}

                {/* PL/SQL package preview */}
                {content.pks_content && (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontWeight: '600', color: '#334155' }}>Package Specification (.pks)</span>
                      <button
                        onClick={() => copyCode(content.pks_content)}
                        style={{ background: 'none', border: 'none', color: '#0284c7', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                      >
                        {copied ? <Check size={12} color="#059669" /> : <Copy size={12} />}
                        <span>{copied ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                    <pre className="code-container" style={{ maxHeight: '180px', fontSize: '11px' }}>
                      {content.pks_content}
                    </pre>
                  </div>
                )}
              </div>
            ) : activeTab === 'code' ? (
              <pre className="code-container" style={{ maxHeight: '320px', fontSize: '11px' }}>
                {content.extraction_sql || content.pks_content || content.pkb_content || JSON.stringify(content, null, 2)}
              </pre>
            ) : (
              <pre className="code-container" style={{ maxHeight: '320px', maxWidth: '100%', boxSizing: 'border-box', overflow: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '11px' }}>
                {JSON.stringify(content, null, 2)}
              </pre>
            )
          ) : (
            <div style={{ textAlign: 'center', padding: '50px 20px', color: '#94a3b8', fontSize: '13px' }}>
              <BarChart2 size={24} style={{ margin: '0 auto 8px', opacity: 0.5 }} />
              <div>Stage artifact not yet generated.</div>
              <div style={{ fontSize: '11px', marginTop: '4px' }}>Click "Generate" above to trigger AI generation.</div>
            </div>
          )}
        </div>
      </div>

      {/* Right Card: Deterministic Validation Engine */}
      <div className="hr-card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: '700', color: '#1e293b' }}>
              Deterministic Validation Engine
            </h3>
            <span style={{ fontSize: '12px', color: '#64748b' }}>
              — Pre-Execution Governance
            </span>
          </div>

          {/* Validation Status Badge */}
          <span className={`badge ${validationState === 'PASS' ? 'badge-approved' : validationState === 'FAIL' ? 'badge-invalidated' : 'badge-pending'}`} style={{ fontSize: '11px' }}>
            <CheckCircle size={12} />
            Validation {validationState}
          </span>
        </div>

        {/* Validation Checks List */}
        <div style={{ flex: 1, maxHeight: '280px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {validations.length > 0 ? (
            validations.map((v, i) => (
              <div
                key={i}
                style={{
                  padding: '10px 12px',
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '4px',
                  fontSize: '12px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <strong style={{ color: '#1e293b' }}>
                    {v.category === 'SCHEMA' && '✓ Schema Conformity & Hallucination Guard'}
                    {v.category === 'SQL' && 'SQL validation'}
                    {v.category === 'PLSQL' && 'Code validation'}
                    {v.category === 'CROSS_ARTIFACT' && 'Cross-artifact traceability'}
                    {!['SCHEMA', 'SQL', 'PLSQL', 'CROSS_ARTIFACT'].includes(v.category) && v.category}
                  </strong>
                  <span className={`badge ${v.status === 'FAIL' ? 'badge-invalidated' : v.status === 'WARN' ? 'badge-pending' : 'badge-approved'}`} style={{ fontSize: '10px' }}>
                    {v.status}
                  </span>
                </div>
                {v.checks?.map((chk, ci) => (
                  <div key={ci} style={{ color: '#475569', fontSize: '11px', marginTop: '2px' }}>
                    • {chk.message}
                  </div>
                ))}
              </div>
            ))
          ) : (
            <div style={{
              padding: '12px',
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '4px',
              fontSize: '12px',
              color: '#64748b'
            }}>
              <div style={{ fontWeight: '600', color: '#334155', marginBottom: '4px' }}>
                Pre-Execution Verification Active
              </div>
              <div>• Validation rules are resolved from the request’s pinned ERP profile version.</div>
              <div>• Downstream stages remain locked until required approvals are complete.</div>
            </div>
          )}
        </div>

        {/* Human Review Decision Buttons Footer */}
        {isPendingReview && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '8px',
            paddingTop: '12px',
            borderTop: '1px solid var(--border-light)',
            marginTop: '8px'
          }}>
            <button
              onClick={handleApprove}
              className="btn btn-success"
              style={{ padding: '6px 12px', fontSize: '12px' }}
            >
              <CheckCircle2 size={14} />
              <span>Approve Gate</span>
            </button>
            <button
              onClick={() => setShowChangesModal(true)}
              className="btn btn-warning"
              style={{ padding: '6px 12px', fontSize: '12px' }}
            >
              <RotateCcw size={14} />
              <span>Request Changes</span>
            </button>
            <button
              onClick={handleReject}
              className="btn btn-danger"
              style={{ padding: '6px 12px', fontSize: '12px' }}
            >
              <XCircle size={14} />
              <span>Reject</span>
            </button>
          </div>
        )}
      </div>

      <details style={{ gridColumn: '1 / -1', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '12px 16px' }}>
        <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 650 }}>Why was this generated this way? <span style={{ fontWeight: 400, color: '#64748b' }}>Inspect configuration and source provenance</span></summary>
        {selectedVersion ? <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12, fontSize: 12 }}>
          <div><b>ERP profile</b><pre style={{ whiteSpace: 'pre-wrap', color: '#475569' }}>{JSON.stringify(metadata.erp_profile || {}, null, 2)}</pre></div>
          <div><b>Prompt versions</b><pre style={{ whiteSpace: 'pre-wrap', color: '#475569' }}>{JSON.stringify(metadata.prompt_versions || [], null, 2)}</pre></div>
          <div><b>Knowledge and standard packages</b><pre style={{ whiteSpace: 'pre-wrap', color: '#475569' }}>{JSON.stringify({ knowledge: metadata.knowledge_asset_versions || [], packages: metadata.standard_package_versions || [] }, null, 2)}</pre></div>
          <div><b>Feedback and upstream references</b><pre style={{ whiteSpace: 'pre-wrap', color: '#475569' }}>{JSON.stringify({ feedback: metadata.feedback_versions || [], upstream: metadata.upstream_artifacts || {} }, null, 2)}</pre></div>
        </div> : <p style={{ marginTop: 10, color: '#64748b', fontSize: 12 }}>Generation provenance is available after an artifact is generated.</p>}
      </details>

      {/* Changes Request Modal */}
      {showChangesModal && (
        <div className="hr-modal-overlay">
          <div className="hr-modal-content" style={{ width: '500px', padding: '20px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '6px' }}>
              Request Changes on {artifact?.artifact_type} v{selectedVersion?.version_number}
            </h3>
            <p style={{ fontSize: '12px', color: '#475569', marginBottom: '12px' }}>
              Specify the exact adjustments required for the next AI generation cycle.
            </p>
            <textarea
              rows={4}
              value={reviewComments}
              onChange={(e) => setReviewComments(e.target.value)}
              placeholder="e.g. Ensure all supplier names have newlines sanitized, and verify the delta query uses LAST_UPDATE_DATE."
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '4px',
                border: '1px solid #cbd5e1',
                fontSize: '12px',
                outline: 'none',
                fontFamily: 'inherit',
                marginBottom: '14px'
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => setShowChangesModal(false)} className="btn btn-secondary">
                Cancel
              </button>
              <button onClick={handleRequestChanges} className="btn btn-warning">
                Submit Change Request
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
