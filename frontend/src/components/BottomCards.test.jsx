import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BottomCards from './BottomCards';

const { createArtifactPdf } = vi.hoisted(() => ({ createArtifactPdf: vi.fn() }));
vi.mock('../utils/generatePdf', () => ({ createArtifactPdf }));

describe('Artifact Studio structured viewer', () => {
  it('requires confirmation of the exact artifact revision before approval', async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(<BottomCards artifact={{ artifact_type: 'FDD', current_version: 4 }}
      selectedVersion={{ version_number: 4, state: 'PENDING_HUMAN_REVIEW', content: {} }}
      canReview onApprove={onApprove} />);

    fireEvent.click(screen.getByRole('button', { name: 'Approve Gate' }));
    expect(screen.getByRole('dialog', { name: 'Approve artifact revision' }).textContent).toContain('Approve FDD v4');
    expect(onApprove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onApprove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Approve Gate' }));
    expect(screen.queryByLabelText('Review feedback')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }));
    await waitFor(() => expect(onApprove).toHaveBeenCalledOnce());
    expect(onApprove).toHaveBeenCalledWith(4);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('renders long JSON as text in its bounded code viewer', () => {
    const content = { payload: '<script>bad()</script>' + 'x'.repeat(8000) };
    const { container } = render(
      <BottomCards
        artifact={{ artifact_type: 'CONTEXT_ANALYSIS', gate_status: 'PENDING_REVIEW' }}
        selectedVersion={{ version_number: 1, state: 'PENDING_HUMAN_REVIEW', content }}
        versions={[]}
        validations={[]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'JSON', exact: true }));
    const viewer = container.querySelector('pre.code-container');
    expect(viewer?.textContent).toContain('<script>bad()</script>');
    expect(viewer?.style.maxWidth).toBe('100%');
    expect(viewer?.style.overflow).toBe('auto');
    expect(viewer?.style.overflowWrap).toBe('anywhere');
    expect(container.querySelector('script')).toBeNull();
  });

  it('preserves engineering acronyms in the artifact title', () => {
    render(<BottomCards artifact={{ artifact_type: 'FDD' }} />);
    expect(screen.getByText('FDD')).toBeTruthy();
  });

  it('exports the selected revision on demand and reports popup errors', async () => {
    const close = vi.fn();
    const popup = { location: { href: '' }, close };
    const open = vi.spyOn(window, 'open').mockReturnValue(popup);
    const createObjectURL = vi.fn().mockReturnValue('blob:artifact-pdf');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    createArtifactPdf.mockResolvedValueOnce(new Blob(['pdf']));
    const artifact = { artifact_type: 'FDD' };
    const selectedVersion = { version_number: 7, state: 'APPROVED', generated_at: '2026-10-02T09:00:00Z', content: {} };
    render(<BottomCards artifact={artifact} selectedVersion={selectedVersion} />);

    fireEvent.click(screen.getByRole('button', { name: 'View as PDF' }));
    await waitFor(() => expect(createArtifactPdf).toHaveBeenCalledWith(artifact, selectedVersion));
    await waitFor(() => expect(popup.location.href).toBe('blob:artifact-pdf'));
    expect(open).toHaveBeenCalledWith('', '_blank');

    open.mockReturnValueOnce(null);
    fireEvent.click(screen.getByRole('button', { name: 'View as PDF' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Allow pop-ups to view the PDF.');
    vi.unstubAllGlobals();
  });

  it('retains review feedback after a failed submission and does not ask for a reviewer name', async () => {
    const requestChanges = vi.fn().mockRejectedValue(new Error('Review revision changed; reload.'));
    const prompt = vi.spyOn(window, 'prompt');
    render(<BottomCards artifact={{ artifact_type: 'FDD', gate_status: 'PENDING_REVIEW', current_version: 3 }}
      selectedVersion={{ version_number: 3, state: 'PENDING_HUMAN_REVIEW', content: {} }}
      canReview onRequestChanges={requestChanges} />);
    fireEvent.click(screen.getByRole('button', { name: 'Request Changes' }));
    fireEvent.change(screen.getByLabelText('Review feedback'), { target: { value: 'Use the approved supplier mappings.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit Change Request' }));
    await screen.findByText('Review revision changed; reload.');
    expect(screen.getByLabelText('Review feedback').value).toBe('Use the approved supplier mappings.');
    expect(requestChanges).toHaveBeenCalledWith(3, undefined, 'Use the approved supplier mappings.');
    expect(prompt).not.toHaveBeenCalled();
    requestChanges.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Submit Change Request' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('hides review actions when the authenticated identity cannot review the client', () => {
    render(<BottomCards artifact={{ artifact_type: 'FDD' }} selectedVersion={{ version_number: 1, state: 'PENDING_HUMAN_REVIEW', content: {} }} />);
    expect(screen.queryByRole('button', { name: 'Request Changes' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('blocks approval while keeping correction actions available for unresolved questions', () => {
    render(<BottomCards artifact={{ artifact_type: 'CONTEXT_ANALYSIS', current_version: 1 }}
      selectedVersion={{ version_number: 1, state: 'PENDING_HUMAN_REVIEW', content: {} }}
      canReview approvalBlockers={['Provide the approved invoice schema.']} />);
    expect(screen.getByRole('button', { name: 'Approve Gate' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Request Changes' }).disabled).toBe(false);
    expect(screen.getByText('Provide the approved invoice schema.')).toBeTruthy();
  });
});
