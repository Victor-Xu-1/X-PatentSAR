import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { decodeEditableFields } from '../src/api/correctionDecoders';
import type { CorrectionDocument } from '../src/api/correctionTypes';
import { ColumnChooser } from '../src/features/results/ColumnChooser';
import { CorrectionDialog } from '../src/features/results/CorrectionDialog';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compound } from './fixtures';
import { filterValuesFixture } from './filter-value-fixtures';

// Field-label isolation only; no editor, chemistry or model execution is needed.
vi.mock('../src/features/results/StructureEditor', () => ({
  default: () => <div aria-label="结构式绘制区域" />,
}));

const labels = ['I-7', '001-A', '实例乙', 'Compound 5'];
const rowFor = (displayId: string) => ({
  ...compound,
  id: 'canonical-record-7',
  display_id: displayId,
});
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

describe('original identifier labels do not redefine record identity', () => {
  it('keeps the shared compound column key while naming it 原文编号', () => {
    expect(resultColumns().find((column) => column.id === 'compound')).toMatchObject({
      id: 'compound',
      label: '原文编号',
    });
  });

  it.each(labels)(
    'renders the supplied identifier %s verbatim without changing the canonical selection key',
    async (label) => {
      const row = rowFor(label);
      const snapshot = JSON.stringify(row);
      const props = callbacks();
      render(<ResultsTable {...props} rows={[row]} />);
      expect(screen.getByRole('columnheader', { name: '原文编号' })).toHaveAttribute(
        'data-column',
        'compound',
      );
      expect(screen.queryByRole('columnheader', { name: 'Compound' })).not.toBeInTheDocument();
      expect(document.querySelector('caption')).toHaveTextContent('原文编号与结构独立成列');
      expect(document.querySelector('caption')).not.toHaveTextContent('Compound');
      expect(screen.getByRole('button', { name: `查看 ${label} 结构详情` }).textContent).toBe(
        label,
      );
      await userEvent.click(screen.getByLabelText(`选择化合物 ${label}`));
      expect(props.onSelect).toHaveBeenCalledExactlyOnceWith(row.id);
      expect(document.querySelector('tbody tr')).toHaveAttribute('data-compound', row.id);
      expect(JSON.stringify(row)).toBe(snapshot);
    },
  );

  it('uses the same column label in the picker and retains compound in visibility state', async () => {
    const onHidden = vi.fn();
    render(
      <ColumnChooser
        columns={resultColumns().filter((column) => column.id === 'compound')}
        hidden={[]}
        onHidden={onHidden}
      />,
    );
    expect(screen.getByText('原文编号')).toBeVisible();
    await userEvent.click(screen.getByLabelText('显示列 原文编号'));
    expect(onHidden).toHaveBeenCalledExactlyOnceWith(['compound']);
  });

  it('renames the filter menu while keeping its API selector and applied filter key unchanged', async () => {
    const choices = vi
      .spyOn(api, 'filterValues')
      .mockResolvedValue(filterValuesFixture('compound', ['I-7', '001-A']));
    const onFilters = vi.fn();
    render(
      <ResultsTable
        {...callbacks()}
        projectId="project-contract"
        rows={[compound]}
        filters={{ q: '', target: '', confidence: '', review: '', page: 1, page_size: 10 }}
        onFilters={onFilters}
        onHideColumn={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '原文编号 列选项' }));
    const menu = screen.getByRole('dialog', { name: '原文编号 列选项' });
    await userEvent.click(await within(menu).findByLabelText('筛选值 I-7'));
    await userEvent.click(within(menu).getByRole('button', { name: '确定' }));
    expect(choices).toHaveBeenCalledWith(
      'project-contract',
      'compound',
      expect.any(Object),
      '',
      1,
      expect.any(AbortSignal),
    );
    expect(onFilters).toHaveBeenCalledExactlyOnceWith({
      column_filters: [{ column: 'compound', op: 'not_in', values: ['I-7'], include_empty: true }],
      page: 1,
    });
  });

  it('copies the renamed header but never rewrites supplied identifier values', () => {
    const rows = labels.map(rowFor);
    const snapshot = JSON.stringify(rows);
    const columns = resultColumns().filter((column) => column.id === 'compound');
    expect(tableCopyText(rows, columns, [])).toBe(['原文编号', ...labels].join('\n'));
    expect(JSON.stringify(rows)).toBe(snapshot);
  });

  it('labels the correction field 原文编号 while reading by the original canonical record key', async () => {
    const row = rowFor('实例乙');
    const fields = decodeEditableFields({
      display_id: row.display_id,
      smiles: row.smiles,
      activities: row.activities,
    });
    const correction: CorrectionDocument = {
      source_fingerprint: 'a'.repeat(64),
      basis_fingerprint: null,
      revision: 0,
      stale: false,
      has_changes: false,
      original: fields,
      values: fields,
      updated_at: null,
    };
    const read = vi.spyOn(api, 'getCorrection').mockResolvedValue(correction);
    render(
      <CorrectionDialog
        projectId="project-contract"
        compound={row}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    const input = await screen.findByLabelText('修正化合物编号');
    expect(input.closest('label')).toHaveTextContent('原文编号');
    expect(input).toHaveValue(row.display_id);
    expect(screen.getByRole('dialog')).toHaveAccessibleName(`修正 · ${row.display_id}`);
    expect(read).toHaveBeenCalledWith('project-contract', row.id, expect.any(AbortSignal));
  });

  it.each(['001-A', '编号待确认'])(
    'uses the parent-supplied readonly identifier label %s for the correction title without changing canonical lookup',
    async (identifierLabel) => {
      const row = { ...rowFor('Compound 7'), identifier_label: identifierLabel };
      const fields = decodeEditableFields({
        display_id: row.display_id,
        smiles: row.smiles,
        activities: row.activities,
      });
      const correction: CorrectionDocument = {
        source_fingerprint: 'a'.repeat(64),
        basis_fingerprint: null,
        revision: 0,
        stale: false,
        has_changes: false,
        original: fields,
        values: fields,
        updated_at: null,
      };
      const snapshot = JSON.stringify(row);
      const read = vi.spyOn(api, 'getCorrection').mockResolvedValue(correction);
      render(
        <CorrectionDialog
          projectId="project-contract"
          compound={row}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />,
      );
      await screen.findByLabelText('修正化合物编号');
      expect(screen.getByRole('dialog')).toHaveAccessibleName(`修正 · ${identifierLabel}`);
      expect(read).toHaveBeenCalledWith('project-contract', row.id, expect.any(AbortSignal));
      expect(JSON.stringify(row)).toBe(snapshot);
    },
  );
});
