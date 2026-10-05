import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ClientWorkspace from './ClientWorkspace';
import { adminIdentity, fixtureClients, fixtureInstallations, fixtureProfiles, onboardingResponse } from '../../tests/fixtures';
import type { CurrentIdentity } from '../contracts/identity';

describe('client onboarding console', () => {
  it('uses the public profile id when creating an installation', async () => {
    const fetch = vi.fn((url: string, options?: RequestInit) => Promise.resolve(Response.json(options?.method === 'POST'
      ? fixtureInstallations[0] : onboardingResponse(new URL(url, 'http://fixture.test').pathname))));
    vi.stubGlobal('fetch', fetch);
    render(<ClientWorkspace identity={adminIdentity} erpProfiles={fixtureProfiles} />);
    fireEvent.click(await screen.findByRole('button', { name: /Alpha Industries/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Add installation' }));
    const dialog = within(screen.getByRole('dialog'));
    fireEvent.change(dialog.getByLabelText('ERP profile'), { target: { value: 'profile-0' } });
    fireEvent.change(dialog.getByLabelText('Installation key'), { target: { value: 'finance' } });
    fireEvent.change(dialog.getByLabelText('Display name'), { target: { value: 'Client finance' } });
    fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(fetch.mock.calls.some((call) => call[1]?.method === 'POST')).toBe(true));
    const call = fetch.mock.calls.find((entry) => entry[1]?.method === 'POST');
    expect(call?.[0]).toBe('/api/clients/client-a/installations');
    expect(JSON.parse(String(call?.[1]?.body)).erp_profile_id).toBe('profile-0');
  });

  it('hides client administration controls from a consultant', async () => {
    const identity: CurrentIdentity = { ...adminIdentity, platform_roles: [], capabilities: { manage_clients: false, configure_erp: false, publish_erp: false }, clients: [{ id: 'client-a', display_name: 'Alpha Industries', roles: ['CONSULTANT'], permissions: { manage_environment: false, create_request: true, review_functional: false, review_technical: false, test: false } }] };
    const fetch = vi.fn((url: string) => Promise.resolve(Response.json(onboardingResponse(new URL(url, 'http://fixture.test').pathname))));
    vi.stubGlobal('fetch', fetch);
    render(<ClientWorkspace identity={identity} erpProfiles={fixtureProfiles} />);
    fireEvent.click(await screen.findByRole('button', { name: /Alpha Industries/ }));
    await screen.findByRole('button', { name: /Alpha Industries finance/ });
    expect(screen.queryByRole('button', { name: 'Add client' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add installation' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Client access' })).toBeNull();
    expect(fetch.mock.calls.some((call) => call[0].includes('/memberships'))).toBe(false);
  });

  it('requests bounded client pages and clears selected client before a search', async () => {
    const fetch = vi.fn((url: string) => {
      const path = new URL(url, 'http://fixture.test');
      const data = path.pathname === '/api/clients' && !path.searchParams.get('search')
        ? Array.from({ length: 25 }, (_, index) => ({ ...fixtureClients[0], id: `paged-${index}`, display_name: `Paged client ${index}` }))
        : path.pathname === '/api/clients' ? [] : onboardingResponse(path.pathname);
      return Promise.resolve(Response.json(data));
    });
    vi.stubGlobal('fetch', fetch);
    render(<ClientWorkspace identity={adminIdentity} erpProfiles={fixtureProfiles} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Paged client 0 alpha' }));
    fireEvent.change(screen.getByLabelText('Search clients'), { target: { value: 'Unknown client' } });
    expect(screen.queryByRole('heading', { name: 'Paged client 0' })).toBeNull();
    await screen.findByText('No clients match this page.');
    expect(fetch.mock.calls.some((call) => call[0] === '/api/clients?search=Unknown+client&limit=25&offset=0')).toBe(true);
    expect(fetch.mock.calls[0]?.[0]).toBe('/api/clients?search=&limit=25&offset=0');
  });
});
