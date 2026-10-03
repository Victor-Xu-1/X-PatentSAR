import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { decodeCorrection } from '../src/api/correctionDecoders';
import type { CorrectionDocument } from '../src/api/correctionTypes';
import { CorrectionDialog } from '../src/features/results/CorrectionDialog';
import { correctionDraft, draftFields } from '../src/features/results/correctionDraft';
import { compound } from './fixtures';

const fields = { display_id: compound.display_id, smiles: null, activities: compound.activities };
const document: CorrectionDocument = {
  source_fingerprint: 'a'.repeat(64),
  basis_fingerprint: null,
  revision: 0,
  stale: false,
  has_changes: false,
  original: fields,
  values: fields,
  updated_at: null,
};
afterEach(() => vi.restoreAllMocks());
function props() {
  return {
    projectId: 'project-contract',
    compound,
    onClose: vi.fn(),
    onSaved: vi.fn(),
    onReview: vi.fn(),
  };
}
describe('bounded editable correction contract', () => {
  it('accepts the source-bound empty overlay and preserves grade strings', () => {
    expect(decodeCorrection(document).values.activities[0]?.value).toBe('++');
    const draft = correctionDraft(fields);
    draft.activities[0]!.value = '< 10';
    expect(draftFields(draft).activities[0]?.value).toBe('< 10');
  });
  it('does not coerce text grades to numeric measurements', () => {
    const draft = correctionDraft(fields);
    draft.activities[0]!.valueKind = 'number';
    expect(() => draftFields(draft)).toThrow();
    draft.activities[0]!.value = '0.03';
    expect(draftFields(draft).activities[0]?.value).toBe(0.03);
  });
  it('rejects malformed fingerprints, booleans, nonfinite values and excessive pages', () => {
    expect(() => decodeCorrection({ ...document, source_fingerprint: 'x' })).toThrow();
    for (const value of [true, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(() =>
        decodeCorrection({
          ...document,
          values: { ...fields, activities: [{ ...fields.activities[0], value }] },
        }),
      ).toThrow();
    }
    const draft = correctionDraft(fields);
    draft.activities[0]!.page = '2.5';
    expect(() => draftFields(draft)).toThrow();
    expect(() => decodeCorrection({ ...document, revision: 0, has_changes: true })).toThrow();
  });
});
describe('online correction persistence and concurrency', () => {
  it('loads original values and saves identifier, SMILES and activity in one bounded revision', async () => {
    vi.spyOn(api, 'getCorrection').mockResolvedValue(document);
    const save = vi.spyOn(api, 'saveCorrection').mockResolvedValue({ ...document, revision: 1 });
    const callbacks = props();
    render(<CorrectionDialog {...callbacks} />);
    const user = userEvent.setup();
    const id = await screen.findByLabelText('修正化合物编号');
    await user.clear(id);
    await user.type(id, 'Corrected-7');
    await user.type(screen.getByLabelText('修正 SMILES'), 'CCO');
    await user.clear(screen.getByLabelText('测量 1 值'));
    await user.type(screen.getByLabelText('测量 1 值'), '+');
    await user.click(screen.getByRole('button', { name: '保存修正' }));
    expect(save).toHaveBeenCalledWith('project-contract', compound.id, document, {
      ...fields,
      display_id: 'Corrected-7',
      smiles: 'CCO',
      activities: [{ ...fields.activities[0], value: '+' }],
    });
    expect(callbacks.onSaved).toHaveBeenCalledOnce();
  });
  it('retains a draft on conflict and requires explicit save after reading latest', async () => {
    const latest = {
      ...document,
      revision: 1,
      has_changes: true,
      values: { ...fields, display_id: 'Other-7' },
    };
    const read = vi
      .spyOn(api, 'getCorrection')
      .mockResolvedValueOnce(document)
      .mockResolvedValueOnce(latest);
    const save = vi
      .spyOn(api, 'saveCorrection')
      .mockRejectedValueOnce(new ApiError(409, 'revision_conflict', '已被更新'))
      .mockResolvedValueOnce({ ...latest, revision: 2 });
    render(<CorrectionDialog {...props()} />);
    const id = await screen.findByLabelText('修正化合物编号');
    fireEvent.change(id, { target: { value: 'My-Draft' } });
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    expect(await screen.findByRole('button', { name: '检查已保存状态并保留草稿' })).toBeVisible();
    expect(screen.getByRole('button', { name: '保存修正' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '检查已保存状态并保留草稿' }));
    expect(read).toHaveBeenCalledTimes(2);
    expect(id).toHaveValue('My-Draft');
    expect(save).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    expect(save).toHaveBeenLastCalledWith('project-contract', compound.id, latest, {
      ...fields,
      display_id: 'My-Draft',
    });
  });
  it('never retries an uncertain write and can confirm it through read-only recovery', async () => {
    const saved = {
      ...document,
      revision: 1,
      has_changes: true,
      values: { ...fields, display_id: 'Saved-7' },
    };
    vi.spyOn(api, 'getCorrection').mockResolvedValueOnce(document).mockResolvedValueOnce(saved);
    const save = vi
      .spyOn(api, 'saveCorrection')
      .mockRejectedValue(new ApiError(0, 'timeout', '写入结果未知', true));
    const callbacks = props();
    render(<CorrectionDialog {...callbacks} />);
    fireEvent.change(await screen.findByLabelText('修正化合物编号'), {
      target: { value: 'Saved-7' },
    });
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await userEvent.click(await screen.findByRole('button', { name: '检查已保存状态并保留草稿' }));
    await waitFor(() => expect(callbacks.onSaved).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledOnce();
  });
  it('retains the dialog and error on unavailable source data', async () => {
    vi.spyOn(api, 'getCorrection').mockRejectedValue(new ApiError(409, 'running', '任务运行中'));
    const callbacks = props();
    render(<CorrectionDialog {...callbacks} />);
    expect(await screen.findByText('任务运行中')).toBeVisible();
    expect(screen.queryByRole('button', { name: '保存修正' })).not.toBeInTheDocument();
    expect(callbacks.onSaved).not.toHaveBeenCalled();
  });
});
