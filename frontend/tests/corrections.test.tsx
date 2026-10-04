import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { decodeCorrection, decodeEditableFields } from '../src/api/correctionDecoders';
import type { CorrectionDocument } from '../src/api/correctionTypes';
import { CorrectionDialog } from '../src/features/results/CorrectionDialog';
import {
  changeStructureDraft,
  correctionDraft,
  draftFields,
} from '../src/features/results/correctionDraft';
import { compound } from './fixtures';

// UI state isolation only. Real Ketcher drawing/chemistry is verified in Chromium.
vi.mock('../src/features/results/StructureEditor', async () => {
  const { useEffect } = await vi.importActual<typeof import('react')>('react');
  return {
    default: function MockStructureEditor({
      smiles,
      onReady,
      onChange,
    }: {
      smiles: string;
      onReady: (ready: boolean) => void;
      onChange: (value: import('../src/features/results/correctionDraft').StructureChange) => void;
    }) {
      useEffect(() => {
        onReady(true);
      }, [onReady]);
      return (
        <div aria-label="结构式绘制区域">
          <button
            type="button"
            onClick={() =>
              onChange({
                smiles: 'CCO',
                molfile: 'Controlled UI transport\n\n\nV3000\nM  END\n',
                graphKey: 'CCO',
                graphChanged: true,
              })
            }
          >
            模拟画结构
          </button>
          <button
            type="button"
            aria-label="清空结构"
            onClick={() =>
              onChange({ smiles: '', molfile: null, graphKey: '', graphChanged: Boolean(smiles) })
            }
          >
            清空结构
          </button>
        </div>
      );
    },
  };
});

const fields = decodeEditableFields({
  display_id: compound.display_id,
  smiles: null,
  activities: compound.activities,
});
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
  return { projectId: 'project-contract', compound, onClose: vi.fn(), onSaved: vi.fn() };
}
async function ready() {
  await screen.findByLabelText('修正化合物编号');
  await waitFor(() => expect(screen.getByRole('button', { name: '保存修正' })).toBeEnabled());
}
describe('bounded editable correction contract', () => {
  it('preserves untouched scalar types and exact contexts; grades/ranges remain text', () => {
    expect(decodeCorrection(document).values.activities[0]?.value).toBe('++');
    const draft = correctionDraft(fields);
    expect(draftFields(draft)).toEqual(fields);
    draft.activities[0]!.value = '< 10';
    expect(draftFields(draft).activities[0]).toEqual({ ...fields.activities[0], value: '< 10' });
    draft.activities[0]!.value = '0.03';
    expect(draftFields(draft).activities[0]?.value).toBe(0.03);
    const numericText = { ...fields, activities: [{ ...fields.activities[0]!, value: '0.15' }] };
    expect(draftFields(correctionDraft(numericText)).activities[0]?.value).toBe('0.15');
  });
  it('adds only explicitly entered missing columns without inventing a patent source', () => {
    const extra = { id: 'b'.repeat(64), name: 'IC50', unit: 'nM', target: 'T', assay: 'A' };
    const draft = correctionDraft(fields, compound, [extra]);
    expect(draft.activities).toHaveLength(2);
    expect(draftFields(draft).activities).toEqual(fields.activities);
    draft.activities[1]!.value = '7.5';
    expect(draftFields(draft).activities[1]).toEqual({
      name: 'IC50',
      value: 7.5,
      unit: 'nM',
      target: 'T',
      assay: 'A',
      page: null,
    });
  });
  it('never converts untouched descriptors to overrides; binds edited values to the current drawing', () => {
    const draft = correctionDraft({ ...fields, smiles: 'CCO' });
    expect(draftFields(draft).property_overrides).toEqual({});
    draft.properties.logP = { value: '-1.2', touched: true, overridden: false };
    expect(draftFields(draft)).toMatchObject({
      property_overrides: { logP: -1.2 },
      property_basis_smiles: 'CCO',
    });
    const changed = changeStructureDraft(draft, {
      smiles: 'CCC',
      molfile: null,
      graphKey: 'new',
      graphChanged: true,
    });
    expect(draftFields(changed).property_overrides).toEqual({});
    draft.properties.hydrogen_bond_donors.value = '1.5';
    draft.properties.hydrogen_bond_donors.touched = true;
    expect(() => draftFields(draft)).toThrow();
  });
  it('retains manual blanks and repeated observations separately', () => {
    const source = {
      ...fields,
      property_overrides: { molecular_weight: null },
      activities: [...fields.activities, { ...fields.activities[0]!, value: '+' }],
    };
    const draft = correctionDraft(source);
    expect(draftFields(draft).property_overrides).toEqual({ molecular_weight: null });
    expect(draftFields(draft).activities.map((item) => item.value)).toEqual(['++', '+']);
  });
  it('rejects malformed fingerprints, controls, booleans, nonfinite properties and invalid counts', () => {
    expect(() => decodeCorrection({ ...document, source_fingerprint: 'x' })).toThrow();
    for (const value of [true, Number.NaN, Number.POSITIVE_INFINITY])
      expect(() =>
        decodeEditableFields({ ...fields, activities: [{ ...fields.activities[0], value }] }),
      ).toThrow();
    for (const property_overrides of [
      { logP: Infinity },
      { tpsa: -1 },
      { hydrogen_bond_donors: 0.5 },
      { MW: 2 },
      { logP: true },
    ])
      expect(() => decodeEditableFields({ ...fields, property_overrides })).toThrow();
    expect(() => decodeEditableFields({ ...fields, structure_molfile: 'bad\u0000' })).toThrow();
    expect(() => decodeCorrection({ ...document, revision: 0, has_changes: true })).toThrow();
  });
});
describe('online correction persistence and concurrency', () => {
  it('only exposes drawing, column values and save/cancel in the normal editing path', async () => {
    vi.spyOn(api, 'getCorrection').mockResolvedValue(document);
    render(<CorrectionDialog {...props()} />);
    await ready();
    for (const name of ['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])
      expect(screen.getByLabelText(`修正 ${name}`)).toBeVisible();
    expect(screen.getByLabelText('结构式绘制区域')).toBeVisible();
    expect(screen.queryByLabelText('修正 SMILES')).not.toBeInTheDocument();
    expect(screen.queryByText(/原始值 \/ 当前已保存值/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '复核注记' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '恢复原始值' })).not.toBeInTheDocument();
  });
  it('saves a drawn molecule, identifier, activity and metric in one bounded revision', async () => {
    vi.spyOn(api, 'getCorrection').mockResolvedValue(document);
    const save = vi.spyOn(api, 'saveCorrection').mockResolvedValue({ ...document, revision: 1 });
    const callbacks = props();
    render(<CorrectionDialog {...callbacks} />);
    await ready();
    fireEvent.change(screen.getByLabelText('修正化合物编号'), { target: { value: 'Corrected-7' } });
    await userEvent.click(screen.getByRole('button', { name: '模拟画结构' }));
    fireEvent.change(screen.getByLabelText('修正 抑制等级 1'), { target: { value: '+' } });
    fireEvent.change(screen.getByLabelText('修正 MW'), { target: { value: '48.2' } });
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    const saved = save.mock.calls[0]!;
    expect(saved.slice(0, 3)).toEqual(['project-contract', compound.id, document]);
    expect(saved[3]).toMatchObject({
      display_id: 'Corrected-7',
      activities: [{ ...fields.activities[0], value: '+' }],
      property_overrides: { molecular_weight: 48.2 },
    });
    expect(saved[3].smiles).toBeTruthy();
    expect(saved[3].structure_molfile).toContain('V3000');
    expect(saved[3].property_basis_smiles).toBe(saved[3].smiles);
    expect(callbacks.onSaved).toHaveBeenCalledOnce();
  });
  it('clears a structure only on an intentional action', async () => {
    vi.spyOn(api, 'getCorrection').mockResolvedValue({
      ...document,
      values: { ...fields, smiles: 'CCO' },
    });
    const save = vi.spyOn(api, 'saveCorrection').mockResolvedValue({ ...document, revision: 1 });
    render(<CorrectionDialog {...props()} />);
    await ready();
    await userEvent.click(screen.getByLabelText('清空结构'));
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    expect(save.mock.calls[0]?.[3]).toMatchObject({
      smiles: null,
      structure_molfile: null,
      property_overrides: {},
    });
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
    await ready();
    const id = screen.getByLabelText('修正化合物编号');
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
    await ready();
    fireEvent.change(screen.getByLabelText('修正化合物编号'), { target: { value: 'Saved-7' } });
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await userEvent.click(await screen.findByRole('button', { name: '检查已保存状态并保留草稿' }));
    await waitFor(() => expect(callbacks.onSaved).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledOnce();
  });
  it('keeps validation failures editable and cancel never writes', async () => {
    vi.spyOn(api, 'getCorrection').mockResolvedValue(document);
    const save = vi.spyOn(api, 'saveCorrection');
    const callbacks = props();
    render(<CorrectionDialog {...callbacks} />);
    await ready();
    fireEvent.change(screen.getByLabelText('修正 HBD'), { target: { value: '0.5' } });
    await userEvent.click(screen.getByRole('button', { name: '保存修正' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(save).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(callbacks.onClose).toHaveBeenCalledOnce();
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
