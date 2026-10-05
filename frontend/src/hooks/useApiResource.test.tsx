import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useApiResource } from './useApiResource';

describe('scoped API resources', () => {
  it('hides old scope immediately and ignores late responses even when transport ignores cancellation', async () => {
    let finishOld: (response: Response) => void = () => {};
    const mockFetch = vi.fn((url: string) => url === '/api/clients/old'
      ? new Promise<Response>((resolve) => { finishOld = resolve; })
      : Promise.resolve(Response.json({ id: 'new' })));
    vi.stubGlobal('fetch', mockFetch);
    const { result, rerender } = renderHook(({ path }) => useApiResource<{ id: string }>(path), { initialProps: { path: '/api/clients/old' } });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    rerender({ path: '/api/clients/new' });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data?.id).toBe('new'));
    await act(async () => { finishOld(Response.json({ id: 'old' })); });
    expect(result.current.data?.id).toBe('new');
  });

  it('clears completed scope without a request when the parent selection is removed', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ id: 'old' }));
    vi.stubGlobal('fetch', fetch);
    const { result, rerender } = renderHook(({ path }: { path: string | null }) => useApiResource<{ id: string }>(path), { initialProps: { path: '/api/clients/old' as string | null } });
    await waitFor(() => expect(result.current.data?.id).toBe('old'));
    rerender({ path: null });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
