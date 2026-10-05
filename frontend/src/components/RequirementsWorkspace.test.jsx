import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import RequirementsWorkspace from './RequirementsWorkspace';

describe('explicit ERP profile upgrades', () => {
  it('requires confirmation, uses the current version as a concurrency guard and preserves unsaved edits', async () => {
    const fetch = vi.fn().mockImplementation((_url, options) => Promise.resolve(Response.json(options?.method === 'PATCH' ? {} : [])));
    vi.stubGlobal('fetch', fetch);
    const project = { id: 'project', erp_profile_id: 'erp', erp_profile_version_id: 'v1', erp_name: 'New ERP', erp_version: 1, requirement_version: 3, schema_context_version: 2, business_requirement: 'Supplier requirements', erp_schema_context: {} };
    const erpProfiles = [{ id: 'erp', profile_version_id: 'v2', profile_version: 2 }];
    const onSaved = vi.fn();
    render(<RequirementsWorkspace project={project} erpProfiles={erpProfiles} canEdit onSaved={onSaved} />);
    const upgrade = screen.getByRole('button', { name: 'Use ERP profile v2' });
    fireEvent.click(upgrade);
    expect(screen.getByRole('dialog', { name: 'Upgrade ERP profile' })).toBeTruthy();
    expect(fetch.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.change(screen.getByLabelText(/Requirement text/), { target: { value: 'Unsaved supplier edits' } });
    expect(upgrade.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Requirement text/), { target: { value: project.business_requirement } });
    fireEvent.click(upgrade);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm profile upgrade' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    const [, options] = fetch.mock.calls.find(([, value]) => value?.method === 'PATCH');
    expect(JSON.parse(options.body)).toEqual({ erp_profile_version_id: 'v2', expected_erp_profile_version_id: 'v1', expected_requirement_version: 3, expected_schema_context_version: 2 });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
