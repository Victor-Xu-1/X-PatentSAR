import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { compound, job, page, project } from './fixtures';

describe('Evidence Studio compact workspace controls', () => {
  it('uses short PDF captions while preserving explicit accessible names and keyboard switching', async () => {
    vi.spyOn(api, 'page').mockResolvedValue(page);
    const onTab = vi.fn();
    render(
      <PdfPane
        project={project}
        page={4}
        tab="original"
        selectedId={null}
        onPage={vi.fn()}
        onTab={onTab}
        onSelect={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    const original = screen.getByRole('tab', { name: '原文视图' });
    expect(original).toHaveTextContent('原文');
    expect(original).not.toHaveTextContent('视图');
    expect(screen.getByRole('tab', { name: '文本视图' })).toHaveTextContent('文本');
    expect(screen.getByRole('tab', { name: '结构标注' })).toHaveTextContent('标注');
    original.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onTab).toHaveBeenCalledExactlyOnceWith('text');
    expect(screen.getByRole('tab', { name: '文本视图' })).toHaveFocus();
  });

  it('keeps the correction header labelled without squeezing vertical text into a utility column', () => {
    render(
      <ResultsTable
        rows={[compound]}
        selected={new Set()}
        focusedId={null}
        onSelect={vi.fn()}
        onSelectPage={vi.fn()}
        onJump={vi.fn()}
        onActivitySource={vi.fn()}
        onCrop={vi.fn()}
        onReview={vi.fn()}
      />,
    );
    const header = screen.getByRole('columnheader', { name: '修正' });
    expect(header.querySelector('.column-heading > svg')).not.toBeNull();
    expect(screen.getByRole('slider', { name: '调整修正列宽' })).toHaveAttribute(
      'aria-valuenow',
      '64',
    );
    expect(screen.getByRole('button', { name: '修正 I-7' })).toBeEnabled();
  });

  it('distinguishes repeated task rows with one real timestamp without expanding technical details', async () => {
    const stopped = { ...job, status: 'interrupted' as const };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [stopped] });
    render(<JobsPage projects={[project]} ready onOpen={vi.fn()} />);
    await screen.findByRole('button', { name: project.title });
    const timestamp = document.querySelector('time.job-timestamp')!;
    expect(timestamp).toBeVisible();
    expect(timestamp).toHaveAttribute('dateTime', job.created_at);
    expect(screen.getByText('创建')).not.toBeVisible();
    expect(document.querySelector('details.job-record')).not.toHaveAttribute('open');
  });
});
