import { configureAccessTokenProvider } from '../api';

type Status = 'local' | 'initializing' | 'signed_out' | 'signed_in' | 'error';
interface AuthState { configured: boolean; status: Status; error: string }
interface Configuration { issuer: string; clientId: string; authorization: string; token: string; logout: string }
interface Transaction { state: string; nonce: string; verifier: string; createdAt: number; issuer: string; clientId: string; redirectUri: string }
interface Session { accessToken: string; refreshToken: string | null; expiresAt: number; subject: string; nonce: string }

const transactionKey = 'erpfusion.oidc.transaction';
const listeners = new Set<() => void>();
let configuration: Configuration | null = null;
let session: Session | null = null;
let refresh: Promise<string> | null = null;
let initialization: Promise<void> | null = null;
let signInPending = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let epoch = 0;

function readConfiguration(): AuthState {
  const values = [import.meta.env.VITE_OIDC_ISSUER, import.meta.env.VITE_OIDC_CLIENT_ID,
    import.meta.env.VITE_OIDC_AUTHORIZATION_ENDPOINT, import.meta.env.VITE_OIDC_TOKEN_ENDPOINT,
    import.meta.env.VITE_OIDC_LOGOUT_ENDPOINT].map((value) => String(value || '').trim());
  if (values.every((value) => !value)) return { configured: false, status: 'local', error: '' };
  try {
    if (values.some((value) => !value)) throw new Error();
    const [issuer, clientId, authorization, token, logout] = values as [string, string, string, string, string];
    for (const value of [issuer, authorization, token, logout]) {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error();
    }
    if (new URL(authorization).origin !== new URL(token).origin || new URL(token).origin !== new URL(logout).origin) throw new Error();
    configuration = { issuer, clientId, authorization, token, logout };
    return { configured: true, status: 'initializing', error: '' };
  } catch { return { configured: true, status: 'error', error: 'Sign-in configuration is incomplete or invalid. Contact an administrator.' }; }
}

let snapshot = readConfiguration();
export const getOidcState = (): AuthState => snapshot;
export function subscribeOidcState(listener: () => void): () => void {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
function update(status: Status, error = '') {
  snapshot = { ...snapshot, status, error };
  for (const listener of listeners) listener();
}
function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}
function random(): string { return base64url(crypto.getRandomValues(new Uint8Array(32))); }
function callbackUri(): string { return new URL('/auth/callback', window.location.origin).href; }

/** Claims here guard UI state. API authorization still requires backend signature verification. */
function claims(token: unknown): Record<string, unknown> {
  if (typeof token !== 'string' || token.length > 16384) throw new Error('Invalid sign-in response.');
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2]) throw new Error('Invalid sign-in response.');
  try {
    const decode = (part: string): unknown => JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(part.replaceAll('-', '+').replaceAll('_', '/')), (character) => character.charCodeAt(0))));
    const header = decode(parts[0]); const payload = decode(parts[1]);
    if (!header || typeof header !== 'object' || !('alg' in header) || !['RS256', 'ES256'].includes(String(header.alg))
      || !payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error();
    return payload as Record<string, unknown>;
  } catch { throw new Error('Invalid sign-in response.'); }
}
function validateClaims(payload: Record<string, unknown>, config: Configuration): string {
  const now = Date.now() / 1000;
  if (payload.iss !== config.issuer || typeof payload.sub !== 'string' || !payload.sub
    || typeof payload.exp !== 'number' || !Number.isFinite(payload.exp) || payload.exp <= now
    || typeof payload.iat !== 'number' || !Number.isFinite(payload.iat) || payload.iat > now + 60
    || (payload.nbf !== undefined && (typeof payload.nbf !== 'number' || !Number.isFinite(payload.nbf) || payload.nbf > now + 60))) {
    throw new Error('Invalid or expired sign-in response.');
  }
  return payload.sub;
}
function audienceMatches(audience: unknown, expected: string): boolean {
  return audience === expected || (Array.isArray(audience) && audience.includes(expected));
}
function acceptTokens(data: Record<string, unknown>, nonce: string, expectedSubject?: string): Session {
  const config = configuration!;
  const id = claims(data.id_token); const access = claims(data.access_token);
  const subject = validateClaims(id, config);
  if (validateClaims(access, config) !== subject || (expectedSubject && subject !== expectedSubject)
    || !audienceMatches(id.aud, config.clientId) || (id.token_use !== undefined && id.token_use !== 'id')
    || (id.azp !== undefined && id.azp !== config.clientId) || (Array.isArray(id.aud) && id.aud.length > 1 && id.azp !== config.clientId)
    || (access.token_use !== undefined && access.token_use !== 'access')
    || (access.client_id !== undefined ? access.client_id !== config.clientId : !audienceMatches(access.aud, config.clientId))
    || (expectedSubject ? id.nonce !== undefined && id.nonce !== nonce : id.nonce !== nonce)
    || typeof data.token_type !== 'string' || data.token_type.toLowerCase() !== 'bearer'
    || typeof data.expires_in !== 'number' || !Number.isFinite(data.expires_in) || data.expires_in <= 30
    || typeof data.access_token !== 'string'
    || (data.refresh_token !== undefined && (typeof data.refresh_token !== 'string' || !data.refresh_token || data.refresh_token.length > 16384))) {
    throw new Error('Invalid sign-in response.');
  }
  const expiresAt = Math.min(Number(access.exp) * 1000, Date.now() + data.expires_in * 1000);
  if (expiresAt - Date.now() <= 30000) throw new Error('Invalid or expired sign-in response.');
  return { accessToken: data.access_token, refreshToken: typeof data.refresh_token === 'string' ? data.refresh_token : null,
    expiresAt, subject, nonce };
}
async function exchange(body: URLSearchParams): Promise<Record<string, unknown>> {
  const response = await fetch(configuration!.token, { method: 'POST', body, credentials: 'omit', redirect: 'error', cache: 'no-store',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error('Sign-in could not be completed. Please try again.');
  const text = await response.text();
  if (text.length > 65536) throw new Error('Invalid sign-in response.');
  const data: unknown = JSON.parse(text);
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid sign-in response.');
  return data as Record<string, unknown>;
}
function clearSession(message = '') {
  epoch += 1; session = null; refresh = null; clearTimeout(timer);
  update(message ? 'error' : 'signed_out', message);
  configureAccessTokenProvider(null);
}
function scheduleExpiration() {
  clearTimeout(timer);
  if (session) timer = setTimeout(() => { void accessToken().catch(() => undefined); }, Math.max(0, session.expiresAt - Date.now() - 30000));
}
async function accessToken(): Promise<string | null> {
  if (!session) return null;
  if (session.expiresAt - Date.now() > 30000) return session.accessToken;
  if (!session.refreshToken) { clearSession('Your session expired. Sign in again.'); throw new Error('Your session expired. Sign in again.'); }
  if (!refresh) {
    const previous = session; const attempt = epoch;
    refresh = (async () => {
      try {
        const data = await exchange(new URLSearchParams({ grant_type: 'refresh_token', client_id: configuration!.clientId, refresh_token: previous.refreshToken! }));
        const next = acceptTokens(data, previous.nonce, previous.subject);
        if (attempt !== epoch) throw new Error('Sign-in session changed.');
        session = { ...next, refreshToken: next.refreshToken || previous.refreshToken };
        scheduleExpiration(); return session.accessToken;
      } catch {
        if (attempt === epoch) clearSession('Your session expired. Sign in again.');
        throw new Error('Your session expired. Sign in again.');
      } finally { if (attempt === epoch) refresh = null; }
    })();
  }
  return refresh;
}

export async function beginSignIn(): Promise<void> {
  if (!configuration) { update('error', 'Sign-in is not configured. Contact an administrator.'); return; }
  if (signInPending) return;
  signInPending = true; update('initializing');
  try {
    const transaction: Transaction = { state: random(), nonce: random(), verifier: random(), createdAt: Date.now(),
      issuer: configuration.issuer, clientId: configuration.clientId, redirectUri: callbackUri() };
    const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(transaction.verifier))));
    sessionStorage.setItem(transactionKey, JSON.stringify(transaction));
    const url = new URL(configuration.authorization);
    url.search = new URLSearchParams({ response_type: 'code', client_id: configuration.clientId, redirect_uri: transaction.redirectUri,
      scope: 'openid email profile', state: transaction.state, nonce: transaction.nonce, code_challenge: challenge, code_challenge_method: 'S256' }).toString();
    window.location.assign(url.href);
  } catch { signInPending = false; update('error', 'Sign-in could not be started. Allow session storage and use a secure browser connection.'); }
}

export function initializeOidc(): Promise<void> {
  if (initialization) return initialization;
  initialization = (async () => {
    if (!configuration) return;
    if (window.location.pathname !== '/auth/callback') { update('signed_out'); return; }
    const query = new URLSearchParams(window.location.search);
    // Remove the authorization code from browser history before any API requests or UI rendering.
    window.history.replaceState(null, '', '/');
    try {
      const saved = sessionStorage.getItem(transactionKey);
      sessionStorage.removeItem(transactionKey);
      const transaction: unknown = saved ? JSON.parse(saved) : null;
      if (!transaction || typeof transaction !== 'object') throw new Error();
      const item = transaction as Transaction;
      if (typeof item.state !== 'string' || !item.state || query.getAll('state').length !== 1 || query.get('state') !== item.state
        || typeof item.nonce !== 'string' || !item.nonce || typeof item.verifier !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(item.verifier)
        || item.issuer !== configuration.issuer || item.clientId !== configuration.clientId || item.redirectUri !== callbackUri()
        || typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt) || Date.now() - item.createdAt > 600000 || item.createdAt > Date.now() + 60000
        || query.has('error') || query.getAll('code').length !== 1 || !query.get('code') || query.get('code')!.length > 4096) throw new Error();
      const data = await exchange(new URLSearchParams({ grant_type: 'authorization_code', client_id: configuration.clientId,
        code: query.get('code')!, redirect_uri: item.redirectUri, code_verifier: item.verifier }));
      session = acceptTokens(data, item.nonce); epoch += 1;
      update('signed_in');
      configureAccessTokenProvider(accessToken, (rejected) => {
        if (session?.accessToken === rejected) clearSession('Your sign-in is no longer valid. Sign in again.');
      });
      scheduleExpiration();
    } catch { clearSession('Sign-in could not be completed. Start sign-in again.'); }
  })();
  return initialization;
}

export function signOut(): void {
  clearSession();
  try { sessionStorage.removeItem(transactionKey); } catch { /* Storage may be blocked; tokens have already been discarded. */ }
  if (!configuration) return;
  const url = new URL(configuration.logout);
  url.search = new URLSearchParams({ client_id: configuration.clientId, logout_uri: new URL('/', window.location.origin).href }).toString();
  window.location.assign(url.href);
}
