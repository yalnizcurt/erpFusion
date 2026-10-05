import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import QualificationWorkspace from './QualificationWorkspace';

const { requestJson, downloadApiFile, resources } = vi.hoisted(() => ({ requestJson: vi.fn(), downloadApiFile: vi.fn(), resources: {} }));
vi.mock('../api', () => ({ requestJson, downloadApiFile }));
vi.mock('../hooks/useApiResource', () => ({ useApiResource: (path) => ({ data: resources[path], error: null, loading: false, reload: vi.fn() }) }));
vi.mock('./ConnectionSettings', () => ({ default: () => <div>Connection settings</div> }));

const project = { id: 'project-1', client_id: 'client-1', erp_installation_id: 'install-1', erp_environment_id: 'env-1' };
const admin = { capabilities: { manage_clients: true }, clients: [] };
const tester = { capabilities: { manage_clients: false }, clients: [{ id: 'client-1', roles: ['TESTER'] }] };
const base = '/api/projects/project-1';
const capabilitiesPath = `${base}/executions/capabilities/env-1`;
const environmentsPath = '/api/clients/client-1/installations/install-1/environments';
const attempt = { id: 'attempt-1', candidate_id: 'candidate-1', candidate_checksum: 'a'.repeat(64), environment_id: 'env-1', operation: 'QUALIFY_CANDIDATE', adapter: 'oracle_simulator', adapter_version: '1', integration_pattern_version_id: 'pattern-v1', simulated: true, verdict: 'NOT_RUN', status: 'AWAITING_APPROVAL', created_at: '2026-10-05T08:00:00Z', assurance: [], request: { parameters: {}, scenario: 'SUCCESS' }, result: {} };

beforeEach(() => {
  for (const key of Object.keys(resources)) delete resources[key];
  requestJson.mockResolvedValue({ id: 'attempt-1' });
  resources[environmentsPath] = [{ id: 'env-1', installation_id: 'install-1', display_name: 'Company TEST', environment_type: 'TEST', custody: 'CUSTOMER', execution_mode: 'SIMULATED' }];
  resources[`${base}/package`] = { candidate_id: 'candidate-1', manifest: { artifacts: { FDD: {}, TDD: {}, PUBLISHER: {} }, integration_pattern: { name: 'Publisher outbound', version: 1, runtime_type: 'ERP_NATIVE', deliverable_type: 'PUBLISHER_SOURCE', qualification_strategy: 'NATIVE_ARTIFACT', baseline_versions: [{ id: 'baseline-v1' }], configuration: { generation_rules: { strategy: 'publisher_source', strategy_version: '1' } } } } };
  resources[`${base}/executions`] = { attempts: [] };
  resources[capabilitiesPath] = { available: true, actor_can_execute: true, qualification_ready: true, qualification_id: 'qualification-1', mode: 'SIMULATED', adapter: 'oracle_simulator', capabilities: [{ name: 'RUN_REPORT', implemented: true, qualified: true }], blockers: [] };
});

describe('deliverable qualification controls', () => {
  it('labels simulation honestly and requests a test without automatically approving or dispatching it', async () => {
    render(<QualificationWorkspace project={project} identity={tester} />);
    expect(screen.getByText('SIMULATED qualification')).toBeTruthy();
    expect(screen.getByText(/passing simulation is never live ERP evidence/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Request deliverable test' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledOnce());
    const [path, options] = requestJson.mock.calls[0];
    expect(path).toBe(`${base}/executions`);
    expect(JSON.parse(options.body)).toMatchObject({ candidate_id: 'candidate-1', environment_id: 'env-1', operation: 'QUALIFY_CANDIDATE', scenario: 'SUCCESS', parameters: {} });
    expect(requestJson.mock.calls.some(([url]) => url.endsWith('/approve'))).toBe(false);
    expect(await screen.findByRole('status')).toHaveProperty('textContent', expect.stringContaining('approve it separately'));
  });

  it('requires explicit approval for the exact displayed attempt', async () => {
    resources[`${base}/executions`] = { attempts: [attempt] };
    render(<QualificationWorkspace project={project} identity={tester} />);
    fireEvent.click(screen.getByText(/SIMULATED · AWAITING_APPROVAL/));
    fireEvent.click(screen.getByRole('button', { name: 'Approve this exact test' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledOnce());
    expect(requestJson.mock.calls[0][0]).toBe(`${base}/executions/attempt-1/approve`);
    expect(JSON.parse(requestJson.mock.calls[0][1].body)).toEqual({ acknowledge: true });
  });

  it('shows unsupported pattern capabilities and blocks automatic testing for a read-only user', () => {
    resources[capabilitiesPath] = { available: false, actor_can_execute: false, capabilities: [{ name: 'CALL_API', implemented: false, qualified: false }], blockers: ['pattern_adapter_not_implemented'] };
    render(<QualificationWorkspace project={project} identity={{ capabilities: { manage_clients: false }, clients: [] }} />);
    expect(screen.getByText('CALL_API')).toBeTruthy();
    expect(screen.getByText('Not implemented')).toBeTruthy();
    expect(screen.getByText('pattern_adapter_not_implemented')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Request deliverable test' }).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Approve target capabilities' })).toBeNull();
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('keeps ownership acknowledgement separate from capability authorization', () => {
    render(<QualificationWorkspace project={project} identity={admin} />);
    fireEvent.click(screen.getByText('Review environment ownership and execution mode'));
    expect(screen.getByLabelText('Execution mode').value).toBe('SIMULATED');
    fireEvent.click(screen.getByLabelText(/I confirm ownership/));
    expect(screen.getByRole('button', { name: 'Save target review' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Approve target capabilities' }).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Execution mode'), { target: { value: 'ASSISTED' } });
    expect(screen.getByLabelText(/I confirm ownership/).checked).toBe(false);
    expect(screen.getByRole('button', { name: 'Save target review' }).disabled).toBe(true);
  });

  it('records only supported unknown-outcome decisions as assisted evidence', async () => {
    resources[`${base}/executions`] = { attempts: [{ ...attempt, status: 'UNKNOWN_OUTCOME' }] };
    render(<QualificationWorkspace project={project} identity={tester} />);
    fireEvent.click(screen.getByText(/SIMULATED · UNKNOWN_OUTCOME/));
    expect(screen.queryByRole('option', { name: 'CONFIRMED_COMPLETED' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Reconciliation outcome'), { target: { value: 'CONFIRMED_NO_EXECUTION' } });
    fireEvent.change(screen.getByLabelText('Human reconciliation evidence'), { target: { value: 'Authorized operator found no corresponding execution.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record human reconciliation' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledOnce());
    expect(requestJson.mock.calls[0][0]).toBe(`${base}/executions/attempt-1/reconcile`);
    expect(JSON.parse(requestJson.mock.calls[0][1].body)).toMatchObject({ outcome: 'CONFIRMED_NO_EXECUTION', acknowledge: true });
    expect(await screen.findByRole('status')).toHaveProperty('textContent', expect.stringContaining('does not turn the unknown attempt into a passing test'));
  });

  it('queues a new reviewed revision using a selected stage from the manifest and sanitized failure context', async () => {
    resources[`${base}/executions`] = { attempts: [{ ...attempt, status: 'FAILED' }] };
    requestJson.mockResolvedValueOnce({ attempt_id: 'attempt-1', failure: { category: 'EXECUTION', safe_message: 'Job failed.' } }).mockResolvedValueOnce({ id: 'generation-1' });
    render(<QualificationWorkspace project={project} identity={admin} />);
    fireEvent.click(screen.getByText(/SIMULATED · FAILED/));
    fireEvent.click(screen.getByRole('button', { name: 'Review safe failure context' }));
    await screen.findByLabelText('Stage to revise');
    fireEvent.change(screen.getByLabelText('Stage to revise'), { target: { value: 'PUBLISHER' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate correction for review' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledTimes(2));
    expect(requestJson.mock.calls[1][0]).toBe(`${base}/executions/attempt-1/remediate`);
    expect(JSON.parse(requestJson.mock.calls[1][1].body)).toEqual({ stage: 'PUBLISHER', acknowledge: true });
    expect(await screen.findByRole('status')).toHaveProperty('textContent', expect.stringContaining('Review and approve the new revision'));
  });
});
