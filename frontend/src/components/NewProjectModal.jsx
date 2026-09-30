import React, { useState } from 'react';
import { X, Plus, Sparkles } from 'lucide-react';

function profileOptionLabel(profile) {
  const name = profile.display_name || profile.name || 'ERP profile';
  const versionLabel = profile.version_label?.trim();
  const nameAlreadyIncludesVersion = versionLabel && name.toLocaleLowerCase().endsWith(versionLabel.toLocaleLowerCase());
  const profileName = versionLabel && !nameAlreadyIncludesVersion ? `${name} ${versionLabel}` : name;
  return `${profileName} · Profile v${profile.profile_version}`;
}

export default function NewProjectModal({ onClose, onCreateProject, erpProfiles = [] }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [erpProfileVersionId, setErpProfileVersionId] = useState('');
  const [requirement, setRequirement] = useState('');
  const [schemaJson, setSchemaJson] = useState('{\n  "entities": []\n}');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const selectedProfileVersionId = erpProfileVersionId || erpProfiles[0]?.profile_version_id || '';

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !requirement.trim()) {
      setError('Please provide both a project name and business requirement.');
      return;
    }

    let parsedSchema = {};
    try {
      parsedSchema = JSON.parse(schemaJson);
    } catch (err) {
      setError('Invalid ERP context JSON format: ' + err.message);
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onCreateProject({
        name,
        description,
        business_requirement: requirement,
        erp_schema_context: parsedSchema,
        erp_profile_version_id: selectedProfileVersionId || null,
      });
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to create project');
    } finally {
      setSubmitting(false);
    }
  };

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
        width: '750px',
        maxHeight: '90vh',
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={18} color="#fc7500" />
            <h3 style={{ fontSize: '15px', fontWeight: '600', color: '#1e293b' }}>Create New ERP Integration Project</h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', padding: '4px' }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} style={{ padding: '20px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {error && (
            <div style={{
              padding: '10px 14px',
              borderRadius: '6px',
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#dc2626',
              fontSize: '13px'
            }}>
              {error}
            </div>
          )}

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: '#334155' }}>
              Project Name *
            </label>
            <input
              type="text"
              id="new-project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Supplier Invoice Integration"
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                background: '#ffffff',
                border: '1px solid #cbd5e1',
                color: '#1e293b',
                fontSize: '13px',
                outline: 'none'
              }}
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: '#334155' }}>
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief context about this outbound or inbound integration"
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                background: '#ffffff',
                border: '1px solid #cbd5e1',
                color: '#1e293b',
                fontSize: '13px',
                outline: 'none'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: '#334155' }}>
              ERP Profile
            </label>
            <select value={selectedProfileVersionId} onChange={(e) => setErpProfileVersionId(e.target.value)} style={{ width: '100%', padding: '9px 12px', borderRadius: '6px', background: '#ffffff', border: '1px solid #cbd5e1', color: '#1e293b', fontSize: '13px' }} required>
              <option value="">Select a published ERP profile</option>
              {erpProfiles.map((profile) => <option key={profile.profile_version_id} value={profile.profile_version_id}>{profileOptionLabel(profile)}</option>)}
            </select>
            {erpProfiles.length === 0 && <small style={{ display: 'block', color: '#64748b', marginTop: '5px' }}>No published profiles are available. Ask an administrator to publish an ERP profile.</small>}
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: '#334155' }}>
              Business Requirement *
            </label>
            <textarea
              id="new-project-requirement"
              rows={4}
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="Describe what business records to extract, required filters, delivery frequency, delimiter formatting, and sanitization requirements."
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                background: '#ffffff',
                border: '1px solid #cbd5e1',
                color: '#1e293b',
                fontSize: '13px',
                outline: 'none',
                fontFamily: 'inherit'
              }}
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: '500', marginBottom: '6px', color: '#334155' }}>
              ERP Schema or Context (JSON) *
            </label>
            <textarea
              rows={8}
              value={schemaJson}
              onChange={(e) => setSchemaJson(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                background: '#f8fafc',
                border: '1px solid #cbd5e1',
                color: '#0284c7',
                fontSize: '12px',
                outline: 'none',
                fontFamily: 'var(--font-mono)'
              }}
              required
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
            <button type="button" onClick={onClose} className="btn btn-secondary">
              Cancel
            </button>
            <button type="submit" id="btn-submit-create-project" disabled={submitting} className="btn btn-primary">
              <Plus size={15} />
              <span>{submitting ? 'Creating...' : 'Create Project'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
