import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { Workspace } from '../src/features/workspace/Workspace';
import { emptyRoute } from '../src/model/route';
import type { Route } from '../src/model/route';
import { compound, page, project, results } from './fixtures';

const keys = ['a'.repeat(64), 'b'.repeat(64), 'c'.repeat(64)];
const row = {
  ...compound,
  activities: [
    { ...compound.activities[0]!, name: 'Ratio', value: 0.15, page: 5 },
    { ...compound.activities[0]!, name: 'Grade', value: '+++', page: 5 },
    { ...compound.activities[0]!, name: 'Ratio', value: 0.2, page: 6 },
  ],
  activity_source_keys: keys,
};
const callbacks = {
  offset: 0,
  selected: new Set<string>(),
  focusedId: null,
  onSelect: vi.fn(),
  onSelectPage: vi.fn(),
  onJump: vi.fn(),
  onActivitySource: vi.fn(),
  onCrop: vi.fn(),
  onReview: vi.fn(),
};
describe('activity value itself is the provenance control', () => {
  it('removes all visible p-number labels and keeps each repeated observation original index/key', async () => {
    render(<ResultsTable {...callbacks} rows={[row]} metrics={['Ratio', 'Grade']} />);
    const table = screen.getByRole('table');
    expect(table.textContent).not.toMatch(/p\.\d+/);
    const buttons = table.querySelectorAll('td.activity-value-column button');
    expect(Array.from(buttons, (button) => button.textContent)).toEqual(['0.15', '0.2', '+++']);
    await userEvent.click(buttons[1] as HTMLElement);
    expect(callbacks.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      row,
      row.activities[2],
      keys[2],
    );
    const source = screen.getByRole('button', { name: 'I-7 结构来源第 4 页' });
    expect(source.textContent).toBe('');
    await userEvent.click(source);
    expect(callbacks.onJump).toHaveBeenCalledWith(row);
  });
  it('retains legacy page-only navigation and disabled unknown-page values without inventing keys', async () => {
    const legacy = {
      ...compound,
      activities: [
        compound.activities[0]!,
        { ...compound.activities[0]!, value: null, page: null },
      ],
    };
    render(<ResultsTable {...callbacks} rows={[legacy]} />);
    await userEvent.click(screen.getByRole('button', { name: 'I-7 抑制等级 活性来源第 5 页' }));
    expect(callbacks.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      legacy,
      legacy.activities[0],
      undefined,
    );
    expect(screen.getByRole('button', { name: 'I-7 抑制等级 活性来源页码未知' })).toBeDisabled();
    expect(screen.getByRole('table').textContent).not.toContain('来源未知');
  });
  it('keeps repeated identical observations bound to their own index and supports keyboard activation', async () => {
    const activity = row.activities[0]!;
    const repeated = {
      ...row,
      activities: [activity, activity],
      activity_source_keys: keys.slice(0, 2),
    };
    render(<ResultsTable {...callbacks} rows={[repeated]} />);
    const value = screen.getAllByRole('button', { name: 'I-7 Ratio 活性来源第 5 页' })[1]!;
    value.focus();
    await userEvent.keyboard('{Enter}');
    expect(callbacks.onActivitySource).toHaveBeenCalledExactlyOnceWith(repeated, activity, keys[1]);
    expect(value).toHaveFocus();
  });
  it('uses original-page focus, switches same-page observations and clears focus on manual navigation', async () => {
    vi.spyOn(api, 'results').mockResolvedValue({
      ...results,
      items: [row],
      metrics: ['Ratio', 'Grade'],
    });
    const load = vi
      .spyOn(api, 'page')
      .mockImplementation(async (_id, number) => ({ ...page, page: number }));
    const navigate = vi.fn();
    function Host() {
      const [route, setRoute] = useState<Route>({ ...emptyRoute, projectId: project.id, page: 4 });
      return (
        <Workspace
          project={project}
          route={route}
          navigate={(next) => {
            navigate(next);
            setRoute(next);
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
    await userEvent.click(await screen.findByRole('button', { name: 'I-7 Ratio 活性来源第 5 页' }));
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 5,
        tab: 'original',
        compoundId: null,
        activityFocus: { compoundId: row.id, key: keys[0] },
        layout: expect.objectContaining({ pdfVisible: true }),
      }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'I-7 Grade 活性来源第 5 页' }));
    await waitFor(() =>
      expect(load).toHaveBeenLastCalledWith(project.id, 5, expect.any(AbortSignal), {
        compoundId: row.id,
        key: keys[1],
      }),
    );
    fireEvent.click(screen.getByRole('tab', { name: '结构标注' }));
    expect(navigate.mock.calls.at(-1)![0].activityFocus).toBeUndefined();
    await userEvent.click(screen.getByRole('button', { name: 'I-7 Ratio 活性来源第 5 页' }));
    fireEvent.click(screen.getByRole('button', { name: '下一页原始文档' }));
    expect(navigate.mock.calls.at(-1)![0].activityFocus).toBeUndefined();
    await userEvent.click(screen.getByRole('button', { name: 'I-7 Ratio 活性来源第 5 页' }));
    await userEvent.click(screen.getByRole('button', { name: 'I-7 结构来源第 4 页' }));
    expect(navigate.mock.calls.at(-1)![0].activityFocus).toBeUndefined();
  });
});
