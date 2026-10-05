import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createArtifactPdf } from './generatePdf';

const { text } = vi.hoisted(() => ({ text: vi.fn() }));
vi.mock('jspdf', () => ({ default: vi.fn(function () { return {
  addPage: vi.fn(),
  line: vi.fn(),
  output: vi.fn(() => new Blob(['pdf'])),
  setDrawColor: vi.fn(),
  setFont: vi.fn(),
  setFontSize: vi.fn(),
  setLineWidth: vi.fn(),
  setTextColor: vi.fn(),
  splitTextToSize: (value) => String(value).split('\n'),
  text,
}; }) }));

describe('artifact PDF export', () => {
  beforeEach(() => text.mockClear());

  it('keeps nested fields and revision metadata for known and custom artifact types', async () => {
    const cases = [
      ['FDD', { attribute_mappings: [{ source_table: 'SUPPLIERS' }], assumptions: ['All suppliers are active.'] }],
      ['TDD', { technical_architecture: { package: { body: 'Nested technical detail' } } }],
      ['CONTEXT_ANALYSIS', { assumptions: ['Use approved schema'], open_questions: [{ question: 'Which ledger?' }] }],
      ['CUSTOM_STAGE', { custom_section: { custom_field: 'Preserved value' } }],
    ];
    const version = { version_number: 6, state: 'APPROVED', generated_at: '2026-10-02T09:00:00Z' };

    for (const [artifact_type, content] of cases) {
      text.mockClear();
      await createArtifactPdf({ artifact_type }, { ...version, content });
      const printed = text.mock.calls.map(([value]) => value).join('\n');
      expect(printed).toContain(`Version: v${version.version_number}`);
      expect(printed).toContain(`State: ${version.state}`);
      expect(printed).toContain(`Generated: ${version.generated_at}`);
      if (artifact_type === 'TDD') expect(printed).toContain('Nested technical detail');
      if (artifact_type === 'CONTEXT_ANALYSIS') {
        expect(printed).toContain('Use approved schema');
        expect(printed).toContain('Which ledger?');
      }
      if (artifact_type === 'CUSTOM_STAGE') expect(printed).toContain('Preserved value');
      if (artifact_type === 'FDD') {
        expect(printed).toContain('SUPPLIERS');
        expect(printed).toContain('All suppliers are active.');
      }
    }
  });
});
