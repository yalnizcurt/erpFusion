import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { requestJson } from '../api';
import type { ClientMembership, ClientRole } from '../contracts/identity';
import { useApiResource } from '../hooks/useApiResource';

const roles: { value: ClientRole; label: string }[] = [
  { value: 'CLIENT_ADMIN', label: 'Client administrator' },
  { value: 'CONSULTANT', label: 'Consultant' },
  { value: 'FUNCTIONAL_REVIEWER', label: 'Functional reviewer' },
  { value: 'TECHNICAL_REVIEWER', label: 'Technical reviewer' },
  { value: 'TESTER', label: 'Tester' },
];

/** Rendered only after the server grants client administration permission. */
export default function ClientMemberships({ clientId }: { clientId: string }) {
  const path = `/api/clients/${clientId}/memberships`;
  const memberships = useApiResource<ClientMembership[]>(path);
  const [subject, setSubject] = useState('');
  const [role, setRole] = useState<ClientRole>('CONSULTANT');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mutate = async (method: 'POST' | 'DELETE', membershipId?: string) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await requestJson(membershipId ? `${path}/${membershipId}` : path, {
        method, ...(method === 'POST' ? { body: JSON.stringify({ subject_id: subject.trim(), role }) } : {}),
      });
      memberships.reload(); setNotice(method === 'POST' ? 'Client role assigned.' : 'Client role revoked.');
      if (method === 'POST') setSubject('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to update client access.'); }
    finally { pending.current = false; setBusy(false); }
  };
  const assign = (event: FormEvent) => {
    event.preventDefault();
    if (subject.trim()) void mutate('POST');
  };
  return <section aria-label="Client access" style={{ padding: 18, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 9, minWidth: 0 }}>
    <h2 style={{ fontSize: 16 }}>Client access</h2>
    <p style={{ fontSize: 12, color: '#64748b', margin: '8px 0' }}>Assign a role using the person’s subject identifier from your configured identity provider. Each role applies only to this client.</p>
    {(error || memberships.error) && <p role="alert" style={{ color: '#991b1b' }}>{error || memberships.error}</p>}
    {notice && <p role="status">{notice}</p>}
    <form onSubmit={assign} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'end', marginBottom: 12 }}>
      <label style={{ display: 'grid', gap: 6, flex: '1 1 200px', fontSize: 12 }}>Identity provider subject
        <input required maxLength={255} value={subject} disabled={busy} onChange={(event) => setSubject(event.target.value)} style={{ padding: 8, border: '1px solid #cbd5e1', borderRadius: 6 }} />
      </label>
      <label style={{ display: 'grid', gap: 6, fontSize: 12 }}>Client role
        <select value={role} disabled={busy} onChange={(event) => setRole(event.target.value as ClientRole)} style={{ padding: 8, border: '1px solid #cbd5e1', borderRadius: 6 }}>{roles.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
      </label>
      <button type="submit" disabled={busy || !subject.trim()} className="btn btn-primary">Assign role</button>
    </form>
    {memberships.loading ? <p role="status">Loading client access…</p> : <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 8 }}>
      {memberships.data?.filter((item) => item.client_id === clientId).map((item) => <li key={item.id} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: 10, background: '#f8fafc', borderRadius: 6 }}>
        <span style={{ minWidth: 0, overflowWrap: 'anywhere', flex: 1 }}><strong style={{ fontSize: 12 }}>{roles.find((entry) => entry.value === item.role)?.label || item.role} · {item.status}</strong><small style={{ display: 'block', color: '#64748b' }}>Principal ID: {item.subject_id}</small></span>
        {item.status === 'ACTIVE' && <button type="button" className="btn btn-secondary" disabled={busy} aria-label={`Revoke ${item.role} for ${item.subject_id}`} onClick={() => {
          if (window.confirm('Revoke this client role? The person will lose the permissions granted by this role.')) void mutate('DELETE', item.id);
        }}>Revoke</button>}
      </li>)}
      {!memberships.data?.length && !memberships.error && <li style={{ color: '#64748b', fontSize: 12 }}>No client roles have been assigned.</li>}
    </ul>}
  </section>;
}
