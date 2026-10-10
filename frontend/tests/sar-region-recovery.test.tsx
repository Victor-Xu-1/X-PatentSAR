import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { ApiError } from '../src/api/errors';
import { setLocale } from '../src/i18n';
import { RegionSelector } from '../src/features/sar/RegionSelector';
import { readSavedRegion } from '../src/features/sar/readSavedRegion';
import { sarDataset, sarDrawing, sarMolecule, sarRegion, studyProfile } from './sar-fixtures';

const recovered = { ...sarRegion, name: 'Region', kind: 'variable' as const };
const props = {
  dataset: sarDataset,
  reference: sarMolecule,
  onRegion: vi.fn(),
  scope: 'owned-region',
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue({ ...studyProfile, regions: [recovered] });
});
async function saveSelection() {
  fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
  await userEvent.click(screen.getByRole('button', { name: 'Atom 1 (O)' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
}

describe('explicit immutable region readback', () => {
  it('recovers a committed uncertain save using current dataset/profile reads, without another POST or automatic readback', async () => {
    const save = vi
      .spyOn(sarApi, 'saveRegion')
      .mockRejectedValue(new ApiError(503, 'lost', 'Unknown write result', true));
    const selected = vi.fn();
    render(<RegionSelector active {...props} onRegion={selected} />);
    await saveSelection();
    const check = await screen.findByRole('button', { name: 'Check saved selection' });
    expect(sarStudyApi.profile).not.toHaveBeenCalled();
    expect(sarApi.dataset).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save region' })).toBeDisabled();
    await userEvent.click(check);
    await screen.findByText('Region saved · 1 attachment points');
    expect(selected).toHaveBeenLastCalledWith(recovered);
    expect(sarStudyApi.profile).toHaveBeenCalledExactlyOnceWith(
      sarDataset.id,
      2,
      expect.any(AbortSignal),
    );
    expect(sarApi.dataset).toHaveBeenCalledExactlyOnceWith(sarDataset.id, expect.any(AbortSignal));
    expect(save).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Check saved selection' })).toBeNull();
  });
  it('keeps an unconfirmed save locked when no exact graph/atom/name/kind record can be proved', async () => {
    vi.spyOn(sarApi, 'saveRegion').mockRejectedValue(
      new ApiError(0, 'lost', 'Unknown write result', true),
    );
    vi.spyOn(sarStudyApi, 'profile').mockResolvedValue({
      ...studyProfile,
      regions: [
        { ...recovered, name: 'Other selection' },
        { ...recovered, graph_sha256: '0'.repeat(64) },
      ],
    });
    render(<RegionSelector active {...props} />);
    await saveSelection();
    await userEvent.click(await screen.findByRole('button', { name: 'Check saved selection' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Check saved selection' })).toBeEnabled(),
    );
    expect(screen.getByRole('alert')).toHaveTextContent(
      'A unique matching saved selection has not been confirmed. Check again later.',
    );
    expect(screen.queryByText('Region saved · 1 attachment points')).toBeNull();
    expect(screen.getByRole('button', { name: 'Save region' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear selection' })).toBeDisabled();
    expect(sarApi.saveRegion).toHaveBeenCalledOnce();
  });
  it('reads back a late successful save only after explicit return and does not revive an old owner', async () => {
    let resolve!: (value: typeof recovered) => void;
    const save = vi.spyOn(sarApi, 'saveRegion').mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const accepted = vi.fn();
    const { rerender } = render(<RegionSelector active {...props} onSaved={accepted} />);
    await saveSelection();
    rerender(<RegionSelector active={false} {...props} onSaved={accepted} />);
    await act(async () => resolve(recovered));
    expect(accepted).not.toHaveBeenCalled();
    rerender(<RegionSelector active {...props} onSaved={accepted} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeEnabled());
    expect(screen.queryByText('The SAR operation completed.')).toBeNull();
    await userEvent.click(await screen.findByRole('button', { name: 'Check saved selection' }));
    await screen.findByText('Region saved · 1 attachment points');
    expect(accepted).toHaveBeenCalledExactlyOnceWith(recovered);
    expect(save).toHaveBeenCalledOnce();
  });
  it('preserves the captured save and localization while a failed readback remains explicitly recoverable', async () => {
    vi.spyOn(sarApi, 'saveRegion').mockRejectedValue(
      new ApiError(503, 'lost', 'Unknown write result', true),
    );
    vi.spyOn(sarStudyApi, 'profile').mockRejectedValueOnce(
      new ApiError(503, 'read_unavailable', 'Original read failure'),
    );
    render(<RegionSelector active {...props} />);
    await saveSelection();
    await act(() => setLocale('zh-CN'));
    await userEvent.click(await screen.findByRole('button', { name: '检查已保存选区' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '检查已保存选区' })).toBeEnabled(),
    );
    expect(screen.getByRole('button', { name: '保存区域' })).toBeDisabled();
    expect(screen.getByText('Original read failure')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '检查已保存选区' }));
    await screen.findByText('区域已保存 · 1 个连接点');
    expect(sarApi.saveRegion).toHaveBeenCalledOnce();
  });
  it('keeps the check control mounted and focused while a readback is pending', async () => {
    vi.spyOn(sarApi, 'saveRegion').mockRejectedValue(
      new ApiError(503, 'lost', 'Unknown write result', true),
    );
    let resolve!: (value: typeof studyProfile) => void;
    vi.spyOn(sarStudyApi, 'profile').mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render(<RegionSelector active {...props} />);
    await saveSelection();
    const check = await screen.findByRole('button', { name: 'Check saved selection' });
    await userEvent.click(check);
    expect(check).toBeInTheDocument();
    expect(check).toBeDisabled();
    expect(check).toHaveFocus();
    await act(async () => resolve({ ...studyProfile, regions: [recovered] }));
    await screen.findByText('Region saved · 1 attachment points');
  });
  it.each([
    { dataset_id: 'other-dataset' },
    { dataset_revision: 1 },
    { molecule_id: 'other-molecule' },
    { graph_sha256: '0'.repeat(64) },
    { atom_indices: [0] },
    { name: 'Other selection' },
    { kind: 'core' as const },
  ])('rejects a record with differing identity fields %j', async (difference) => {
    vi.spyOn(sarStudyApi, 'profile').mockResolvedValue({
      ...studyProfile,
      regions: [{ ...recovered, ...difference }],
    });
    await expect(
      readSavedRegion(sarDataset.id, {
        molecule_id: sarMolecule.id,
        expected_dataset_revision: 2,
        expected_graph_sha256: sarMolecule.graph_sha256!,
        atom_indices: [1],
      }),
    ).rejects.toMatchObject({ uncertain: true, code: 'sar_region_not_confirmed' });
  });
  it.each([{ stale: true }, { revision: 3 }])(
    'fails closed before reading the profile for a changed dataset %j',
    async (changed) => {
      vi.spyOn(sarApi, 'dataset').mockResolvedValue({ ...sarDataset, ...changed });
      await expect(
        readSavedRegion(sarDataset.id, {
          molecule_id: sarMolecule.id,
          expected_dataset_revision: 2,
          expected_graph_sha256: sarMolecule.graph_sha256!,
          atom_indices: [1],
        }),
      ).rejects.toMatchObject({ uncertain: true, code: 'sar_dataset_stale' });
      expect(sarStudyApi.profile).not.toHaveBeenCalled();
    },
  );
});
