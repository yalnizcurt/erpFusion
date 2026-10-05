import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { adminIdentity } from '../tests/fixtures';

const auth = vi.hoisted(() => ({ snapshot: { configured: true, status: 'signed_out', error: '' }, listeners: new Set(), signIn: vi.fn(), signOut: vi.fn() }));
vi.mock('./auth/oidc', () => ({
  getOidcState: () => auth.snapshot,
  subscribeOidcState: (listener) => { auth.listeners.add(listener); return () => auth.listeners.delete(listener); },
  initializeOidc: () => Promise.resolve(), beginSignIn: auth.signIn, signOut: auth.signOut,
}));
vi.mock('./utils/generatePdf', () => ({ openArtifactAsPdf: vi.fn() }));
beforeEach(() => { auth.snapshot = { configured: true, status: 'signed_out', error: '' }; });

describe('hosted sign-in controls', () => {
  it('offers sign-in and does not load private API data before authentication', () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in', exact: true }));
    expect(auth.signIn).toHaveBeenCalledOnce(); expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'ERP Profiles', exact: true })).toBeNull();
  });

  it('keeps logout available when Cognito succeeds but portal account provisioning is missing', async () => {
    auth.snapshot = { configured: true, status: 'signed_in', error: '' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: 'Portal membership required' }, { status: 403 })));
    render(<App />);
    await screen.findByText('Portal access unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Sign out', exact: true }));
    expect(auth.signOut).toHaveBeenCalledOnce();
  });

  it('hides prior client data immediately when the in-memory session expires', async () => {
    auth.snapshot = { configured: true, status: 'signed_in', error: '' };
    vi.stubGlobal('fetch', vi.fn((url) => {
      const path = new URL(url, 'http://fixture.test').pathname;
      if (path === '/api/identity/me') return Promise.resolve(Response.json(adminIdentity));
      if (path === '/api/projects') return Promise.resolve(Response.json({ projects: [{ id: 'request-1', name: 'Private client request' }] }));
      if (path.endsWith('/workflow')) return Promise.resolve(Response.json({ stages: [] }));
      return Promise.resolve(Response.json([]));
    }));
    render(<App />);
    await screen.findByRole('button', { name: 'Private client request', exact: true });
    act(() => { auth.snapshot = { configured: true, status: 'error', error: 'Your session expired. Sign in again.' }; for (const listener of auth.listeners) listener(); });
    expect(screen.queryByRole('button', { name: 'Private client request', exact: true })).toBeNull();
    expect(screen.getByRole('button', { name: 'Sign in', exact: true })).toBeTruthy();
  });
});
