import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { api } from '../src/api';
import type { Filters } from '../src/api/types';
import type { CorrectionDocument } from '../src/api/correctionTypes';
import { setLocale, UiError, errorText, useTranslation } from '../src/i18n';
import { englishCatalog } from '../src/i18n/catalog';
import { workbench } from '../src/i18n/catalogs/workbench';
import { resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compileColumnFilter } from '../src/model/columnFilters';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { CorrectionDialog } from '../src/features/results/CorrectionDialog';
import { PageControls } from '../src/features/pdf/PageControls';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { WorkspaceLayout } from '../src/features/workspace/WorkspaceLayout';
import { ColumnMenu } from '../src/features/results/ColumnMenu';
import { TableCopyButton } from '../src/features/results/TableCopyButton';
import { ExportDialog } from '../src/features/results/ExportDialog';
import { CropDialog } from '../src/features/results/CropDialog';
import { EvidencePanel } from '../src/features/analysis/EvidencePanel';
import StructureEditor from '../src/features/results/StructureEditor';
import { EDITOR_CHANNEL, readEditorMessage } from '../src/features/structure-editor/protocol';
import { strengthScaleText } from '../src/model/activityStrength';
import { filterLabels } from '../src/model/columnFilters';
import { defaultLayout } from '../src/model/layout';
import { stageLabel, stageStatusText } from '../src/model/extraction';
import { compound, page, project, results } from './fixtures';
import { evidence } from './analysis-fixtures';
import { filterValuesFixture } from './filter-value-fixtures';
import { descriptorSummary } from './descriptor-fixtures';

beforeEach(() => setLocale('en'));
afterEach(() => {
  setLocale('zh-CN');
  vi.restoreAllMocks();
});
const switchTo = (locale: 'zh-CN' | 'en') => act(() => setLocale(locale));
const activity = {
  id: 'a'.repeat(64),
  name: '原文编号',
  unit: 'nM',
  target: '保存',
  assay: '原始实验',
};
const row = {
  ...compound,
  identifier_label: '取消',
  smiles: 'C[C@H](O)Cl',
  activities: [{ ...activity, value: '< 10', page: 5 }],
};
function paneProps() {
  return {
    project,
    resource: {
      data: { ...results, items: [row], activity_columns: [activity] },
      loading: false,
      error: null,
      reload: vi.fn(),
    },
    filters: { q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 },
    selected: new Set([row.id]),
    focusedId: null,
    onFilters: vi.fn(),
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onActivitySource: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
    onExport: vi.fn(),
    onUpload: vi.fn(),
  };
}

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
  it('switches a standalone PDF control without losing its page input draft', () => {
    setLocale('zh-CN');
    const onPage = vi.fn();
    render(
      <PageControls
        page={4}
        total={12}
        zoom={1}
        disabled={false}
        onPage={onPage}
        onZoom={vi.fn()}
      />,
    );
    const input = screen.getByRole('textbox', { name: '原始文档页码' });
    fireEvent.change(input, { target: { value: '8' } });
    switchTo('en');
    expect(screen.getByRole('textbox', { name: 'Original document page' })).toBe(input);
    expect(input).toHaveValue('8');
    expect(screen.getByRole('button', { name: 'Document tools' })).toBeEnabled();
    switchTo('zh-CN');
    expect(screen.getByRole('textbox', { name: '原始文档页码' })).toBe(input);
    fireEvent.submit(input.closest('form')!);
    expect(onPage).toHaveBeenCalledWith(8);
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
  it('keeps correction and drawing instances, drafts and saved error descriptors on switch-back', async () => {
    setLocale('zh-CN');
    const fields = { display_id: row.display_id, smiles: row.smiles, activities: row.activities };
    const correction: CorrectionDocument = {
      source_fingerprint: 'b'.repeat(64),
      basis_fingerprint: null,
      revision: 0,
      stale: false,
      has_changes: false,
      original: fields,
      values: fields,
      updated_at: null,
    };
    const get = vi.spyOn(api, 'getCorrection').mockResolvedValue(correction);
    const save = vi.spyOn(api, 'saveCorrection').mockRejectedValue(new UiError('修正保存失败。'));
    const onSaved = vi.fn();
    render(
      <CorrectionDialog
        projectId={project.id}
        compound={row}
        activityColumns={[activity]}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );
    const id = await screen.findByRole('textbox', { name: '修正化合物编号' });
    const frame = screen.getByTitle('Ketcher 结构绘制与预览');
    fireEvent.change(id, { target: { value: '用户编号 7A' } });
    const metric = screen.getByRole('textbox', { name: '修正 LogP' });
    fireEvent.change(metric, { target: { value: 'NaN' } });
    act(() =>
      window.dispatchEvent(
        new MessageEvent('message', {
          origin: window.location.origin,
          source: (frame as HTMLIFrameElement).contentWindow,
          data: { channel: EDITOR_CHANNEL, kind: 'loaded' },
        }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await screen.findByText('LogP 必须是有限数字，或留空。');
    expect(save).not.toHaveBeenCalled();
    switchTo('en');
    expect(screen.getByText('LogP must be a finite number or blank.')).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Correct LogP' })).toBe(metric);
    expect(metric).toHaveValue('NaN');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    switchTo('zh-CN');
    fireEvent.change(metric, { target: { value: '-1.25' } });
    fireEvent.click(screen.getByRole('button', { name: '保存修正' }));
    await screen.findByText('修正保存失败。');
    switchTo('en');
    expect(screen.getByRole('textbox', { name: 'Correct compound ID' })).toBe(id);
    expect(id).toHaveValue('用户编号 7A');
    expect(screen.getByRole('textbox', { name: 'Correct LogP' })).toBe(metric);
    expect(metric).toHaveValue('-1.25');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    expect(screen.getByText('Could not save the correction.')).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByTitle('Ketcher 结构绘制与预览')).toBe(frame);
    expect(screen.getByText('修正保存失败。')).toBeVisible();
    await waitFor(() => expect(get).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledOnce();
    expect(onSaved).not.toHaveBeenCalled();
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

function FilterMenu({
  onFilters,
  columnId = 'compound',
}: {
  onFilters: (patch: Partial<Filters>) => void;
  columnId?: string;
}) {
  useTranslation();
  return (
    <ColumnMenu
      projectId={project.id}
      column={resultColumns().find((column) => column.id === columnId)!}
      filters={paneProps().filters}
      onFilters={onFilters}
      onHide={vi.fn()}
    />
  );
}
function frameMessage(frame: HTMLIFrameElement, payload: object) {
  act(() =>
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { channel: EDITOR_CHANNEL, ...payload },
      }),
    ),
  );
}

describe('English workbench view and live language continuity', () => {
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
      Object.assign(Object.create(navigator), { clipboard: { writeText: write } }),
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
  it('localizes PDF controls and source captions while preserving patent text and the page request identity', async () => {
    const raw = '原文编号：用户专利原始文本 < 10 nM C[C@H](O)Cl';
    const getPage = vi.spyOn(api, 'page').mockResolvedValue({ ...page, text: raw });
    render(
      <PdfPane
        project={project}
        page={4}
        tab="text"
        selectedId={null}
        onPage={vi.fn()}
        onTab={vi.fn()}
        onSelect={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    expect(await screen.findByText(raw)).toBeVisible();
    expect(screen.getByText('Native PDF text')).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText(raw)).toBeVisible();
    expect(screen.getByText('原生 PDF 文本')).toBeVisible();
    switchTo('en');
    expect(screen.getByText(raw)).toBeVisible();
    expect(getPage).toHaveBeenCalledOnce();
  });
  it('keeps workspace source/results nodes stable while changing layout controls and accessible widths', () => {
    const change = vi.fn();
    render(
      <WorkspaceLayout
        layout={defaultLayout}
        onChange={change}
        source={<input aria-label="test-source" defaultValue="用户输入" />}
        results={<div data-testid="test-results">原文编号</div>}
      />,
    );
    const input = screen.getByRole('textbox', { name: 'test-source' });
    const result = screen.getByTestId('test-results');
    const separator = screen.getByRole('slider', { name: 'Resize original and results panes' });
    expect(separator).toHaveAttribute('aria-valuetext', 'Original 34%, results 66%');
    switchTo('zh-CN');
    expect(screen.getByRole('slider', { name: '调整原文与结果宽度' })).toBe(separator);
    expect(separator).toHaveAttribute('aria-valuetext', '原文 34%，结果 66%');
    switchTo('en');
    expect(screen.getByRole('textbox', { name: 'test-source' })).toBe(input);
    expect(screen.getByTestId('test-results')).toBe(result);
    expect(input).toHaveValue('用户输入');
    expect(change).not.toHaveBeenCalled();
  });
  it('localizes evidence statistics and controls without translating raw QA findings, target names or limitations', async () => {
    const raw = '原文编号：保存，原始 QA 诊断';
    const get = vi.spyOn(api, 'evidenceSummary').mockResolvedValue({
      ...evidence,
      acceptance: { state: 'failed', errors: [raw] },
      targets: [{ name: '保存', rows: 2 }],
      activities: [{ ...evidence.activities[0]!, name: '原文编号', target: '保存' }],
    });
    render(<EvidencePanel project={project} onSource={vi.fn()} />);
    expect(await screen.findByText('Structure observations')).toBeVisible();
    expect(screen.getByText('保存 · 2 rows')).toBeVisible();
    expect(screen.getByRole('rowheader', { name: '原文编号' })).toBeInTheDocument();
    fireEvent.click(screen.getByText('View core acceptance issues (Other checks: 1)'));
    expect(screen.getByText(raw)).toBeVisible();
    fireEvent.click(screen.getByText('Statistical scope and evidence limits'));
    expect(screen.getByText(evidence.limitations[0]!)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText(raw)).toBeVisible();
    switchTo('en');
    expect(screen.getByText(raw)).toBeVisible();
    expect(get).toHaveBeenCalledOnce();
  });
  it('presents recognition and independent descriptors in English while retaining their original observations', () => {
    render(
      <CropDialog
        projectId={project.id}
        compound={{
          ...row,
          confidence: { ...row.confidence, reason: '原始绑定诊断' },
          descriptors: descriptorSummary,
          recognition: {
            status: 'valid',
            quality_flag: null,
            model_fingerprint: 'raw-model-id',
            token_confidence: { minimum: 0.4, mean: 0.8 },
          },
        }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('Five calculations · Calculated; LogS · Not calculated')).toBeVisible();
    fireEvent.click(screen.getByText('Original extraction evidence / validation'));
    expect(screen.getByText('RDKit parsable')).toBeVisible();
    expect(screen.getByText('raw-model-id')).toBeVisible();
    expect(screen.getByText(/原始绑定诊断/)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText('RDKit 可解析')).toBeVisible();
    switchTo('en');
    expect(screen.getByText('raw-model-id')).toBeVisible();
  });
  it('relocalizes frame-owned errors but preserves raw diagnostics and never reloads or captures the drawing on locale changes', () => {
    const ready = vi.fn(),
      change = vi.fn(),
      save = vi.fn();
    render(
      <StructureEditor
        smiles={row.smiles}
        molfile={null}
        disabled={false}
        onReady={ready}
        onChange={change}
        onSave={save}
      />,
    );
    const frame = screen.getByTitle('Ketcher structure drawing and preview') as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, 'postMessage');
    frameMessage(frame, { kind: 'loaded' });
    const source = '绘图操作失败，请重新加载编辑器。';
    frameMessage(frame, { kind: 'error', message: source, source, recoverable: true });
    expect(screen.getByText('The drawing operation failed. Reload the editor.')).toBeVisible();
    const callbacks = ready.mock.calls.length;
    switchTo('zh-CN');
    expect(screen.getByText(source)).toBeVisible();
    switchTo('en');
    expect(screen.getByTitle('Ketcher structure drawing and preview')).toBe(frame);
    expect(ready).toHaveBeenCalledTimes(callbacks);
    expect(post).not.toHaveBeenCalled();
    frameMessage(frame, { kind: 'error', message: source, recoverable: true });
    expect(screen.getByText(source)).toBeVisible();
    switchTo('zh-CN');
    switchTo('en');
    expect(screen.getByText(source)).toBeVisible();
    expect(change).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    expect(() =>
      readEditorMessage({
        channel: EDITOR_CHANNEL,
        kind: 'error',
        message: 'raw',
        source: 'x'.repeat(1001),
        recoverable: false,
      }),
    ).toThrow(UiError);
  });
  it('recomputes direct stage/color presentation without capturing a locale in source-label records', () => {
    const scale = {
      kind: 'numeric' as const,
      direction: 'lower' as const,
      rule: 'potency' as const,
      eligible: 9,
      excluded: 2,
      distinct: 9,
      strong_boundary: 3,
      medium_boundary: 6,
    };
    expect(strengthScaleText(scale)).toContain('Lower is stronger');
    expect(stageLabel('structures')).toBe('Structure segmentation');
    expect(stageStatusText(null, undefined)).toBe('Not started');
    expect(filterLabels.contains).toBe('包含');
    switchTo('zh-CN');
    expect(strengthScaleText(scale)).toContain('越小越强');
    expect(stageLabel('structures')).toBe('结构分割');
    switchTo('en');
    expect(strengthScaleText(scale)).toContain('9 valid observations, 2 unranked');
    expect(filterLabels.contains).toBe('包含');
  });
  it('covers all marked owned source literals and preserves named placeholders in the literal-only catalog', () => {
    const root = resolve('src') + '/';
    const directories = [
      'features/results',
      'features/pdf',
      'features/analysis',
      'features/workspace',
      'features/structure-editor',
    ];
    const models = [
      'activityStrength',
      'columnFilters',
      'columnValueSelection',
      'resultColumns',
      'results',
      'extraction',
      'tableCopy',
    ];
    const files = [
      ...directories.flatMap((directory) =>
        readdirSync(root + directory)
          .filter((name) => /\.tsx?$/.test(name))
          .map((name) => root + directory + '/' + name),
      ),
      ...models.map((name) => root + 'model/' + name + '.ts'),
    ];
    const protocolOrIdentifier = new Set(['排序', '筛选', '未关联结构 ']);
    for (const path of files) {
      for (const [, , source] of readFileSync(path, 'utf8').matchAll(
        /(['"])([^'"\\\r\n]*[\u3400-\u9fff][^'"\\\r\n]*)\1/g,
      )) {
        if (!protocolOrIdentifier.has(source!))
          expect(englishCatalog[source!], `${path}: ${source}`).toBeTypeOf('string');
      }
    }
    const placeholders = (value: string) =>
      [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(workbench)) {
      expect(english, source).not.toMatch(/[\u3400-\u9fff]/u);
      expect(placeholders(english), source).toEqual(placeholders(source));
    }
    for (const name of ['table', 'chemistry', 'pdf', 'evidence']) {
      const catalogSource = readFileSync(root + `i18n/catalogs/${name}.ts`, 'utf8');
      expect(catalogSource).not.toMatch(/^import\s/m);
    }
    const assembly = readFileSync(root + 'i18n/catalogs/workbench.ts', 'utf8');
    expect(assembly).toContain("from '../catalogMerge'");
    expect(assembly).not.toContain("from '../catalog'");
  });
});
