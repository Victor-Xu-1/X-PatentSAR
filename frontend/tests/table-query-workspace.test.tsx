import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { filterValuesFixture } from './filter-value-fixtures';
import { api } from '../src/api';
import type { ColumnFilter } from '../src/api/types';
import { Workspace } from '../src/features/workspace/Workspace';
import { useResultsState } from '../src/features/workspace/useResultsState';
import { emptyRoute, parseRoute, routeHash } from '../src/model/route';
import type { Route } from '../src/model/route';
import type { TableQuery } from '../src/model/tableQueryRoute';
import { compound, page, project, results } from './fixtures';

const columnFilters: ColumnFilter[] = [{ column: 'compound', op: 'contains', value: 'I-7' }];
const routed: TableQuery = {
  column_filters: columnFilters,
  sort_column: 'compound',
  sort_direction: 'desc',
};
const catalog = [{ id: 'd'.repeat(64), ...compound.activities[0]! }];
const data = {
  ...results,
  activity_columns: catalog,
  items: [{ ...compound, activity_source_keys: ['a'.repeat(64)] }],
};
beforeEach(() => {
  vi.spyOn(api, 'filterValues').mockImplementation(async (_id, column) =>
    filterValuesFixture(column),
  );
});

describe('the existing route is the sole source of global column queries', () => {
  it('restores color sort from the route, resets pagination on band changes, and never retains a competing local band', async () => {
    const read = vi.spyOn(api, 'results').mockResolvedValue(data);
    const initial: TableQuery = {
      ...routed,
      sort_column: `activity:${catalog[0]!.id}`,
      sort_band: 'strong',
    };
    const { result, rerender } = renderHook(
      ({ query }: { query: TableQuery | undefined }) =>
        useResultsState(project.id, '', vi.fn(), null, vi.fn(), query),
      { initialProps: { query: initial as TableQuery | undefined } },
    );
    await waitFor(() => expect(result.current.resource.data).toBe(data));
    act(() => result.current.changeFilters({ page: 3, sort_band: 'none' }));
    expect(result.current.filters.sort_band).toBe('strong');
    rerender({ query: { ...initial, sort_band: 'none' } });
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ page: 1, sort_band: 'none' }),
        expect.any(AbortSignal),
      ),
    );
    rerender({ query: undefined });
    expect(result.current.filters.sort_band).toBe('');
  });
  it('clears obstructing column queries when a PDF annotation selects a row outside the current result page', async () => {
    const other = { ...compound, id: 'I-9', display_id: 'I-9' };
    const read = vi.spyOn(api, 'results').mockImplementation(async (_id, filters) => ({
      ...data,
      items: filters.q === other.id ? [other] : [],
      total: filters.q === other.id ? 1 : 0,
    }));
    vi.spyOn(api, 'page').mockResolvedValue({
      ...page,
      annotations: [{ ...page.annotations[0]!, compound_id: other.id }],
    });
    const navigate = vi.fn();
    function Host() {
      const [route, setRoute] = useState<Route>({
        ...emptyRoute,
        projectId: project.id,
        page: 4,
        tab: 'annotations',
        tableQuery: routed,
      });
      const [query, setQuery] = useState('');
      return (
        <Workspace
          project={project}
          route={route}
          navigate={(next) => {
            navigate(next);
            setRoute(next);
          }}
          query={query}
          onQuery={setQuery}
          ready
          job={null}
          onJobChange={vi.fn()}
          onProjectReload={vi.fn()}
          onUpload={vi.fn()}
          onAttach={vi.fn()}
        />
      );
    }
    render(<Host />);
    fireEvent.load(await screen.findByRole('img', { name: '原始专利 PDF 第 4 页' }));
    await userEvent.click(
      await screen.findByRole('button', { name: '定位化合物 I-9，证据未确认' }),
    );
    expect(navigate.mock.calls.at(-1)![0].tableQuery).toBeUndefined();
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({ compoundId: other.id, page: 4, tab: 'annotations' }),
    );
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ q: other.id, column_filters: [], sort_column: '' }),
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByRole('button', { name: '查看 I-9 结构详情' })).toBeVisible();
  });
  it('restores deep-link queries, resets page on hash changes and clears absent route fields', async () => {
    const read = vi.spyOn(api, 'results').mockResolvedValue(data);
    const onQuery = vi.fn();
    const reload = vi.fn();
    const { result, rerender } = renderHook(
      ({ query }: { query: TableQuery | undefined }) =>
        useResultsState(project.id, '', onQuery, null, reload, query),
      { initialProps: { query: routed as TableQuery | undefined } },
    );
    await waitFor(() => expect(result.current.resource.data).toBe(data));
    expect(read).toHaveBeenLastCalledWith(
      project.id,
      expect.objectContaining(routed),
      expect.any(AbortSignal),
    );
    act(() => result.current.changeFilters({ page: 3 }));
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ page: 3 }),
        expect.any(AbortSignal),
      ),
    );
    rerender({ query: { ...routed, sort_direction: 'asc' } });
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ page: 1, sort_direction: 'asc', column_filters: columnFilters }),
        expect.any(AbortSignal),
      ),
    );
    rerender({ query: undefined });
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({
          page: 1,
          column_filters: [],
          sort_column: '',
          sort_direction: 'asc',
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it('does not retain a competing local copy of route-owned filters or sorting', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(data);
    const { result, rerender } = renderHook(
      ({ query }: { query: TableQuery | undefined }) =>
        useResultsState(project.id, '', vi.fn(), null, vi.fn(), query),
      { initialProps: { query: routed as TableQuery | undefined } },
    );
    await waitFor(() => expect(result.current.resource.data).toBe(data));
    act(() => result.current.changeFilters({ column_filters: [], sort_column: '' }));
    expect(result.current.filters.column_filters).toEqual(columnFilters);
    expect(result.current.filters.sort_column).toBe('compound');
    rerender({ query: undefined });
    expect(result.current.filters.column_filters).toEqual([]);
    expect(result.current.filters.sort_column).toBe('');
  });

  it('keeps authoritative row IDs selected through sort changes but clears selection when filtering changes', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(data);
    const { result, rerender } = renderHook(
      ({ query }: { query: TableQuery }) =>
        useResultsState(project.id, '', vi.fn(), null, vi.fn(), query),
      { initialProps: { query: routed } },
    );
    await waitFor(() => expect(result.current.resource.data).toBe(data));
    act(() => result.current.toggle(compound.id));
    rerender({ query: { ...routed, sort_direction: 'asc' } });
    expect(result.current.selected.has(compound.id)).toBe(true);
    rerender({ query: { ...routed, column_filters: [] } });
    expect(result.current.selected.size).toBe(0);
  });

  it('writes menu queries to the hash and preserves PDF page, activity focus and source/crop/correction callbacks', async () => {
    const read = vi.spyOn(api, 'results').mockResolvedValue(data);
    vi.spyOn(api, 'page').mockImplementation(async (_id, number) => ({ ...page, page: number }));
    const navigate = vi.fn();
    const initial: Route = {
      ...emptyRoute,
      projectId: project.id,
      page: 4,
      activityFocus: { compoundId: compound.id, key: 'a'.repeat(64) },
      tableQuery: routed,
    };
    function Host() {
      const [route, setRoute] = useState(initial);
      return (
        <Workspace
          project={project}
          route={route}
          navigate={(next) => {
            navigate(next);
            setRoute(parseRoute(routeHash(next)));
          }}
          query=""
          onQuery={vi.fn()}
          ready
          job={null}
          onJobChange={vi.fn()}
          onProjectReload={vi.fn()}
          onUpload={vi.fn()}
          onAttach={vi.fn()}
        />
      );
    }
    render(<Host />);
    await screen.findByRole('table');
    await userEvent.click(screen.getByRole('button', { name: '原文编号 列选项' }));
    await userEvent.click(screen.getByRole('button', { name: '升序' }));
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 4,
        activityFocus: initial.activityFocus,
        tableQuery: { ...routed, sort_direction: 'asc' },
      }),
    );
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ sort_direction: 'asc' }),
        expect.any(AbortSignal),
      ),
    );
    await userEvent.click(await screen.findByRole('button', { name: '清除列筛选' }));
    await userEvent.click(await screen.findByRole('button', { name: '取消列排序' }));
    expect(navigate.mock.calls.at(-1)![0].tableQuery).toBeUndefined();
    await waitFor(() =>
      expect(read).toHaveBeenLastCalledWith(
        project.id,
        expect.objectContaining({ column_filters: [], sort_column: '' }),
        expect.any(AbortSignal),
      ),
    );
    await userEvent.click(
      await screen.findByRole('button', { name: 'I-7 抑制等级 活性来源第 5 页' }),
    );
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 5,
        activityFocus: { compoundId: compound.id, key: 'a'.repeat(64) },
      }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'I-7 结构来源第 4 页' }));
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 4, tab: 'annotations', compoundId: compound.id }),
    );
    await userEvent.click(screen.getByRole('button', { name: '查看 I-7 结构详情' }));
    expect(screen.getByRole('dialog')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '关闭对话框' }));
    const correction = vi
      .spyOn(api, 'getCorrection')
      .mockRejectedValue(new Error('isolated correction unavailable'));
    await userEvent.click(screen.getByRole('button', { name: '修正 I-7' }));
    await waitFor(() =>
      expect(correction).toHaveBeenCalledWith(project.id, compound.id, expect.any(AbortSignal)),
    );
  });
});
