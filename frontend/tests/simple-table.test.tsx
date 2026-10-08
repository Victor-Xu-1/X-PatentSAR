import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { METRIC_SPECS } from '../src/api/predictionTypes';
import type { Compound } from '../src/api/types';
import { compound } from './fixtures';
const callbacks = () => ({
  selected: new Set<string>(),
  focusedId: null,
  onSelect: vi.fn(),
  onSelectPage: vi.fn(),
  onJump: vi.fn(),
  onActivitySource: vi.fn(),
  onCrop: vi.fn(),
  onReview: vi.fn(),
});
describe('one simple source-bound table', () => {
  it('shows exactly six properties and independent activity columns, without promoting unknown values', () => {
    render(<ResultsTable {...callbacks()} rows={[compound]} />);
    expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      '',
      '原文编号',
      '结构',
      'Lead',
      '抑制等级',
      ...METRIC_SPECS.map((spec) => spec.label),
      '原文',
      '', // Compact pencil header; accessible column name remains 修正.
    ]);
    expect(screen.getByRole('columnheader', { name: '修正', exact: true })).toBeVisible();
    expect(screen.getByTitle('抑制等级 = ++')).toHaveTextContent('++');
    expect(screen.getByLabelText('MW 未计算')).toHaveTextContent('—');
    expect(screen.queryByText('绑定证据')).not.toBeInTheDocument();
    expect(screen.queryByText('未复核')).not.toBeInTheDocument();
  });
  it('retains exact values and distinct provenance for each activity', async () => {
    const props = callbacks();
    const row = {
      ...compound,
      activities: [
        ...compound.activities,
        { ...compound.activities[0]!, name: 'IC50', value: 18.2, unit: 'nM', page: 9 },
      ],
    };
    render(<ResultsTable {...props} rows={[row]} />);
    await userEvent.click(screen.getByLabelText('I-7 IC50 活性来源第 9 页'));
    expect(props.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      row,
      row.activities[1],
      undefined,
    );
    await userEvent.click(screen.getByLabelText('修正 I-7'));
    expect(props.onReview).toHaveBeenCalledExactlyOnceWith(row);
  });
  it('displays six real-result fields but hides stale predictions', () => {
    const admet: NonNullable<Compound['admet']> = {
      status: 'complete',
      properties: METRIC_SPECS.map((spec, index) => ({ ...spec, value: index + 1 })),
      source_fingerprint: 'a'.repeat(64),
      smiles_sha256: 'b'.repeat(64),
      engine: { name: 'ADMET-AI', version: '2.0.1', model_sha256: 'c'.repeat(64) },
      generated_at: '2026-10-03T00:00:00Z',
      job_id: 'd'.repeat(32),
      warnings: [],
      error: null,
      review_only: true,
    };
    const { rerender } = render(<ResultsTable {...callbacks()} rows={[{ ...compound, admet }]} />);
    expect(screen.getByTitle('LogS · log(mol/L) · 模型预测，非专利实测')).toHaveTextContent('6');
    rerender(
      <ResultsTable
        {...callbacks()}
        rows={[{ ...compound, admet: { ...admet, status: 'stale', properties: [] } }]}
      />,
    );
    expect(screen.getByLabelText('LogS 需重算')).toHaveTextContent('—');
    expect(screen.queryByTitle('LogS · log(mol/L) · 模型预测，非专利实测')).not.toBeInTheDocument();
  });
});
