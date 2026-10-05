import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import DeploymentPackageView from './DeploymentPackageView';

const { requestJson, downloadApiFile } = vi.hoisted(() => ({ requestJson: vi.fn(), downloadApiFile: vi.fn() }));
vi.mock('../api', () => ({ requestJson, downloadApiFile }));

let packageState;
const releases = [{ id: 'release-old', candidate_id: 'candidate-old', evidence_id: 'evidence-old', checksum: 'c'.repeat(64), created_at: '2026-09-01T00:00:00Z', download_url: '/api/projects/project-a/package/releases/release-old/download' }];
vi.mock('../hooks/useApiResource', () => ({
  useApiResource: (path) => ({
    data: path?.endsWith('/package') ? packageState
      : path?.endsWith('/package/releases') ? { releases }
        : path?.endsWith('/versions/1') ? { version_number: 1, content: { package_name: 'PKG', pks_content: 'create or replace package PKG;' } }
          : null,
    error: null, loading: false, reload: vi.fn(),
  }),
}));

const stage = [{ stage: 'SQL', artifact_id: 'artifact-SQL' }];
const consultant = { capabilities: { manage_clients: false }, clients: [{ id: 'client-a', roles: ['CONSULTANT'] }] };

describe('DeploymentPackageView downloads', () => {
  it('downloads an existing candidate and historical release with GET only', async () => {
    packageState = { available: true, kind: 'candidate', candidate_id: 'candidate-current', candidate_checksum: 'a'.repeat(64), release_id: null, files: [], manifest: { client_id: 'client-a' } };
    render(<DeploymentPackageView projectId="project-a" workflowStages={stage} identity={consultant} clientId="client-a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Download source bundle ZIP' }));
    await waitFor(() => expect(downloadApiFile).toHaveBeenCalledWith('/api/projects/project-a/package/download', 'project-project-a-package.zip'));
    expect(requestJson).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Download', exact: true }));
    await waitFor(() => expect(downloadApiFile).toHaveBeenCalledWith('/api/projects/project-a/package/releases/release-old/download', 'release-release-old.zip'));
  });

  it('prepares a missing source bundle only for an allowed role, and downloads configured source files through the verified API', async () => {
    packageState = { available: true, kind: 'candidate', candidate_id: null, candidate_checksum: null, release_id: null,
      files: [{ name: 'PKG.pks', stage: 'SQL', revision: 1, size_bytes: 31, sha256: 'd'.repeat(64) }], manifest: { client_id: 'client-a' } };
    requestJson.mockResolvedValue({ id: 'candidate-new', checksum: 'e'.repeat(64) });
    const { rerender } = render(<DeploymentPackageView projectId="project-a" workflowStages={stage} identity={consultant} clientId="client-a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Prepare source bundle' }));
    await waitFor(() => expect(requestJson).toHaveBeenCalledWith('/api/projects/project-a/package/candidates', { method: 'POST', body: '{}' }));
    await waitFor(() => expect(downloadApiFile).toHaveBeenCalledWith('/api/projects/project-a/package/download', 'project-project-a-package.zip'));
    packageState = { ...packageState, candidate_id: 'candidate-new' };
    rerender(<DeploymentPackageView projectId="project-a" workflowStages={stage} identity={consultant} clientId="client-a" />);
    expect(screen.getByRole('button', { name: 'Download exact source file' }).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: /PKG\.pks/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Download exact source file' }));
    await waitFor(() => expect(downloadApiFile).toHaveBeenCalledWith('/api/projects/project-a/package/candidates/candidate-new/files?name=PKG.pks', 'PKG.pks'));

    packageState = { ...packageState, candidate_id: null };
    requestJson.mockClear();
    rerender(<DeploymentPackageView projectId="project-a" workflowStages={stage} identity={{ capabilities: { manage_clients: false }, clients: [] }} clientId="client-a" />);
    expect(screen.getByRole('button', { name: 'Source bundle not prepared' }).disabled).toBe(true);
    expect(requestJson).not.toHaveBeenCalled();
  });
});
