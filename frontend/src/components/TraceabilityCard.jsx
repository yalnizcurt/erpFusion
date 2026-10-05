import React from 'react';
import { Network, CheckCircle, XCircle, RefreshCw, ShieldCheck } from 'lucide-react';
import { useApiResource } from '../hooks/useApiResource';

export default function TraceabilityCard({ projectId }) {
  const { data, loading, error, reload } = useApiResource(projectId ? `/api/projects/${projectId}/traceability` : null);

  return (
    <div className="hr-card" style={{ margin: '16px 24px', padding: '20px 24px' }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingBottom: '16px',
        borderBottom: '1px solid var(--border-light)',
        marginBottom: '16px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '6px',
            background: 'var(--hr-orange-subtle)',
            color: 'var(--hr-orange)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Network size={18} />
          </div>
          <div>
            <h2 style={{ fontSize: '15px', fontWeight: '700', color: '#1e293b' }}>
              Artifact Dependency Traceability
            </h2>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
              Tracks configured stage dependencies, versions, and approval gates for this request
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {data && data.coverage_pct !== undefined && (
          <span className="badge badge-approved" style={{ fontSize: '12px', padding: '4px 10px' }}>
              <ShieldCheck size={13} />
              {data.coverage_pct}% Lineage Coverage ({data.traced_attributes}/{data.total_attributes} Attributes)
            </span>
          )}
          <button
            onClick={reload}
            disabled={loading}
            className="btn btn-secondary"
            style={{ padding: '5px 12px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} />
            <span>Refresh Lineage</span>
          </button>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '60px 0', gap: '10px', color: '#64748b' }}>
          <RefreshCw size={20} className="spin" color="var(--hr-orange)" />
          <span style={{ fontSize: '13px' }}>Loading configured stage lineage…</span>
        </div>
      ) : error ? <div role="alert" style={{ padding: 24, color: '#991b1b' }}>{error}</div> : data?.kind === 'WORKFLOW' && data.matrix?.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12.5px', textAlign: 'left' }}>
            <thead><tr style={{ borderBottom: '1px solid #cbd5e1', background: '#f8fafc', color: '#475569' }}>
              <th style={{ padding: '10px 14px' }}>Configured stage</th>
              <th style={{ padding: '10px 14px' }}>Depends on</th>
              <th style={{ padding: '10px 14px' }}>Approval gate</th>
              <th style={{ padding: '10px 14px' }}>Current version</th>
            </tr></thead>
            <tbody>{data.matrix.map((row, index) => <tr key={row.stage} style={{ borderBottom: '1px solid #f1f5f9', background: index % 2 ? '#fafafa' : '#fff' }}>
              <td style={{ padding: '11px 14px', fontWeight: 600 }}>{row.label}</td>
              <td style={{ padding: '11px 14px', color: '#475569' }}>{row.depends_on?.length ? row.depends_on.join(', ') : 'Request inputs'}</td>
              <td style={{ padding: '11px 14px' }}><span className={`badge ${row.status === 'APPROVED' ? 'badge-approved' : row.status === 'LOCKED' ? 'badge-locked' : 'badge-pending'}`}>{row.status}</span></td>
              <td style={{ padding: '11px 14px' }}>{row.version || '—'}</td>
            </tr>)}</tbody>
          </table>
        </div>
      ) : data?.matrix && data.matrix.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: '12.5px',
            textAlign: 'left'
          }}>
            <thead>
              <tr style={{
                borderBottom: '1px solid #cbd5e1',
                background: '#f8fafc',
                color: '#475569',
                fontWeight: '600'
              }}>
                <th style={{ padding: '10px 14px' }}>Business Attribute</th>
                <th style={{ padding: '10px 14px' }}>Functional Design</th>
                <th style={{ padding: '10px 14px' }}>Technical Design</th>
                <th style={{ padding: '10px 14px' }}>Generated Query</th>
                <th style={{ padding: '10px 14px' }}>Traceability Status</th>
              </tr>
            </thead>
            <tbody>
              {data.matrix.map((row, idx) => (
                <tr
                  key={idx}
                  style={{
                    borderBottom: '1px solid #f1f5f9',
                    background: idx % 2 === 0 ? '#ffffff' : '#fafafa'
                  }}
                >
                  <td style={{ padding: '11px 14px', fontWeight: '600', color: '#1e293b' }}>
                    {row.attribute}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {row.in_fdd ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#059669', fontSize: '11.5px', fontWeight: '500' }}>
                        <CheckCircle size={15} color="#059669" /> Yes
                      </span>
                    ) : (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#ef4444', fontSize: '11.5px' }}>
                        <XCircle size={15} color="#ef4444" /> Missing
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {row.in_tdd ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#059669', fontSize: '11.5px', fontWeight: '500' }}>
                        <CheckCircle size={15} color="#059669" /> Yes
                      </span>
                    ) : (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#ef4444', fontSize: '11.5px' }}>
                        <XCircle size={15} color="#ef4444" /> Missing
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {row.in_sql ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#059669', fontSize: '11.5px', fontWeight: '500' }}>
                        <CheckCircle size={15} color="#059669" /> Yes
                      </span>
                    ) : (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#ef4444', fontSize: '11.5px' }}>
                        <XCircle size={15} color="#ef4444" /> Missing
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    {row.status === 'FULL' && (
                      <span className="badge badge-approved">Complete Lineage</span>
                    )}
                    {row.status === 'PARTIAL' && (
                      <span className="badge badge-pending">Partial</span>
                    )}
                    {row.status === 'MISSING' && (
                      <span className="badge badge-invalidated">Missing Downstream</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: '50px 20px', color: '#94a3b8' }}>
          <Network size={28} style={{ margin: '0 auto 10px', opacity: 0.4 }} />
          <div style={{ fontSize: '14px', fontWeight: '600', color: '#64748b' }}>
            No Traceability Data Available
          </div>
          <p style={{ fontSize: '12px', marginTop: '6px' }}>
            {data?.message || 'Generate artifacts to see configured workflow dependencies and lineage.'}
          </p>
        </div>
      )}
    </div>
  );
}
