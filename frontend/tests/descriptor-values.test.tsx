import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeCompound } from '../src/api/decoders';
import { METRIC_SPECS } from '../src/api/predictionTypes';
import { PredictionCells, PredictionEvidence } from '../src/features/results/PredictionCells';
import { correctionDraft, draftFields } from '../src/features/results/correctionDraft';
import { effectiveProperty } from '../src/model/propertyValues';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compound } from './fixtures';
import { descriptorSummary, incompleteDescriptors, predictionSummary } from './descriptor-fixtures';

const failedPrediction = {
  ...predictionSummary,
  status: 'failed',
  properties: [],
  error: { code: 'model_failed', message: 'LogS producer failed' },
};
const columns = resultColumns().filter((column) => column.id.startsWith('property:'));

describe('independent effective descriptors across table, clipboard and correction', () => {
  it.each(['pending', 'failed'])('keeps five complete RDKit values while LogS is %s', (status) => {
    const row = decodeCompound({
      ...compound,
      smiles: 'CCO',
      descriptors: descriptorSummary,
      admet: {
        ...failedPrediction,
        status,
        error: status === 'failed' ? failedPrediction.error : null,
      },
    });
    render(
      <table>
        <tbody>
          <tr>
            <PredictionCells row={row} />
          </tr>
        </tbody>
      </table>,
    );
    for (const value of ['46.07', '-0.10', '20.23']) expect(screen.getByText(value)).toBeVisible();
    expect(screen.getAllByText('1')).toHaveLength(2);
    expect(
      screen.getByLabelText(`LogS ${status === 'failed' ? '计算失败' : '等待计算'}`),
    ).toBeVisible();
    const weight = document.querySelector('td[data-property="molecular_weight"]')!;
    expect(weight).toHaveAttribute('title', expect.stringContaining('结构计算，非专利实测'));
    expect(weight).not.toHaveAttribute('title', expect.stringContaining('LogS producer failed'));
    expect(tableCopyText([row], columns, [])).toBe(
      'MW\tLogP\tTPSA\tHBD\tHBA\tLogS\n46.069\t-0.1\t20.23\t1\t1\t',
    );
    const draft = correctionDraft(
      {
        display_id: row.display_id,
        smiles: row.smiles,
        activities: row.activities,
        structure_molfile: null,
        property_overrides: {},
        property_basis_smiles: null,
      },
      row,
    );
    expect(draft.properties.molecular_weight).toEqual({
      value: '46.07',
      overridden: false,
      touched: false,
    });
    expect(draft.properties.Solubility_AqSolDB.value).toBe('');
    expect(draftFields(draft).property_overrides).toEqual({});
    expect(row.admet?.status).toBe(status);
    expect(row.confidence).toEqual(compound.confidence);
  });
  it('keeps explicit manual null/value authoritative and ignores stale overrides', () => {
    const base = decodeCompound({
      ...compound,
      descriptors: descriptorSummary,
      admet: predictionSummary,
    });
    const row = {
      ...base,
      property_overrides: { molecular_weight: null, logP: -2, Solubility_AqSolDB: -5 },
    };
    expect(effectiveProperty(row, 'molecular_weight')).toEqual({ value: null, manual: true });
    expect(effectiveProperty(row, 'logP')).toEqual({ value: -2, manual: true });
    expect(effectiveProperty(row, 'Solubility_AqSolDB')).toEqual({ value: -5, manual: true });
    expect(tableCopyText([row], columns, [])).toBe(
      'MW\tLogP\tTPSA\tHBD\tHBA\tLogS\n\t-2\t20.23\t1\t1\t-5',
    );
    const stale = {
      ...row,
      correction: {
        revision: 1,
        stale: true,
        has_changes: true,
        updated_at: descriptorSummary.generated_at,
      },
    };
    expect(effectiveProperty(stale, 'molecular_weight')).toEqual({ value: 46.069, manual: false });
  });
  it('prefers independent completed descriptors over the compatible legacy six-property observation', () => {
    const row = decodeCompound({
      ...compound,
      descriptors: descriptorSummary,
      admet: {
        ...predictionSummary,
        properties: predictionSummary.properties.map((metric) => ({
          ...metric,
          value: metric.key === 'molecular_weight' ? 99 : metric.value,
        })),
      },
    });
    expect(effectiveProperty(row, 'molecular_weight')).toEqual({ value: 46.069, manual: false });
    expect(effectiveProperty(row, 'Solubility_AqSolDB')).toEqual({ value: -3.2, manual: false });
  });
  it.each(['not_run', 'pending', 'running', 'failed', 'stale', 'unavailable'])(
    'never uses a %s descriptor or ADMET observation as numeric data',
    (status) => {
      const row = decodeCompound({
        ...compound,
        descriptors: incompleteDescriptors(status),
        admet: { ...predictionSummary, status, properties: [] },
      });
      for (const spec of METRIC_SPECS)
        expect(effectiveProperty(row, spec.key)).toEqual({ value: null, manual: false });
      expect(tableCopyText([row], columns, [])).toBe('MW\tLogP\tTPSA\tHBD\tHBA\tLogS\n\t\t\t\t\t');
      const fallback = { ...row, admet: predictionSummary };
      expect(effectiveProperty(fallback, 'molecular_weight')).toEqual({
        value: 46.069,
        manual: false,
      });
    },
  );
  it('keeps legacy complete six-property results readable with omitted/null descriptors', () => {
    for (const extra of [{}, { descriptors: null }]) {
      const row = decodeCompound({ ...compound, admet: predictionSummary, ...extra });
      expect(tableCopyText([row], columns, [])).toBe(
        'MW\tLogP\tTPSA\tHBD\tHBA\tLogS\n46.069\t-0.1\t20.23\t1\t1\t-3.2',
      );
    }
  });
  it('describes each unavailable cell by its own producer, not the LogS status', () => {
    const row = decodeCompound({
      ...compound,
      descriptors: {
        ...incompleteDescriptors('failed'),
      },
      admet: { ...predictionSummary, status: 'pending', properties: [] },
    });
    render(
      <table>
        <tbody>
          <tr>
            <PredictionCells row={row} />
          </tr>
        </tbody>
      </table>,
    );
    expect(screen.getByLabelText('MW 计算失败')).toBeVisible();
    expect(screen.getByLabelText('MW 计算失败').closest('td')).toHaveAttribute(
      'title',
      '计算失败：RDKit producer failed',
    );
    expect(screen.getByLabelText('LogS 等待计算')).toBeVisible();
    expect(screen.getByLabelText('LogS 等待计算').closest('td')).not.toHaveAttribute(
      'title',
      expect.stringContaining('RDKit'),
    );
  });
  it('retains separate producer provenance in the existing on-demand evidence disclosure', () => {
    const row = decodeCompound({
      ...compound,
      descriptors: descriptorSummary,
      admet: failedPrediction,
    });
    render(<PredictionEvidence row={row} />);
    const disclosure = document.querySelector('details')!;
    expect(within(disclosure).getByText(/RDKit 2025.09.6/)).not.toBeVisible();
    fireEvent.click(disclosure.querySelector('summary')!);
    expect(within(disclosure).getByText(/RDKit 2025.09.6/)).toBeVisible();
    expect(
      within(disclosure).getByText(`算法校验：${descriptorSummary.engine.algorithm_sha256}`),
    ).toBeVisible();
    expect(within(disclosure).getByText('LogS producer failed')).toBeVisible();
    expect(within(disclosure).getByText('46.069 Dalton')).toBeVisible();
    expect(row.review).toBeNull(); // Producer observations do not approve a record.
  });
});
