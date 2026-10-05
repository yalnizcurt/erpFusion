import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('API origin selection', () => {
  it('uses relative local paths when no deployment origin is configured', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    const { apiUrl } = await import('./api');
    expect(apiUrl('api/projects')).toBe('/api/projects');
    expect(apiUrl('/api/projects')).toBe('/api/projects');
  });

  it('normalizes the configured origin without changing endpoint paths', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test///');
    const { apiUrl } = await import('./api');
    expect(apiUrl('/api/projects?id=demo')).toBe('https://api.example.test/api/projects?id=demo');
  });
});

describe('authenticated API transport', () => {
  it('uses an in-memory bearer supplier and never sends client-supplied roles or shared admin keys', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    const { apiFetch, configureAccessTokenProvider } = await import('./api');
    const fetch = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal('fetch', fetch);
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    configureAccessTokenProvider(async () => 'fixture-token');
    await apiFetch('/api/projects');
    const options = fetch.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.get('Authorization')).toBe('Bearer fixture-token');
    expect(headers.has('X-ERP-Admin-Key')).toBe(false);
    expect(headers.has('X-ERP-Roles')).toBe(false);
    expect(options.credentials).toBe('omit');
    expect(storage).not.toHaveBeenCalled();
    configureAccessTokenProvider(null);
  });

  it('does not attach tokens to arbitrary external paths', async () => {
    const { apiFetch, configureAccessTokenProvider } = await import('./api');
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    configureAccessTokenProvider(async () => 'fixture-token');
    await expect(apiFetch('https://external.example.test/api/projects')).rejects.toThrow('application API path');
    expect(fetch).not.toHaveBeenCalled();
    configureAccessTokenProvider(null);
  });

  it('notifies the identity boundary when the authenticated session changes', async () => {
    const { configureAccessTokenProvider, subscribeAuthenticationChanges } = await import('./api');
    const changed = vi.fn();
    const unsubscribe = subscribeAuthenticationChanges(changed);
    configureAccessTokenProvider(async () => 'next-token');
    expect(changed).toHaveBeenCalledOnce();
    unsubscribe();
    configureAccessTokenProvider(null);
    expect(changed).toHaveBeenCalledOnce();
  });

  it('reports a rejected bearer token to its session owner without treating permission denial as logout', async () => {
    const { apiFetch, configureAccessTokenProvider } = await import('./api');
    const rejected = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 403 })).mockResolvedValueOnce(new Response(null, { status: 401 })));
    configureAccessTokenProvider(async () => 'fixture-access-token', rejected);
    await apiFetch('/api/projects'); expect(rejected).not.toHaveBeenCalled();
    await apiFetch('/api/projects'); expect(rejected).toHaveBeenCalledWith('fixture-access-token');
    configureAccessTokenProvider(null);
  });
});
