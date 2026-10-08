import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { setLocale } from '../src/i18n';
import { PageControls } from '../src/features/pdf/PageControls';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { WorkspaceLayout } from '../src/features/workspace/WorkspaceLayout';
import { EvidencePanel } from '../src/features/analysis/EvidencePanel';
import { defaultLayout } from '../src/model/layout';
import { page, project } from './fixtures';
import { evidence } from './analysis-fixtures';
import { setupWorkbenchLocale, switchTo } from './i18n-workbench-fixtures';

setupWorkbenchLocale();

describe('workbench interface language and data boundaries', () => {
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
});

describe('English workbench view and live language continuity', () => {
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
});
