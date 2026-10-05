import { useState } from 'react';
import type { Client } from '../contracts/identity';
import { useApiResource } from './useApiResource';

const pageSize = 25;

export function useClientDirectory() {
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({ search, limit: String(pageSize), offset: String(offset) });
  const resource = useApiResource<Client[]>(`/api/clients?${query}`);
  return {
    ...resource, search, offset,
    hasNext: resource.data?.length === pageSize,
    changeSearch(value: string) { setSearch(value); setOffset(0); },
    previousPage() { setOffset((value) => Math.max(0, value - pageSize)); },
    nextPage() { setOffset((value) => value + pageSize); },
  };
}
