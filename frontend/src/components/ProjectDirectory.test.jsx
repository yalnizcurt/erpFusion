import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ProjectDirectory from './ProjectDirectory';

const { downloadApiFile } = vi.hoisted(() => ({ downloadApiFile: vi.fn() }));
vi.mock('../api', () => ({ downloadApiFile }));
vi.mock('../hooks/useApiResource', () => ({
  useApiResource: () => ({
    data: { projects: [{ id: 'project-a', name: 'Supplier sync', client_name: 'Alpha', erp_name: 'ERP A',
      project_type: 'CUSTOM', workflow_status: 'RELEASED', package_available: true, package_kind: 'release',
      package_download_url: '/api/projects/project-a/package/download' }], total: 1, next_offset: null,
      summary: { awaiting_review: 0, ready_for_sandbox: 0, completed: 1 } },
    error: null, loading: false, reload: vi.fn(),
  }),
}));

describe('ProjectDirectory package link', () => {
  it('downloads the server provided current release URL without preparing a candidate', async () => {
    render(<ProjectDirectory onOpen={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Release', exact: true }));
    await waitFor(() => expect(downloadApiFile).toHaveBeenCalledWith('/api/projects/project-a/package/download', 'Supplier sync-release.zip'));
  });
});
