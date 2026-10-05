const apiOrigin = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

export type AccessTokenProvider = () => Promise<string | null>;
let accessTokenProvider: AccessTokenProvider | null = null;
let authenticationRejected: ((token: string) => void) | undefined;
const authenticationListeners = new Set<() => void>();

/** The verified SSO integration supplies tokens in memory; never persist them in browser storage. */
export function configureAccessTokenProvider(provider: AccessTokenProvider | null, onRejected?: (token: string) => void): void {
  accessTokenProvider = provider;
  authenticationRejected = onRejected;
  for (const listener of authenticationListeners) listener();
}

export function subscribeAuthenticationChanges(listener: () => void): () => void {
  authenticationListeners.add(listener);
  return () => { authenticationListeners.delete(listener); };
}

/** Local requests use the Vite proxy; deployed builds can select the API origin. */
export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${apiOrigin}${normalizedPath}`;
}

export class APIError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'APIError';
  }
}

/** Attach credentials only to this application's configured API. Roles come from the server. */
export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  if (!path.startsWith('/api/')) throw new Error('An application API path is required.');
  const headers = new Headers(options.headers);
  const rejected = authenticationRejected;
  const token = await accessTokenProvider?.();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(apiUrl(path), { ...options, headers, credentials: 'omit' });
  if (response.status === 401 && token) rejected?.(token);
  return response;
}

export async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await apiFetch(path, { ...options, headers });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') {
      message = data.detail;
    } else if (response.status === 422) message = 'Some fields are invalid. Review the form and try again.';
    throw new APIError(message, response.status);
  }
  return data as T;
}

/** Downloads use the same in-memory authentication as JSON requests. */
export async function downloadApiFile(path: string, fallbackName: string): Promise<void> {
  const response = await apiFetch(path);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new APIError(body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string' ? body.detail : `Download failed (${response.status}).`, response.status);
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = disposition.match(/filename="([^"\r\n]+)"/)?.[1] || fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename;
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
