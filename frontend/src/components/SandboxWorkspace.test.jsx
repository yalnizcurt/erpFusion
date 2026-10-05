import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SandboxWorkspace from './SandboxWorkspace';

const { requestJson, downloadApiFile, mockState } = vi.hoisted(() => ({ requestJson: vi.fn(), downloadApiFile: vi.fn(), mockState: { manualConnectionRequired: true, connectionConfigured: true, executionMode: 'ASSISTED', assistedReleaseAllowed: true, evidence: [] } }));
vi.mock('../api', () => ({ requestJson, downloadApiFile }));
vi.mock('../hooks/useApiResource', () => ({
  useApiResource: (path) => {
    const data = path?.endsWith('/package') ? { available: true, candidate_id: 'candidate-1', candidate_checksum: 'a'.repeat(64), blockers: [], manifest: { integration_pattern_version_id: 'pattern-version-1', baseline_versions: [{ asset_id: 'baseline-1', version: 2 }] } }
      : path?.endsWith('/package/releases') ? { releases: [] }
        : path?.endsWith('/sandbox/evidence') ? { evidence: mockState.evidence, test_plan: { version: 'approved-1', required_cases: [{ id: 'required-case', expected: { count: 2 } }] }, test_plan_sha256: 'b'.repeat(64), blockers: [], manual_connection_required: mockState.manualConnectionRequired, assisted_release_allowed: mockState.assistedReleaseAllowed, automatic_execution_supported: false }
          : path?.endsWith('/environments') ? [{ id: 'env-1', display_name: 'UAT', environment_type: 'TEST', custody: 'CUSTOMER', execution_mode: mockState.executionMode, status: 'ACTIVE' }]
            : { configured: mockState.connectionConfigured, configuration_version: mockState.connectionConfigured ? 4 : null };
    return { data, error: null, loading: false, reload: vi.fn() };
  },
}));

const project = { id: 'project-1', client_id: 'client-1', erp_installation_id: 'install-1', erp_environment_id: 'env-1' };
const tester = { capabilities: { manage_clients: false }, clients: [{ id: 'client-1', roles: ['TESTER'] }] };

beforeEach(() => {
  requestJson.mockResolvedValue({ id: 'evidence-1' });
  mockState.manualConnectionRequired = true;
  mockState.connectionConfigured = true;
  mockState.executionMode = 'ASSISTED';
  mockState.assistedReleaseAllowed = true;
  mockState.evidence = [];
});

describe('SandboxWorkspace', () => {
  it('keeps a read-only identity from submitting evidence and never auto-deploys', () => {
    render(<SandboxWorkspace project={project} identity={{ capabilities: { manage_clients: false }, clients: [] }} />);
    expect(screen.getByText(/source ZIP is not a qualified native package/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Record assisted test evidence' }).disabled).toBe(true);
    expect(requestJson).not.toHaveBeenCalled();
    expect(downloadApiFile).not.toHaveBeenCalled();
  });

  it('submits only user-entered observations and their note hash for the approved case', async () => {
    render(<SandboxWorkspace project={project} identity={tester} />);
    fireEvent.change(screen.getByLabelText('Observed result (JSON)'), { target: { value: '{"count":2}' } });
    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.change(screen.getByLabelText('Observation / evidence note'), { target: { value: 'Build output reviewed in UAT.' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Record assisted test evidence' }));

    await waitFor(() => expect(requestJson).toHaveBeenCalledOnce());
    const [path, options] = requestJson.mock.calls[0];
    const body = JSON.parse(options.body);
    const noteHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode('Build output reviewed in UAT.'))), (byte) => byte.toString(16).padStart(2, '0')).join('');
    expect(path).toBe('/api/projects/project-1/sandbox/evidence');
    expect(body).toMatchObject({ candidate_id: 'candidate-1', candidate_checksum: 'a'.repeat(64), reviewed_source_checksum: 'a'.repeat(64), environment_id: 'env-1', connection_version: 4 });
    expect(body).not.toHaveProperty('installed_candidate_checksum');
    expect(body.cases).toEqual([{ id: 'required-case', status: 'PASSED', expected: { count: 2 }, actual: { count: 2 }, evidence_note: 'Build output reviewed in UAT.', evidence_sha256: noteHash }]);
    expect(body).not.toHaveProperty('secret_version');
    expect(await screen.findByText(/checksum identifies the reviewed source bundle only/i)).toBeTruthy();
  });

  it('records assisted pattern evidence without a connection while keeping higher-assurance sign-off blocked', async () => {
    mockState.manualConnectionRequired = false;
    mockState.connectionConfigured = false;
    mockState.assistedReleaseAllowed = false;
    mockState.evidence = [{ id: 'evidence-prior', candidate_id: 'candidate-1', environment_id: 'env-1', candidate_checksum: 'a'.repeat(64), connection_version: null, status: 'PASSED', method: 'ASSISTED_MANUAL', execution_attempt_id: null, created_at: '2026-10-05T00:00:00Z' }];
    render(<SandboxWorkspace project={project} identity={tester} />);
    expect(screen.getByText(/pattern version .*approved baselines .*target environment UAT/i)).toBeTruthy();
    expect(screen.getByText(/No ERP connection or secret is required/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Record assisted test evidence' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Sign off this evidence' }).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Observed result (JSON)'), { target: { value: '{"count":2}' } });
    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.change(screen.getByLabelText('Observation / evidence note'), { target: { value: 'Reviewed in UAT.' } });
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: 'Record assisted test evidence' }).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Record assisted test evidence' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledOnce());
    const [path, options] = requestJson.mock.calls[0];
    expect(path).toBe('/api/projects/project-1/sandbox/evidence');
    expect(JSON.parse(options.body).connection_version).toBeNull();
    expect(requestJson.mock.calls).toHaveLength(1);
    expect(downloadApiFile).not.toHaveBeenCalled();
  });

  it('does not offer manual sign-off for machine execution evidence', () => {
    mockState.executionMode = 'SIMULATED';
    mockState.evidence = [{ id: 'machine-evidence', candidate_id: 'candidate-1', environment_id: 'env-1', candidate_checksum: 'a'.repeat(64), connection_version: 4, status: 'PASSED', method: 'SIMULATED_EXECUTION', execution_attempt_id: 'attempt-1', created_at: '2026-10-05T00:00:00Z' }];
    render(<SandboxWorkspace project={project} identity={tester} />);
    expect(screen.queryByRole('button', { name: 'Sign off this evidence' })).toBeNull();
  });
});
