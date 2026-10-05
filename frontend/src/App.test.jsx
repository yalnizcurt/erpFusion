import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { configureAccessTokenProvider } from './api';
import { adminIdentity, fixtureProfiles } from '../tests/fixtures';

vi.mock('./utils/generatePdf', () => ({ openArtifactAsPdf: vi.fn() }));
afterEach(() => { configureAccessTokenProvider(null); window.history.replaceState({}, '', '/'); });

describe('verified identity boundary', () => {
  it('opens an authorized project directly at its saved Studio stage and revision', async () => {
    window.history.replaceState({}, '', '/projects/request-1/studio?tab=workspace&stage=FDD&revision=2');
    vi.stubGlobal('fetch', vi.fn((url) => {
      const path = new URL(url, 'http://fixture.test').pathname;
      if (path === '/api/identity/me') return Promise.resolve(Response.json(adminIdentity));
      if (path === '/api/projects/request-1') return Promise.resolve(Response.json({
        id: 'request-1', name: 'Supplier invoice export', client_id: 'client-a', client_name: 'Alpha Industries',
        erp_name: 'ERP 0', erp_version: 3, project_type: 'CUSTOM', status: 'ACTIVE', business_requirement: '', requirement_version: 1,
      }));
      if (path.endsWith('/workflow')) return Promise.resolve(Response.json({ current_stage: 'FDD', stages: [
        { stage: 'FDD', label: 'Functional Design', review_role: 'FUNCTIONAL_REVIEWER', can_generate: false, depends_on: [], gate_status: 'PENDING_REVIEW' },
      ] }));
      if (path.endsWith('/artifacts')) return Promise.resolve(Response.json([{ id: 'artifact-fdd', artifact_type: 'FDD', gate_status: 'PENDING_REVIEW', current_version: 2 }]));
      if (path.endsWith('/versions')) return Promise.resolve(Response.json([
        { id: 'version-2', version_number: 2, state: 'PENDING_HUMAN_REVIEW', content: {} },
        { id: 'version-1', version_number: 1, state: 'SUPERSEDED', content: {} },
      ]));
      return Promise.resolve(Response.json([]));
    }));

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Supplier invoice export' })).toBeTruthy();
    expect(await screen.findByRole('option', { name: 'v2 (PENDING_HUMAN_REVIEW)' })).toBeTruthy();
    expect(screen.getByLabelText('Configured engineering stage').value).toBe('FDD');
  });

  it('keeps requirement edits when Home navigation is canceled, then saves and reopens them', async () => {
    window.history.replaceState({}, '', '/projects/request-1/studio');
    let project = {
      id: 'request-1', name: 'Supplier invoice export', client_id: 'client-a', client_name: 'Alpha Industries',
      erp_name: 'ERP 0', erp_version: 3, project_type: 'CUSTOM', status: 'ACTIVE', workflow_status: 'DRAFT',
      business_requirement: 'Saved scope', erp_schema_context: {}, requirement_version: 1, schema_context_version: 1,
    };
    const fetch = vi.fn((url, options = {}) => {
      const path = new URL(url, 'http://fixture.test').pathname;
      if (path === '/api/identity/me') return Promise.resolve(Response.json(adminIdentity));
      if (path === '/api/erp-profiles') return Promise.resolve(Response.json(fixtureProfiles));
      if (path === '/api/projects' && options.method !== 'PATCH') return Promise.resolve(Response.json({ projects: [project], total: 1, summary: {} }));
      if (path === '/api/projects/request-1' && options.method === 'PATCH') {
        project = { ...project, ...JSON.parse(options.body), requirement_version: 2 };
        return Promise.resolve(Response.json(project));
      }
      if (path === '/api/projects/request-1') return Promise.resolve(Response.json(project));
      if (path.endsWith('/workflow')) return Promise.resolve(Response.json({ current_stage: 'CONTEXT_ANALYSIS', stages: [
        { stage: 'CONTEXT_ANALYSIS', label: 'Requirements analysis', review_role: 'FUNCTIONAL_REVIEWER', can_generate: true, depends_on: [], gate_status: 'LOCKED' },
      ] }));
      if (path.endsWith('/artifacts') || path.endsWith('/generation-jobs') || path.endsWith('/input-revisions') || path.endsWith('/requirements')) return Promise.resolve(Response.json([]));
      if (path.endsWith('/package')) return Promise.resolve(Response.json({ available: false, candidate_id: null, release_id: null, files: [], blockers: [] }));
      return Promise.resolve(Response.json([]));
    });
    vi.stubGlobal('fetch', fetch);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<App />);

    const requirement = await screen.findByLabelText(/Requirement text/);
    fireEvent.change(requirement, { target: { value: 'Edited supplier scope' } });
    fireEvent.click(screen.getByRole('button', { name: 'All projects' }));
    expect(window.location.pathname).toBe('/projects/request-1/studio');
    expect(screen.getByLabelText(/Requirement text/).value).toBe('Edited supplier scope');
    expect(confirm).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Save requirement revision' }));
    await waitFor(() => expect(fetch.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(true));
    await waitFor(() => expect(screen.getByLabelText(/Requirement text/).value).toBe('Edited supplier scope'));
    expect(screen.getByRole('button', { name: 'Save requirement revision' }).disabled).toBe(true);

    fireEvent.click(screen.getByRole('link', { name: /HighStudio/i }));
    await screen.findByRole('button', { name: 'Supplier invoice export', exact: true });
    expect(confirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Supplier invoice export', exact: true }));
    expect((await screen.findByLabelText(/Requirement text/)).value).toBe('Edited supplier scope');
  });

  it('fails closed before requesting project or client data if identity verification fails', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ detail: 'Authentication required' }, { status: 401 }));
    vi.stubGlobal('fetch', fetch);
    render(<App />);
    await screen.findByText('Sign-in required');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe('/api/identity/me');
    expect(screen.queryByRole('button', { name: 'ERP Profiles' })).toBeNull();
  });

  it('removes prior project data and verifies identity again when a session changes', async () => {
    let authenticateNext;
    let requests = 0;
    const fetch = vi.fn((url) => {
      if (url === '/api/identity/me') {
        requests += 1;
        return requests === 1 ? Promise.resolve(Response.json(adminIdentity)) : new Promise((resolve) => { authenticateNext = resolve; });
      }
      const path = new URL(url, 'http://fixture.test').pathname;
      if (path === '/api/projects') return Promise.resolve(Response.json({ projects: [{ id: 'private-project', name: 'Prior client project' }], total: 1, next_offset: null }));
      if (path.endsWith('/workflow')) return Promise.resolve(Response.json({ stages: [] }));
      return Promise.resolve(Response.json([]));
    });
    vi.stubGlobal('fetch', fetch);
    render(<App />);
    await screen.findByRole('button', { name: 'Prior client project', exact: true });
    act(() => configureAccessTokenProvider(async () => 'next-fixture-token'));
    expect(screen.queryByRole('button', { name: 'Prior client project', exact: true })).toBeNull();
    await waitFor(() => expect(requests).toBe(2));
    await act(async () => { authenticateNext(Response.json({ detail: 'Access revoked' }, { status: 403 })); });
    await screen.findByText('Sign-in required');
    expect(screen.queryByRole('button', { name: 'Prior client project', exact: true })).toBeNull();
  });

  it.each([
    ['TESTER', true],
    ['TECHNICAL_REVIEWER', false],
  ])('uses the configured %s review role for a custom workflow stage', async (reviewRole, permitted) => {
    window.history.replaceState({}, '', '/projects/request-1/studio?tab=workspace&stage=SANDBOX_SIGNOFF');
    const identity = { ...adminIdentity, platform_roles: [], capabilities: { manage_clients: false, configure_erp: false, publish_erp: false },
      clients: [{ id: 'client-a', display_name: 'Alpha Industries', roles: ['TESTER'], permissions: {
        manage_environment: false, create_request: false, review_functional: false, review_technical: false, test: true,
      } }] };
    vi.stubGlobal('fetch', vi.fn((url) => {
      const path = new URL(url, 'http://fixture.test').pathname;
      if (path === '/api/identity/me') return Promise.resolve(Response.json(identity));
      if (path === '/api/projects/request-1') return Promise.resolve(Response.json({ id: 'request-1', name: 'Sandbox acceptance', client_id: 'client-a' }));
      if (path.endsWith('/workflow')) return Promise.resolve(Response.json({ current_stage: 'SANDBOX_SIGNOFF', stages: [
        { stage: 'SANDBOX_SIGNOFF', review_role: reviewRole, can_generate: false, depends_on: [], gate_status: 'PENDING_REVIEW' },
      ] }));
      if (path.endsWith('/artifacts')) return Promise.resolve(Response.json([{ id: 'artifact-1', artifact_type: 'SANDBOX_SIGNOFF', gate_status: 'PENDING_REVIEW', current_version: 1 }]));
      if (path.endsWith('/versions')) return Promise.resolve(Response.json([{ id: 'version-1', version_number: 1, state: 'PENDING_HUMAN_REVIEW', content: {} }]));
      return Promise.resolve(Response.json([]));
    }));
    render(<App />);
    await screen.findByRole('option', { name: 'v1 (PENDING_HUMAN_REVIEW)' });
    expect(!!screen.queryByRole('button', { name: 'Approve Gate' })).toBe(permitted);
    expect(screen.queryByRole('button', { name: 'ERP Profiles' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'New', exact: true })).toBeNull();
  });

  it('sends ERP and status queue filters to the server and clears the previous selection', async () => {
    const fetch = vi.fn((url) => {
      const path = new URL(url, 'http://fixture.test');
      if (path.pathname === '/api/identity/me') return Promise.resolve(Response.json(adminIdentity));
      if (path.pathname === '/api/erp-profiles') return Promise.resolve(Response.json(fixtureProfiles));
      if (path.pathname === '/api/projects') return Promise.resolve(Response.json({ projects: path.searchParams.has('request_status') ? [] : [{ id: 'request-1', name: 'Active request' }], next_offset: null }));
      if (path.pathname.endsWith('/workflow')) return Promise.resolve(Response.json({ stages: [] }));
      return Promise.resolve(Response.json([]));
    });
    vi.stubGlobal('fetch', fetch);
    render(<App />);
    await screen.findByRole('option', { name: 'ERP 0' });
    await screen.findByRole('button', { name: 'Active request', exact: true });
    fireEvent.change(screen.getByLabelText('Filter requests by ERP'), { target: { value: 'profile-0' } });
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('erp_profile_id=profile-0'))).toBe(true));
    fireEvent.change(screen.getByLabelText('Filter requests by status'), { target: { value: 'COMPLETED' } });
    await screen.findByText('No projects match these filters.');
    expect(fetch.mock.calls.some(([url]) => url.includes('erp_profile_id=profile-0') && url.includes('request_status=COMPLETED'))).toBe(true);
    expect(screen.queryByRole('button', { name: 'Active request', exact: true })).toBeNull();
  });
});
