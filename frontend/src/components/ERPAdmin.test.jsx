import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ERPAdmin from './ERPAdmin';
import { adminIdentity } from '../../tests/fixtures';

function registryFixture() {
  const profile = { id: 'profile-test', display_name: 'Configured ERP', name: 'configured', vendor: 'Fixture vendor', versions: [{ id: 'version-test', version: 1, status: 'DRAFT', configuration: {}, supported_artifact_types: ['FDD'] }] };
  vi.stubGlobal('fetch', vi.fn((url) => Promise.resolve(Response.json(url === '/api/erp-profiles/admin' ? [profile] : url.endsWith('/usage') ? {} : []))));
}

describe('ERP administration capability controls', () => {
  it('allows configuration but disables publishing for a configurator', async () => {
    registryFixture();
    render(<ERPAdmin identity={{ ...adminIdentity, capabilities: { manage_clients: false, configure_erp: true, publish_erp: false } }} />);
    fireEvent.click(await screen.findByRole('button', { name: /Configured ERP Fixture vendor/ }));
    expect(screen.getByRole('button', { name: 'Add ERP' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Publish version' }).disabled).toBe(true);
    expect(screen.queryByPlaceholderText(/Admin API key/)).toBeNull();
  });

  it('allows publication but disables configuration for a publisher', async () => {
    registryFixture();
    render(<ERPAdmin identity={{ ...adminIdentity, capabilities: { manage_clients: false, configure_erp: false, publish_erp: true } }} />);
    fireEvent.click(await screen.findByRole('button', { name: /Configured ERP Fixture vendor/ }));
    expect(screen.getByRole('button', { name: 'Add ERP' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Save configuration' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Publish version' }).disabled).toBe(false);
  });
});
