import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const issuer = 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_fixture';
const clientId = 'fixture-public-client';
const domain = 'https://fixture.auth.us-east-1.amazoncognito.com';
const origin = 'https://portal.example.test';
const storage = new Map<string, string>();
let location: { origin: string; pathname: string; search: string; assign: ReturnType<typeof vi.fn> };
const jwt = (payload: Record<string, unknown>) => `${btoa(JSON.stringify({ alg: 'RS256' }))}.${btoa(JSON.stringify(payload))}.fixture-signature`;
function tokens(nonce: string, overrides: Record<string, unknown> = {}) {
  const common = { iss: issuer, sub: 'fixture-user', exp: Date.now() / 1000 + 3600, iat: Date.now() / 1000 };
  return { id_token: jwt({ ...common, aud: clientId, nonce, token_use: 'id' }),
    access_token: jwt({ ...common, client_id: clientId, token_use: 'access' }),
    refresh_token: 'memory-only-refresh', token_type: 'Bearer', expires_in: 3600, ...overrides };
}
async function configure() {
  vi.stubEnv('VITE_OIDC_ISSUER', issuer); vi.stubEnv('VITE_OIDC_CLIENT_ID', clientId);
  vi.stubEnv('VITE_OIDC_AUTHORIZATION_ENDPOINT', `${domain}/oauth2/authorize`);
  vi.stubEnv('VITE_OIDC_TOKEN_ENDPOINT', `${domain}/oauth2/token`);
  vi.stubEnv('VITE_OIDC_LOGOUT_ENDPOINT', `${domain}/logout`);
  vi.stubEnv('VITE_API_BASE_URL', '');
  return import('./oidc');
}
async function beginCallback() {
  const auth = await configure();
  await auth.beginSignIn();
  const authorization = new URL(location.assign.mock.calls[0]?.[0] as string);
  location.pathname = '/auth/callback'; location.search = `?code=fixture-code&state=${authorization.searchParams.get('state')}`;
  return { auth, authorization, nonce: authorization.searchParams.get('nonce')! };
}

beforeEach(() => {
  vi.resetModules(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-02T00:00:00Z'));
  storage.clear();
  location = { origin, pathname: '/', search: '', assign: vi.fn() };
  vi.stubGlobal('window', { location, history: { replaceState: vi.fn((_state, _unused, path: string) => {
    const url = new URL(path, origin); location.pathname = url.pathname; location.search = url.search;
  }) } });
  vi.stubGlobal('sessionStorage', { getItem: (key: string) => storage.get(key) ?? null,
    setItem: vi.fn((key: string, value: string) => storage.set(key, value)), removeItem: (key: string) => storage.delete(key) });
  vi.stubGlobal('crypto', webcrypto);
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllEnvs(); });

describe('hosted browser sign-in', () => {
  it('leaves local fixtures unchanged when sign-in is not configured and rejects partial configuration', async () => {
    for (const name of ['ISSUER', 'CLIENT_ID', 'AUTHORIZATION_ENDPOINT', 'TOKEN_ENDPOINT', 'LOGOUT_ENDPOINT']) vi.stubEnv(`VITE_OIDC_${name}`, '');
    const auth = await import('./oidc');
    await auth.initializeOidc();
    expect(auth.getOidcState()).toEqual({ configured: false, status: 'local', error: '' });
    vi.resetModules(); vi.stubEnv('VITE_OIDC_ISSUER', issuer);
    const partial = await import('./oidc');
    await partial.initializeOidc();
    expect(partial.getOidcState().status).toBe('error');
    expect(partial.getOidcState().configured).toBe(true);
  });

  it('starts code + S256 PKCE with separate random state/nonce and stores only a transient transaction', async () => {
    const auth = await configure();
    await Promise.all([auth.beginSignIn(), auth.beginSignIn()]);
    expect(location.assign).toHaveBeenCalledOnce();
    const url = new URL(location.assign.mock.calls[0]?.[0] as string);
    expect(url.origin).toBe(domain);
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
    expect(url.searchParams.get('scope')).toBe('openid email profile');
    expect(url.searchParams.get('redirect_uri')).toBe(`${origin}/auth/callback`);
    expect(url.searchParams.get('state')).not.toBe(url.searchParams.get('nonce'));
    const transaction = JSON.parse([...storage.values()][0]!) as Record<string, string>;
    expect(transaction.verifier).toHaveLength(43);
    const challenge = Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(transaction.verifier))).toString('base64url');
    expect(url.searchParams.get('code_challenge')).toBe(challenge);
    expect([...storage.values()].join()).not.toContain('access_token');
  });

  it('consumes the callback once, removes its code from history and supplies only the access token in memory', async () => {
    const { auth, nonce } = await beginCallback();
    const response = tokens(nonce);
    const fetch = vi.fn((url: string) => Promise.resolve(Response.json(url === `${domain}/oauth2/token` ? response : { ok: true })));
    vi.stubGlobal('fetch', fetch);
    await Promise.all([auth.initializeOidc(), auth.initializeOidc()]);
    expect(auth.getOidcState().status).toBe('signed_in');
    expect(location.search).toBe(''); expect(location.pathname).toBe('/'); expect(storage.size).toBe(0);
    const exchange = fetch.mock.calls[0];
    expect(exchange?.[0]).toBe(`${domain}/oauth2/token`);
    expect(fetch).toHaveBeenCalledOnce();
    const { apiFetch } = await import('../api');
    await apiFetch('/api/projects');
    const options = (fetch.mock.calls[1] as unknown as [string, RequestInit])[1];
    expect(new Headers(options.headers).get('Authorization')).toBe(`Bearer ${response.access_token}`);
    expect(storage.size).toBe(0);
    expect([...storage.values()].join()).not.toContain('memory-only-refresh');
  });

  it.each(['mismatch', 'expired', 'duplicate-code', 'issuer-changed'])('rejects %s callback transactions without exchanging a code', async (failure) => {
    const { auth } = await beginCallback();
    if (failure === 'mismatch') location.search = '?code=fixture-code&state=wrong';
    if (failure === 'expired') vi.setSystemTime(Date.now() + 600001);
    if (failure === 'duplicate-code') location.search += '&code=second';
    if (failure === 'issuer-changed') {
      const key = [...storage.keys()][0]!; const transaction = JSON.parse(storage.get(key)!) as Record<string, unknown>;
      transaction.issuer = 'https://untrusted.example.test'; storage.set(key, JSON.stringify(transaction));
    }
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await auth.initializeOidc();
    expect(fetch).not.toHaveBeenCalled(); expect(storage.size).toBe(0);
    expect(auth.getOidcState().status).toBe('error'); expect(location.search).toBe('');
  });

  it.each(['nonce', 'issuer', 'audience', 'subject', 'expiry', 'token-use'])('rejects invalid %s token claims', async (failure) => {
    const { auth, nonce } = await beginCallback();
    const response = tokens(nonce);
    const common = { iss: issuer, sub: 'fixture-user', exp: Date.now() / 1000 + 3600, iat: Date.now() / 1000, aud: clientId, nonce, token_use: 'id' };
    if (failure === 'nonce') response.id_token = jwt({ ...common, nonce: 'wrong' });
    if (failure === 'issuer') response.id_token = jwt({ ...common, iss: 'https://untrusted.example.test' });
    if (failure === 'audience') response.id_token = jwt({ ...common, aud: 'another-client' });
    if (failure === 'subject') response.access_token = jwt({ ...common, sub: 'another-user', token_use: 'access', client_id: clientId });
    if (failure === 'expiry') response.id_token = jwt({ ...common, exp: Date.now() / 1000 - 1 });
    if (failure === 'token-use') response.access_token = jwt({ ...common, token_use: 'id', client_id: clientId });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(response)));
    await auth.initializeOidc();
    expect(auth.getOidcState().status).toBe('error'); expect(storage.size).toBe(0);
  });

  it('refreshes once for concurrent API requests and retains rotated tokens only in memory', async () => {
    const { auth, nonce } = await beginCallback();
    let exchanges = 0;
    const fetch = vi.fn((url: string, options?: RequestInit) => {
      if (url !== `${domain}/oauth2/token`) return Promise.resolve(Response.json({ ok: true }));
      exchanges += 1;
      expect(new URLSearchParams(String(options?.body)).get('grant_type')).toBe(exchanges === 1 ? 'authorization_code' : 'refresh_token');
      return Promise.resolve(Response.json(tokens(nonce, { refresh_token: exchanges === 1 ? 'first-refresh' : 'rotated-refresh' })));
    });
    vi.stubGlobal('fetch', fetch); await auth.initializeOidc();
    vi.setSystemTime(Date.now() + 3570001);
    const { apiFetch } = await import('../api');
    await Promise.all([apiFetch('/api/projects'), apiFetch('/api/clients')]);
    expect(exchanges).toBe(2); expect(auth.getOidcState().status).toBe('signed_in'); expect(storage.size).toBe(0);
    vi.setSystemTime(Date.now() + 3570001); await apiFetch('/api/projects');
    const grant = fetch.mock.calls.find(([, options]) => String(options?.body).includes('rotated-refresh'));
    expect(grant).toBeTruthy();
  });

  it('discards a late refresh after logout and sends the browser to the configured sign-out endpoint', async () => {
    const { auth, nonce } = await beginCallback();
    let resolveRefresh!: (value: Response) => void;
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(tokens(nonce))).mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRefresh = resolve; }));
    vi.stubGlobal('fetch', fetch); await auth.initializeOidc();
    vi.setSystemTime(Date.now() + 3570001);
    const { apiFetch } = await import('../api');
    const request = apiFetch('/api/projects');
    await Promise.resolve(); auth.signOut();
    const logout = new URL(location.assign.mock.calls.at(-1)?.[0] as string);
    expect(logout.pathname).toBe('/logout'); expect(logout.searchParams.get('client_id')).toBe(clientId);
    expect(logout.searchParams.get('logout_uri')).toBe(`${origin}/`);
    resolveRefresh(Response.json(tokens(nonce)));
    await expect(request).rejects.toThrow('session expired');
    expect(auth.getOidcState().status).toBe('signed_out'); expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('fails closed when refresh is revoked and requires sign-in again after a page reload', async () => {
    const { auth, nonce } = await beginCallback();
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(tokens(nonce))).mockResolvedValueOnce(Response.json({ error: 'invalid_grant' }, { status: 400 }));
    vi.stubGlobal('fetch', fetch); await auth.initializeOidc();
    await vi.advanceTimersByTimeAsync(3570001);
    expect(auth.getOidcState().status).toBe('error'); expect(auth.getOidcState().error).toContain('Sign in again');
    vi.resetModules();
    const reloaded = await import('./oidc'); await reloaded.initializeOidc();
    expect(reloaded.getOidcState().status).toBe('signed_out'); expect(storage.size).toBe(0);
  });
});
