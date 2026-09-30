const apiOrigin = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

/** Keep local Vite proxying by default; production can point at the Render API origin. */
export function apiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${apiOrigin}${normalizedPath}`;
}
