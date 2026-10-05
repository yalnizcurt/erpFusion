import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import NewProjectModal from './NewProjectModal';
import { adminIdentity, fixtureProfiles, onboardingResponse } from '../../tests/fixtures';

function renderForm(onCreateProject = vi.fn().mockResolvedValue(undefined), patterns: unknown[] = []) {
  const fetch = vi.fn((url: string) => {
    const path = new URL(url, 'http://fixture.test').pathname;
    return Promise.resolve(Response.json(path === '/api/integration-patterns' ? patterns : onboardingResponse(path)));
  });
  vi.stubGlobal('fetch', fetch);
  const onClose = vi.fn();
  render(<NewProjectModal identity={adminIdentity} erpProfiles={fixtureProfiles} onClose={onClose} onCreateProject={onCreateProject} />);
  return { fetch, onClose, onCreateProject };
}

async function selectOwner(selectProfile = true) {
  await screen.findByRole('option', { name: 'Alpha Industries' });
  fireEvent.change(screen.getByLabelText('Client *'), { target: { value: 'client-a' } });
  await screen.findByRole('option', { name: 'Alpha Industries finance' });
  expect(screen.queryByRole('option', { name: 'Beta Industries finance' })).toBeNull();
  fireEvent.change(screen.getByLabelText('ERP installation *'), { target: { value: 'installation-0' } });
  await screen.findByRole('option', { name: 'Alpha Industries finance sandbox · SANDBOX' });
  fireEvent.change(screen.getByLabelText('Execution environment *'), { target: { value: 'environment-0' } });
  expect(screen.queryByRole('option', { name: 'ERP 1 · Profile v3' })).toBeNull();
  if (selectProfile) {
    await waitFor(() => expect((screen.getByRole('button', { name: 'Create Project' }) as HTMLButtonElement).disabled).toBe(true));
    fireEvent.change(screen.getByLabelText('ERP profile version *'), { target: { value: 'profile-version-0' } });
  }
  fireEvent.change(screen.getByLabelText('Project Name *'), { target: { value: 'Supplier invoice export' } });
}

describe('integration request ownership', () => {
  it('requires explicit selections and submits exact matching client, installation, environment and profile version', async () => {
    const { onCreateProject, onClose } = renderForm();
    await screen.findByRole('option', { name: 'Alpha Industries' });
    expect((screen.getByLabelText('Client *') as HTMLSelectElement).value).toBe('');
    expect((screen.getByRole('button', { name: 'Create Project' }) as HTMLButtonElement).disabled).toBe(true);
    await selectOwner();
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    await waitFor(() => expect(onCreateProject).toHaveBeenCalledTimes(1));
    expect(onCreateProject.mock.calls[0]?.[0]).toMatchObject({
      client_id: 'client-a', erp_installation_id: 'installation-0', erp_environment_id: 'environment-0',
      erp_profile_version_id: 'profile-version-0', erp_schema_context: {}, business_requirement: '', project_type: 'CUSTOM', due_date: null,
    });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('preserves ownership and draft fields after a rejected save', async () => {
    const onCreateProject = vi.fn().mockRejectedValue(new Error('Profile was retired.'));
    renderForm(onCreateProject);
    await selectOwner();
    fireEvent.change(screen.getByLabelText('Integration type'), { target: { value: 'STANDARD' } });
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-10-12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    await screen.findByText('Profile was retired.');
    expect((screen.getByLabelText('Project Name *') as HTMLInputElement).value).toBe('Supplier invoice export');
    expect((screen.getByLabelText('ERP profile version *') as HTMLSelectElement).value).toBe('profile-version-0');
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(onCreateProject.mock.calls[0]?.[0]).toMatchObject({ project_type: 'STANDARD', due_date: '2026-10-12' });
  });

  it('clears downstream selections when the selected client changes', async () => {
    renderForm();
    await selectOwner();
    fireEvent.change(screen.getByLabelText('Client *'), { target: { value: 'client-b' } });
    expect((screen.getByLabelText('ERP installation *') as HTMLSelectElement).value).toBe('');
    expect((screen.getByLabelText('Execution environment *') as HTMLSelectElement).value).toBe('');
    expect((screen.getByLabelText('ERP profile version *') as HTMLSelectElement).value).toBe('');
    await screen.findByRole('option', { name: 'Beta Industries finance' });
    expect(screen.queryByRole('option', { name: 'Alpha Industries finance' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Create Project' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('pins the selected pattern intelligence version even when a newer product profile is published', async () => {
    const { onCreateProject } = renderForm(undefined, [{ id: 'pattern-1', name: 'Approved API mapping', versions: [{
      id: 'pattern-version-2', version: 2, profile_version_id: 'older-profile-version',
      runtime_type: 'API_INTEGRATION', deliverable_type: 'API_MAPPING', implementation_status: 'GENERATION_SUPPORTED',
    }] }]);
    await selectOwner(false);
    await screen.findByRole('option', { name: /Approved API mapping · v2/ });
    expect((screen.getByRole('button', { name: 'Create Project' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Integration pattern and version *'), { target: { value: 'pattern-version-2' } });
    expect(screen.queryByLabelText('ERP profile version *')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    await waitFor(() => expect(onCreateProject).toHaveBeenCalledOnce());
    expect(onCreateProject.mock.calls[0]?.[0]).toMatchObject({
      integration_pattern_version_id: 'pattern-version-2', erp_profile_version_id: 'older-profile-version',
      client_id: 'client-a', erp_installation_id: 'installation-0', erp_environment_id: 'environment-0',
    });
  });

  it('blocks creation when pattern discovery fails instead of bypassing pattern selection', async () => {
    const { fetch, onCreateProject } = renderForm();
    fetch.mockImplementation((url: string) => {
      const path = new URL(url, 'http://fixture.test').pathname;
      return Promise.resolve(path === '/api/integration-patterns' ? Response.json({ detail: 'Pattern registry unavailable' }, { status: 503 }) : Response.json(onboardingResponse(path)));
    });
    await selectOwner();
    await screen.findByText('Pattern registry unavailable');
    expect((screen.getByRole('button', { name: 'Create Project' }) as HTMLButtonElement).disabled).toBe(true);
    expect(onCreateProject).not.toHaveBeenCalled();
  });
});
