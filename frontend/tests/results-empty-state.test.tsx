import { render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Filters } from '../src/api/types';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { Workspace } from '../src/features/workspace/Workspace';
import { setLocale } from '../src/i18n';
import { emptyRoute } from '../src/model/route';
import { job, project, results } from './fixtures';

function paneProps(): ComponentProps<typeof ResultsPane> {
  return {
    project,
    job,
    jobVerified: true,
    resource: {
      data: { ...results, items: [], total: 0 },
      loading: false,
      error: null,
      reload: vi.fn(),
    },
    filters: { q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 },
    selected: new Set(),
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

it('describes an active extraction awaiting rows instead of a failed match', async () => {
  vi.spyOn(api, 'results').mockResolvedValue({ ...results, items: [], total: 0 });
  render(
    <Workspace
      project={project}
      route={emptyRoute}
      navigate={vi.fn()}
      query=""
      onQuery={vi.fn()}
      ready={false}
      job={job}
      jobVerified
      onJobChange={vi.fn()}
      onProjectReload={vi.fn()}
      onUpload={vi.fn()}
      onAttach={vi.fn()}
    />,
  );
  expect(await screen.findByText('结果就绪后将自动显示')).toBeVisible();
  expect(screen.queryByText('暂无匹配的提取结果')).not.toBeInTheDocument();
});

it.each(['queued', 'running'] as const)(
  'waits for published results from the verified %s task without invented rows or writes',
  (status) => {
    const props = paneProps();
    render(<ResultsPane {...props} job={{ ...job, status }} />);
    expect(screen.getByText('结果就绪后将自动显示')).toBeVisible();
    expect(screen.getByLabelText('选择当前页全部化合物')).toBeDisabled();
    expect(screen.getByRole('button', { name: '导出结果' })).toBeDisabled();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(props.resource.reload).not.toHaveBeenCalled();
    expect(props.onFilters).not.toHaveBeenCalled();
    expect(props.onSelect).not.toHaveBeenCalled();
  },
);

it.each(['complete', 'failed', 'cancelled', 'interrupted'] as const)(
  'does not claim preparation from old running stage facts after a %s task',
  (status) => {
    render(<ResultsPane {...paneProps()} job={{ ...job, status }} />);
    expect(screen.getByText('暂无提取结果')).toBeVisible();
    expect(screen.queryByText('结果就绪后将自动显示')).not.toBeInTheDocument();
  },
);

it.each(['unverified', 'other-project', 'unknown'] as const)(
  'does not borrow active state from an %s task observation',
  (kind) => {
    render(
      <ResultsPane
        {...paneProps()}
        jobVerified={kind !== 'unverified'}
        job={
          kind === 'unknown'
            ? null
            : { ...job, project_id: kind === 'other-project' ? 'other' : project.id }
        }
      />,
    );
    expect(screen.getByText('暂无提取结果')).toBeVisible();
    expect(screen.queryByText('结果就绪后将自动显示')).not.toBeInTheDocument();
  },
);

const queryFilters: Partial<Filters>[] = [
  { q: 'missing' },
  { target: 'target' },
  { confidence: 'high' },
  { review: 'needs_review' },
  { column_filters: [{ column: 'compound', op: 'contains', value: 'missing' }] },
];
it.each(queryFilters)('retains a true no-match message for filter %j', (patch) => {
  const props = paneProps();
  render(<ResultsPane {...props} filters={{ ...props.filters, ...patch }} />);
  expect(screen.getByText('暂无匹配的提取结果')).toBeVisible();
  expect(screen.queryByText('结果就绪后将自动显示')).not.toBeInTheDocument();
  expect(props.onFilters).not.toHaveBeenCalled();
});

it.each<Partial<Filters>>([{ q: '  ' }, { sort_column: 'compound', sort_direction: 'desc' }])(
  'does not mistake whitespace or sorting for a restrictive query %j',
  (patch) => {
    const props = paneProps();
    render(<ResultsPane {...props} filters={{ ...props.filters, ...patch }} />);
    expect(screen.getByText('结果就绪后将自动显示')).toBeVisible();
  },
);

it('retains a page-empty result when the published query total is nonzero', () => {
  const props = paneProps();
  render(
    <ResultsPane
      {...props}
      resource={{ ...props.resource, data: { ...results, items: [], total: 5, page: 2 } }}
    />,
  );
  expect(screen.getByText('当前页暂无结果')).toBeVisible();
  expect(screen.queryByText('结果就绪后将自动显示')).not.toBeInTheDocument();
});

it('replaces only the empty presentation when real rows arrive, preserving source values', () => {
  const props = paneProps();
  const snapshot = JSON.stringify(results);
  const { rerender } = render(<ResultsPane {...props} />);
  expect(screen.getByText('结果就绪后将自动显示')).toBeVisible();
  rerender(
    <ResultsPane {...props} jobVerified={false} resource={{ ...props.resource, data: results }} />,
  );
  expect(screen.getByLabelText('选择化合物 I-7')).toBeVisible();
  expect(screen.getByTitle('抑制等级 = ++')).toBeVisible();
  expect(screen.queryByText('结果就绪后将自动显示')).not.toBeInTheDocument();
  expect(JSON.stringify(results)).toBe(snapshot);
});

it('keeps a result-read error visible instead of disguising it as task preparation', () => {
  const props = paneProps();
  render(
    <ResultsPane
      {...props}
      resource={{ ...props.resource, error: new Error('controlled read failure') }}
    />,
  );
  expect(screen.getByRole('alert')).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.getByText('结果就绪后将自动显示')).not.toBeVisible();
});

it('keeps initial query loading separate from a known active extraction', () => {
  const props = paneProps();
  render(<ResultsPane {...props} resource={{ ...props.resource, data: null, loading: true }} />);
  expect(screen.getByText('正在查询真实结构与活性结果…')).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.getByText('结果就绪后将自动显示')).not.toBeVisible();
});

it.each([
  ['en', 'Results will appear automatically when ready', 'No extraction results yet'],
  ['zh-CN', '结果就绪后将自动显示', '暂无提取结果'],
] as const)('renders truthful active and unknown empty states in %s', (locale, active, neutral) => {
  setLocale(locale);
  const props = paneProps();
  const { rerender } = render(<ResultsPane {...props} />);
  expect(screen.getByText(active)).toBeVisible();
  rerender(<ResultsPane {...props} jobVerified={false} />);
  expect(screen.getByText(neutral)).toBeVisible();
  expect(props.resource.reload).not.toHaveBeenCalled();
});
