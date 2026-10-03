import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Compound } from '../src/api/types';
import { ExtractionNotice } from '../src/features/results/ExtractionNotice';
import { Metrics } from '../src/features/results/Metrics';
import { Pagination } from '../src/features/results/Pagination';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { compound, project } from './fixtures';

const structure: Compound = {
  ...compound,
  id: 'structure-only',
  display_id: 'Compound 2',
  record_kind: 'structure_only',
  activities: [],
};
const activity: Compound = {
  ...compound,
  id: 'activity-only',
  display_id: 'Compound 3',
  record_kind: 'activity_only',
  structure_id: null,
  structure_image_url: null,
  source: { ...compound.source, page: null, bbox: null },
  flags: ['structure_unmatched'],
};
const callbacks = () => ({
  offset: 0,
  selected: new Set<string>(),
  focusedId: null,
  onSelect: vi.fn(),
  onSelectPage: vi.fn(),
  onJump: vi.fn(),
  onActivitySource: vi.fn(),
  onCrop: vi.fn(),
  onReview: vi.fn(),
});

describe('complete information table presentation', () => {
  it('hides generated structure-only page suffixes without changing source identity or callbacks', async () => {
    const props = callbacks();
    const original = { ...structure, display_id: '未关联结构 S1 · p.4' };
    render(<ResultsTable {...props} rows={[original]} />);
    const identity = screen.getByLabelText('查看 未关联结构 S1 · p.4 结构详情');
    expect(identity).toHaveTextContent('未关联结构 S1');
    expect(identity).not.toHaveTextContent('p.4');
    await userEvent.click(identity);
    expect(props.onCrop).toHaveBeenCalledWith(original);
  });

  it('does not strip an intentionally edited compound identifier', () => {
    const edited = {
      ...structure,
      display_id: '未关联结构 User label · p.4',
      correction: { revision: 1, stale: false, has_changes: true, updated_at: '2026-10-04' },
    };
    render(<ResultsTable {...callbacks()} rows={[edited]} />);
    expect(screen.getByLabelText('查看 未关联结构 User label · p.4 结构详情')).toHaveTextContent(
      edited.display_id,
    );
  });

  it('keeps structures without activity and labels the gap without a biological conclusion', () => {
    render(<ResultsTable {...callbacks()} rows={[structure]} />);
    expect(screen.getByText('Compound 2')).toBeVisible();
    expect(screen.getByText('未关联活性')).toBeVisible();
    expect(screen.queryByText(/^(无活性|阴性)$/)).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Compound 2 结构裁图' })).toBeVisible();
    expect(screen.getByLabelText('MW 未计算')).toHaveTextContent('—');
  });

  it('retains an activity-only record with the genuine missing-crop placeholder', () => {
    render(<ResultsTable {...callbacks()} rows={[activity]} />);
    expect(screen.getByText('结构待定位')).toBeVisible();
    expect(screen.getByText('尚未绑定结构裁图')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByLabelText('放大 Compound 3 结构裁图')).toBeDisabled();
    expect(screen.getByLabelText('查看 Compound 3 结构详情')).toBeEnabled();
    expect(screen.getByTitle('抑制等级 = ++')).toHaveTextContent('++');
  });

  it('keeps all record kinds selectable, editable and navigable through the same callbacks', async () => {
    const props = callbacks();
    const matched = { ...compound, record_kind: 'structure_activity' as const };
    render(<ResultsTable {...props} rows={[matched, structure, activity]} />);
    await userEvent.click(screen.getByLabelText('选择当前页全部化合物'));
    expect(props.onSelectPage).toHaveBeenCalledExactlyOnceWith(true);
    for (const row of [structure, activity]) {
      await userEvent.click(screen.getByLabelText('选择化合物 ' + row.display_id));
      await userEvent.click(screen.getByLabelText('修正 ' + row.display_id));
      expect(props.onSelect).toHaveBeenCalledWith(row.id);
      expect(props.onReview).toHaveBeenCalledWith(row);
    }
    await userEvent.click(screen.getByLabelText('Compound 2 结构来源第 4 页'));
    expect(props.onJump).toHaveBeenCalledExactlyOnceWith(structure);
    await userEvent.click(screen.getByLabelText('Compound 3 抑制等级 活性来源第 5 页'));
    expect(props.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      activity,
      activity.activities[0],
      undefined,
    );
  });

  it('does not label a hidden metric or a legacy empty record as structure-only', () => {
    const { rerender } = render(
      <ResultsTable {...callbacks()} rows={[compound]} metrics={['IC50']} />,
    );
    expect(screen.queryByText('未关联活性')).not.toBeInTheDocument();
    expect(screen.getByLabelText('IC50 该指标无数据')).toBeVisible();
    rerender(<ResultsTable {...callbacks()} rows={[{ ...compound, activities: [] }]} />);
    expect(screen.queryByText('未关联活性')).not.toBeInTheDocument();
    expect(screen.queryByText('结构待定位')).not.toBeInTheDocument();
  });

  it('does not suppress explicitly retained structure-only gaps when no metrics are selected', () => {
    render(<ResultsTable {...callbacks()} rows={[structure]} metrics={[]} />);
    expect(screen.getByText('未关联活性')).toBeVisible();
    expect(screen.getAllByRole('row')).toHaveLength(2);
  });

  it('preserves a real zero measurement instead of converting it into a missing-activity label', () => {
    render(
      <ResultsTable
        {...callbacks()}
        rows={[
          {
            ...compound,
            record_kind: 'structure_activity',
            activities: [{ ...compound.activities[0]!, value: 0 }],
          },
        ]}
      />,
    );
    expect(screen.getByTitle('抑制等级 = 0')).toHaveTextContent('0');
    expect(screen.queryByText('未关联活性')).not.toBeInTheDocument();
  });

  it('shows effective activity edits without rewriting the original source classification', () => {
    render(
      <ResultsTable
        {...callbacks()}
        rows={[
          {
            ...structure,
            activities: [{ ...compound.activities[0]!, value: 18.2, unit: 'nM' }],
          },
        ]}
      />,
    );
    expect(screen.getByTitle('抑制等级 = 18.2 nM')).toHaveTextContent('18.2 nM');
    expect(screen.queryByText('未关联活性')).not.toBeInTheDocument();
  });
});

describe('minimal source-provided coverage information', () => {
  it('shows real coverage in the existing on-demand statistics, without additional cards', () => {
    render(
      <Metrics
        project={{
          ...project,
          summary: { ...project.summary, structure_only: 9, activity_only: 2 },
        }}
      />,
    );
    expect(screen.getByLabelText('记录覆盖数量')).toHaveTextContent('未关联活性 9 · 结构待定位 2');
    expect(screen.getByLabelText('记录覆盖数量').closest('.metric-card')).toBeNull();
    expect(screen.getByLabelText('项目真实统计').querySelectorAll('.metric-card')).toHaveLength(6);
  });

  it('does not calculate coverage from other summary numbers when no counts were provided', () => {
    render(<Metrics project={project} />);
    expect(screen.queryByLabelText('记录覆盖数量')).not.toBeInTheDocument();
  });

  it('shows provided zero but does not convert an unknown count to zero', () => {
    render(
      <Metrics
        project={{
          ...project,
          summary: { ...project.summary, structure_only: 0, activity_only: null },
        }}
      />,
    );
    expect(screen.getByLabelText('记录覆盖数量')).toHaveTextContent('未关联活性 0');
    expect(screen.getByLabelText('记录覆盖数量')).not.toHaveTextContent('结构待定位');
  });

  it('counts table rows without claiming they are chemically unique molecules', () => {
    render(<Pagination page={1} pageSize={10} total={31} disabled={false} onChange={vi.fn()} />);
    expect(screen.getByText('共 31 条结构/活性记录 · 1–10')).toBeVisible();
  });

  it('does not promote supplemental structures through original QA acceptance', () => {
    render(
      <ExtractionNotice
        project={{
          ...project,
          summary: { ...project.summary, structure_only: 9, activity_only: 2 },
          acceptance: { state: 'accepted', errors: [] },
        }}
        job={null}
      />,
    );
    expect(
      screen.getByText('原始提取验收由确定性 QA 决定；补充记录与人工修正不改变验收。'),
    ).toBeVisible();
  });
});
