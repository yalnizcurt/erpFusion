import React, { useState, useEffect, useCallback } from 'react';
import { GitCompare, X, ArrowRight, RefreshCw } from 'lucide-react';
import { apiUrl } from '../api';

export default function DiffViewer({ artifact, versions, onClose }) {
  const sortedVersions = [...versions].sort((a, b) => b.version_number - a.version_number);
  const [v1, setV1] = useState(sortedVersions.length > 1 ? sortedVersions[1].version_number : 1);
  const [v2, setV2] = useState(sortedVersions.length > 0 ? sortedVersions[0].version_number : 1);
  const [diffData, setDiffData] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadDiff = useCallback(async () => {
    if (!artifact?.id || !v1 || !v2 || v1 === v2) return;
    setLoading(true);
    try {
      const res = await fetch(apiUrl(`/api/artifacts/${artifact.id}/diff?v1=${v1}&v2=${v2}`));
      if (res.ok) {
        const data = await res.json();
        setDiffData(data);
      }
    } catch (e) {
      console.error('Failed to load diff', e);
    } finally {
      setLoading(false);
    }
  }, [artifact?.id, v1, v2]);

  useEffect(() => {
    if (artifact && v1 && v2 && v1 !== v2) {
      loadDiff();
    }
  }, [artifact, v1, v2, loadDiff]);

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(15, 23, 42, 0.45)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 200,
      padding: '24px'
    }}>
      <div style={{
        background: '#ffffff',
        borderRadius: '8px',
        border: '1px solid #e2e8f0',
        boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
        width: '900px',
        maxHeight: '85vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          borderBottom: '1px solid #e2e8f0',
          background: '#f8fafc'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <GitCompare size={18} color="#0096e6" />
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#1e293b' }}>
              Version Diff Inspector — {artifact?.artifact_type}
            </h3>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            {/* Version selectors */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
              <span style={{ color: '#475569' }}>Base:</span>
              <select
                value={v1}
                onChange={(e) => setV1(Number(e.target.value))}
                style={{
                  background: '#ffffff',
                  color: '#1e293b',
                  border: '1px solid #cbd5e1',
                  borderRadius: '4px',
                  padding: '4px 8px',
                  fontSize: '12px'
                }}
              >
                {sortedVersions.map((v) => (
                  <option key={v.id} value={v.version_number}>
                    v{v.version_number} ({v.state})
                  </option>
                ))}
              </select>
              <ArrowRight size={14} color="#64748b" />
              <span style={{ color: '#475569' }}>Target:</span>
              <select
                value={v2}
                onChange={(e) => setV2(Number(e.target.value))}
                style={{
                  background: '#ffffff',
                  color: '#1e293b',
                  border: '1px solid #cbd5e1',
                  borderRadius: '4px',
                  padding: '4px 8px',
                  fontSize: '12px'
                }}
              >
                {sortedVersions.map((v) => (
                  <option key={v.id} value={v.version_number}>
                    v{v.version_number} ({v.state})
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: '#64748b',
                cursor: 'pointer',
                padding: '4px'
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Diff Content Box */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px', gap: '8px', color: '#64748b' }}>
              <RefreshCw size={18} className="spin" />
              <span>Computing unified diff...</span>
            </div>
          ) : v1 === v2 ? (
            <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
              Select two different versions to compare changes.
            </div>
          ) : diffData?.diff_text ? (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', fontSize: '12px', color: '#475569' }}>
                <span className="badge badge-approved">{diffData.changes_count} Lines Changed</span>
                <span>Comparing v{v1} against v{v2}</span>
              </div>
              <pre className="code-container" style={{ maxHeight: '55vh', fontSize: '12px' }}>
                {diffData.diff_text.split('\n').map((line, idx) => {
                  let cls = 'diff-line-neutral';
                  if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-line-added';
                  else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-line-removed';
                  return (
                    <span key={idx} className={cls}>
                      {line}
                    </span>
                  );
                })}
              </pre>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
              No differences found between v{v1} and v{v2}.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
