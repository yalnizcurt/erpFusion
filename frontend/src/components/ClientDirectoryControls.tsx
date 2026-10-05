import type { useClientDirectory } from '../hooks/useClientDirectory';

export default function ClientDirectoryControls({ directory, onChange, disabled = false }: {
  directory: ReturnType<typeof useClientDirectory>;
  onChange: () => void;
  disabled?: boolean;
}) {
  return <div style={{ display: 'grid', gap: 8, marginBottom: 12 }}>
    <label style={{ display: 'grid', gap: 5, fontSize: 12 }}>
      Search clients
      <input type="search" value={directory.search} maxLength={255} disabled={disabled}
        onChange={(event) => { onChange(); directory.changeSearch(event.target.value); }}
        placeholder="Client name" style={{ padding: '8px 10px', width: '100%', border: '1px solid #cbd5e1', borderRadius: 6 }} />
    </label>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}>
      <button type="button" className="btn btn-secondary" disabled={disabled || directory.loading || directory.offset === 0}
        onClick={() => { onChange(); directory.previousPage(); }}>Previous clients</button>
      <span>Page {directory.offset / 25 + 1}</span>
      <button type="button" className="btn btn-secondary" disabled={disabled || directory.loading || !directory.hasNext}
        onClick={() => { onChange(); directory.nextPage(); }}>Next clients</button>
    </div>
  </div>;
}
