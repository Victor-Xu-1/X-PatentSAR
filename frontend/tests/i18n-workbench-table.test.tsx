import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { setLocale, UiError, errorText } from '../src/i18n';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compileColumnFilter } from '../src/model/columnFilters';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { TableCopyButton } from '../src/features/results/TableCopyButton';
import { ExportDialog } from '../src/features/results/ExportDialog';
import { LanguageSwitch } from '../src/components/LanguageSwitch';
import { project } from './fixtures';
import { filterValuesFixture } from './filter-value-fixtures';
import {
  activity,
  row,
  paneProps,
  FilterMenu,
  setupWorkbenchLocale,
  switchTo,
} from './i18n-workbench-fixtures';

setupWorkbenchLocale();

describe('workbench interface language and data boundaries', () => {
  it('recomputes column presentation and TSV headers without changing IDs, patent headers, contexts or values', () => {
    setLocale('zh-CN');
    const chinese = resultColumns([activity]);
    setLocale('en');
    const english = resultColumns([activity]);
    expect(english.map(({ id }) => id)).toEqual(chinese.map(({ id }) => id));
    expect(english.find(({ id }) => id === 'compound')?.label).toBe('Original ID');
    expect(english.find(({ id }) => id.startsWith('activity:'))).toMatchObject({
      label: '原文编号 (nM)',
      context: '保存 · 原始实验',
    });
    const fields = ['compound', 'structure', `activity:${activity.id}`];
    const copy = tableCopyText(
      [row],
      english.filter(({ id }) => fields.includes(id)),
      [activity],
    );
    expect(copy).toBe(
      'Original ID\tStructure\t原文编号 (nM) · 保存 · 原始实验\n取消\tC[C@H](O)Cl\t< 10',
    );
    setLocale('zh-CN');
    expect(resultColumns([activity])).toEqual(chinese);
  });
  it('keeps selected rows, hidden columns, open chooser and search draft across language flips', () => {
    setLocale('zh-CN');
    const props = paneProps();
    render(<ResultsPane {...props} />);
    const header = screen.getByRole('button', { name: '原文编号 列选项' });
    const rawHeader = screen.getByRole('button', {
      name: '原文编号 (nM) · 保存 · 原始实验 列选项',
    });
    fireEvent.click(screen.getByRole('button', { name: '显示列' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '显示列 LogS' }));
    const dialog = screen.getByRole('dialog');
    const search = within(dialog).getByRole('textbox', { name: '查找列' });
    fireEvent.change(search, { target: { value: 'Log' } });
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Show columns' })).toBe(dialog);
    expect(within(dialog).getByRole('textbox', { name: 'Find column' })).toBe(search);
    expect(search).toHaveValue('Log');
    expect(screen.getByRole('button', { name: 'Original ID column options' })).toBe(header);
    expect(
      screen.getByRole('button', {
        name: '原文编号 (nM) · 保存 · 原始实验 column options',
      }),
    ).toBe(rawHeader);
    expect(within(dialog).getByRole('checkbox', { name: 'Show column LogS' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select compound 取消' })).toBeChecked();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '显示列' })).toBe(dialog);
    expect(screen.getByRole('button', { name: '原文编号 列选项' })).toBe(header);
    expect(props.onFilters).not.toHaveBeenCalled();
    expect(props.resource.reload).not.toHaveBeenCalled();
  });
  it('localizes validation errors at display time without changing the compiled query', () => {
    let failure: Error | undefined;
    try {
      compileColumnFilter('property:logP', { op: 'eq', value: 'NaN', upper: '' }, 'number');
    } catch (error) {
      failure = error as Error;
    }
    expect(failure).toBeInstanceOf(UiError);
    setLocale('en');
    expect(errorText(failure!)).toContain('finite number');
    expect(
      compileColumnFilter(
        `activity:${activity.id}`,
        { op: 'eq', value: '取消', upper: '' },
        'text',
      ),
    ).toEqual([{ column: `activity:${activity.id}`, op: 'eq', value: '取消' }]);
    setLocale('zh-CN');
    expect(errorText(failure!)).toBe('比较条件需要有限数值，不能使用等级或区间文本。');
  });
});

describe('English workbench view and live language continuity', () => {
  it('preserves a nonmodal filter draft for real language-control pointer and keyboard interactions only', async () => {
    const user = userEvent.setup();
    vi.spyOn(api, 'filterValues').mockResolvedValue(
      filterValuesFixture('property:logP', ['-1.25', '2']),
    );
    const apply = vi.fn();
    render(
      <>
        <LanguageSwitch />
        <FilterMenu columnId="property:logP" onFilters={apply} />
      </>,
    );
    await user.click(screen.getByRole('button', { name: 'LogP column options' }));
    await screen.findByRole('checkbox', { name: 'Filter value -1.25' });
    await user.click(screen.getByRole('button', { name: 'Number filters' }));
    await user.type(screen.getByRole('textbox', { name: 'Filter value' }), 'NaN');
    await user.click(screen.getByRole('button', { name: 'OK' }));
    const dialog = screen.getByRole('dialog');
    await user.click(screen.getByRole('combobox', { name: 'Interface language' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Interface language' }), 'zh-CN');
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(screen.getByRole('textbox', { name: '筛选值' })).toHaveValue('NaN');
    expect(screen.getByRole('alert')).toHaveTextContent('比较条件需要有限数值');
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(apply).not.toHaveBeenCalled();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('relocalizes an existing filter validation error while retaining draft, choices and scientific query keys', async () => {
    const columnId = 'property:logP';
    const choices = vi
      .spyOn(api, 'filterValues')
      .mockResolvedValue(filterValuesFixture(columnId, ['-1.25', '2']));
    const apply = vi.fn();
    render(<FilterMenu columnId={columnId} onFilters={apply} />);
    fireEvent.click(screen.getByRole('button', { name: 'LogP column options' }));
    await screen.findByRole('checkbox', { name: 'Filter value -1.25' });
    fireEvent.click(screen.getByRole('button', { name: 'Number filters' }));
    const input = screen.getByRole('textbox', { name: 'Filter value' });
    fireEvent.change(input, { target: { value: 'NaN' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    const error = screen.getByRole('alert');
    expect(error).toHaveTextContent('Comparison requires a finite number');
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toBe(error);
    expect(error).toHaveTextContent('比较条件需要有限数值，不能使用等级或区间文本。');
    expect(screen.getByRole('textbox', { name: '筛选值' })).toBe(input);
    expect(input).toHaveValue('NaN');
    switchTo('en');
    expect(error).toHaveTextContent('Comparison requires a finite number');
    expect(choices).toHaveBeenCalledOnce();
    expect(apply).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '-1.25' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    expect(apply).toHaveBeenCalledExactlyOnceWith({
      column_filters: [{ column: columnId, op: 'eq', value: '-1.25' }],
      page: 1,
    });
  });
  it('keeps an open filter checklist and condition draft without refetching choices on a language change', async () => {
    const choices = vi
      .spyOn(api, 'filterValues')
      .mockResolvedValue(filterValuesFixture('compound', ['取消', '原文编号']));
    const apply = vi.fn();
    render(<FilterMenu onFilters={apply} />);
    fireEvent.click(screen.getByRole('button', { name: 'Original ID column options' }));
    const value = await screen.findByRole('checkbox', { name: 'Filter value 取消' });
    fireEvent.click(value);
    const dialog = screen.getByRole('dialog');
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '原文编号 列选项' })).toBe(dialog);
    expect(screen.getByRole('checkbox', { name: '筛选值 取消' })).toBe(value);
    expect(value).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: '文本筛选' }));
    const input = screen.getByRole('textbox', { name: '筛选值' });
    fireEvent.change(input, { target: { value: '用户条件' } });
    switchTo('en');
    expect(screen.getByRole('textbox', { name: 'Filter value' })).toBe(input);
    expect(input).toHaveValue('用户条件');
    expect(screen.getByRole('combobox', { name: 'Filter condition' })).toHaveValue('contains');
    expect(choices).toHaveBeenCalledOnce();
    expect(apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(apply).not.toHaveBeenCalled();
  });
  it('updates copy fallback captions and headers but retains copied scientific cells and the dialog instance', async () => {
    const write = vi.fn().mockRejectedValue(new Error('Test-only clipboard refusal'));
    vi.stubGlobal(
      'navigator',
      Object.defineProperty(Object.create(navigator), 'clipboard', {
        value: { writeText: write },
        configurable: true,
      }),
    );
    render(
      <TableCopyButton
        rows={[row]}
        selected={new Set()}
        columns={resultColumns([activity])}
        activities={[activity]}
        disabled={false}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Copy current page' }));
    const field = await screen.findByRole('textbox', { name: 'TSV for manual copying' });
    const text = (field as HTMLTextAreaElement).value;
    expect(text).toContain('Original ID\tStructure');
    const dialog = screen.getByRole('dialog');
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '复制当前页' })).toBe(dialog);
    expect(screen.getByRole('textbox', { name: '可手动复制的 TSV' })).toBe(field);
    expect((field as HTMLTextAreaElement).value.split('\n')[1]).toBe(text.split('\n')[1]);
    expect((field as HTMLTextAreaElement).value).toContain('原文编号\t结构');
    switchTo('en');
    expect(field).toHaveValue(text);
    expect(write).toHaveBeenCalledOnce();
  });
  it('retains export scope and format drafts without exporting on a language flip', () => {
    const exportCall = vi.spyOn(api, 'export');
    render(
      <ExportDialog
        project={project}
        selected={[row.id]}
        filters={paneProps().filters}
        onClose={vi.fn()}
      />,
    );
    const scope = screen.getByRole('combobox', { name: 'Export scope' });
    const format = screen.getByRole('combobox', { name: 'File format' });
    fireEvent.change(scope, { target: { value: 'all' } });
    fireEvent.change(format, { target: { value: 'json' } });
    switchTo('zh-CN');
    expect(screen.getByRole('combobox', { name: '导出范围' })).toBe(scope);
    expect(screen.getByRole('combobox', { name: '文件格式' })).toBe(format);
    switchTo('en');
    expect(scope).toHaveValue('all');
    expect(format).toHaveValue('json');
    expect(exportCall).not.toHaveBeenCalled();
  });
});
