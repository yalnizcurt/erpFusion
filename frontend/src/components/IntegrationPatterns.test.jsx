import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import IntegrationPatterns from './IntegrationPatterns';

const profile = { id: 'erp-1', versions: [{ id: 'profile-v1', version: 1, status: 'PUBLISHED' }] };
const version = {
  id: 'pattern-v1', version: 1, status: 'PUBLISHED', profile_version_id: 'profile-v1',
  runtime_type: 'API_INTEGRATION', direction: 'OUTBOUND', deliverable_type: 'API_MAPPING',
  qualification_strategy: 'REMOTE_API', delivery_method: 'CUSTOMER_CONTROLLED', baseline_asset_version_ids: ['baseline-v1'],
  implementation_status: 'GENERATION_SUPPORTED', configuration: { required_capabilities: ['CALL_API'], generation_rules: { strategy: 'baseline_json' } },
};
const pattern = { id: 'pattern-1', key: 'api-map', name: 'API mapping', provider: 'HighRadius', versions: [version] };

function setup(canEdit = true, canPublish = true) {
  const fetch = vi.fn((url, options = {}) => {
    if (options.method === 'POST') return Promise.resolve(Response.json({ ...version, id: 'new-version', version: 2, status: 'DRAFT' }));
    return Promise.resolve(Response.json(url.includes('/baseline-assets')
      ? [{ id: 'baseline-v1', name: 'Approved mapping', version: 1, status: 'PUBLISHED', asset_kind: 'PACKAGE' }]
      : [pattern]));
  });
  vi.stubGlobal('fetch', fetch);
  render(<IntegrationPatterns profile={profile} canEdit={canEdit} canPublish={canPublish} />);
  return fetch;
}

describe('integration pattern administration', () => {
  it('keeps published contracts immutable and clones exact baseline/intelligence references to a draft', async () => {
    const fetch = setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Open' }));
    expect(screen.getByRole('button', { name: 'Save draft pattern version' }).closest('fieldset').disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'New version from this' }));
    expect(screen.getByLabelText('Pinned ERP intelligence version').value).toBe('profile-v1');
    expect(Array.from(screen.getByLabelText('Approved baseline asset versions').selectedOptions, (option) => option.value)).toEqual(['baseline-v1']);
    fireEvent.click(screen.getByRole('button', { name: 'Save draft pattern version' }));
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => url.endsWith('/pattern-1/versions') && options?.method === 'POST')).toBe(true));
    const call = fetch.mock.calls.find(([url, options]) => url.endsWith('/pattern-1/versions') && options?.method === 'POST');
    expect(JSON.parse(call[1].body)).toMatchObject({ profile_version_id: 'profile-v1', baseline_asset_version_ids: ['baseline-v1'], runtime_type: 'API_INTEGRATION', qualification_strategy: 'REMOTE_API' });
  });

  it('clears previous pattern baselines when adding another pattern', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: 'Open' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add integration pattern' }));
    expect(screen.getByLabelText('Pattern key').value).toBe('');
    expect(screen.getByLabelText('Runtime model').value).toBe('ASSISTED');
    expect(screen.getByLabelText('Approved baseline asset versions').selectedOptions).toHaveLength(0);
  });

  it('allows a publisher to inspect and retire but prevents editing or version creation', async () => {
    setup(false, true);
    expect((await screen.findByRole('button', { name: 'Retire' })).disabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Add integration pattern' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'New version from this' }).disabled).toBe(true);
  });

  it('rejects malformed contract JSON without creating a pattern', async () => {
    const fetch = setup();
    await screen.findByRole('button', { name: 'Open' });
    fireEvent.change(screen.getByLabelText('Pattern key'), { target: { value: 'file-map' } });
    fireEvent.change(screen.getByLabelText('Pattern name'), { target: { value: 'File mapping' } });
    fireEvent.change(screen.getByLabelText(/Pattern contract/), { target: { value: '{bad' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save draft pattern version' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Pattern contract must be valid JSON.');
    expect(fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });
});
