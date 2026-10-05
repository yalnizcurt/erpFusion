import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ClientMemberships from './ClientMemberships';

describe('client membership administration', () => {
  it('assigns provider subjects, displays stored principal identifiers honestly and revokes only the selected membership', async () => {
    const membership = { id: 'membership-1', client_id: 'client-a', subject_id: 'principal-uuid', role: 'CONSULTANT', status: 'ACTIVE' };
    const fetch = vi.fn((url: string, options?: RequestInit) => Promise.resolve(options?.method === 'DELETE'
      ? new Response(null, { status: 204 }) : Response.json(options?.method === 'POST' ? membership : [membership])));
    vi.stubGlobal('fetch', fetch);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ClientMemberships clientId="client-a" />);
    await screen.findByText('Principal ID: principal-uuid');
    fireEvent.change(screen.getByLabelText('Identity provider subject'), { target: { value: ' provider-subject-42 ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Assign role' }));
    await waitFor(() => expect(fetch.mock.calls.some((entry) => entry[1]?.method === 'POST')).toBe(true));
    const create = fetch.mock.calls.find((entry) => entry[1]?.method === 'POST');
    expect(create?.[0]).toBe('/api/clients/client-a/memberships');
    expect(JSON.parse(String(create?.[1]?.body))).toEqual({ subject_id: 'provider-subject-42', role: 'CONSULTANT' });
    await screen.findByText('Client role assigned.');
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke CONSULTANT for principal-uuid' }));
    await waitFor(() => expect(fetch.mock.calls.some((entry) => entry[0] === '/api/clients/client-a/memberships/membership-1' && entry[1]?.method === 'DELETE')).toBe(true));
  });
});
