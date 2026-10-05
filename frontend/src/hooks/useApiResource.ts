import { useCallback, useEffect, useState } from 'react';
import { requestJson } from '../api';

interface Snapshot<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

/** A changed scope immediately hides old data; cancelled/late responses never replace the new scope. */
export function useApiResource<T>(path: string | null, revision = 0) {
  const [reloadCount, setReloadCount] = useState(0);
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({ key: null, data: null, error: null });
  const key = path === null ? null : `${path}:${revision}:${reloadCount}`;
  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    let active = true;
    void requestJson<T>(path, { signal: controller.signal }).then(
      (data) => { if (active) setSnapshot({ key, data, error: null }); },
      (cause: unknown) => {
        if (active) setSnapshot({ key, data: null, error: cause instanceof Error ? cause.message : 'Request failed.' });
      },
    );
    return () => { active = false; controller.abort(); };
  }, [path, key]);
  const reload = useCallback(() => setReloadCount((count) => count + 1), []);
  const current = path !== null && snapshot.key === key;
  return {
    data: current ? snapshot.data : null,
    error: current ? snapshot.error : null,
    loading: path !== null && !current,
    reload,
  };
}
