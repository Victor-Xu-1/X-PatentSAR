import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { defaultLayout, normalizeLayout } from '../src/model/layout';
import { parseRoute, routeHash, emptyRoute } from '../src/model/route';
import { WorkspaceLayout } from '../src/features/workspace/WorkspaceLayout';
import { Workspace } from '../src/features/workspace/Workspace';
import { api } from '../src/api';
import { compound, page, project, results } from './fixtures';

describe('results-first layout with one safe, refreshable state', () => {
  it('defaults to 28 percent source and validates nonfinite / extreme inputs', () => {
    expect(defaultLayout).toEqual({ pdfWidth: 28, pdfVisible: true, fullscreen: false });
    expect(normalizeLayout({ pdfWidth: NaN }).pdfWidth).toBe(28);
    expect(normalizeLayout({ pdfWidth: Infinity }).pdfWidth).toBe(28);
    expect(normalizeLayout({ pdfWidth: -50 }).pdfWidth).toBe(20);
    expect(normalizeLayout({ pdfWidth: 99 }).pdfWidth).toBe(55);
  });
  it('roundtrips source width, collapse, fullscreen and result view across refresh', () => {
    const route = {
      ...emptyRoute,
      projectId: 'p',
      layout: { pdfWidth: 31, pdfVisible: false, fullscreen: true },
      resultTab: 'admet' as const,
    };
    expect(parseRoute(routeHash(route))).toEqual(route);
    const invalid = parseRoute('#/projects/p?pdfWidth=Infinity&pdf=bad&fullscreen=bad');
    expect(invalid.layout).toEqual(defaultLayout);
    expect(parseRoute('#/new-task').view).toBe('new-task');
  });
  it('supports keyboard resize, Home/End and collapse focus restoration', async () => {
    function TestLayout() {
      const [layout, setLayout] = useState(defaultLayout);
      return (
        <WorkspaceLayout
          layout={layout}
          onChange={setLayout}
          source={<div>真实原文</div>}
          results={<div>真实结果</div>}
        />
      );
    }
    render(<TestLayout />);
    const splitter = screen.getByRole('slider', { name: '调整原文与结果宽度' });
    expect(splitter).toHaveAttribute('aria-valuenow', '28');
    splitter.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(splitter).toHaveAttribute('aria-valuenow', '30');
    await userEvent.keyboard('{End}');
    expect(splitter).toHaveAttribute('aria-valuenow', '55');
    await userEvent.keyboard('{Home}');
    expect(splitter).toHaveAttribute('aria-valuenow', '20');
    await userEvent.click(screen.getByRole('button', { name: '收起原文，结果全宽' }));
    expect(screen.queryByText('真实原文')).not.toBeInTheDocument();
    const restore = screen.getByRole('button', { name: '展开原文' });
    expect(restore).toHaveFocus();
    await userEvent.click(restore);
    expect(screen.getByText('真实原文')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '全屏工作区' }));
    expect(screen.getByRole('button', { name: '退出全屏工作区' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: '全屏工作区' })).toHaveFocus();
  });
  it('pointer resize respects bounds and only commits on pointer end', () => {
    const change = vi.fn();
    render(
      <WorkspaceLayout
        layout={defaultLayout}
        onChange={change}
        source={<div />}
        results={<div />}
      />,
    );
    const split = document.querySelector('.workspace-split')!;
    vi.spyOn(split, 'getBoundingClientRect').mockReturnValue({ left: 100, width: 1000 } as DOMRect);
    const separator = screen.getByRole('slider');
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 380, button: 0, isPrimary: true });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 450 });
    expect(change).not.toHaveBeenCalled();
    fireEvent.pointerUp(separator, { pointerId: 1, clientX: 450 });
    expect(change).toHaveBeenCalledWith({ ...defaultLayout, pdfWidth: 35 });
  });
  it('ignores pointer resize when pane geometry is not measurable', () => {
    const change = vi.fn();
    render(
      <WorkspaceLayout
        layout={defaultLayout}
        onChange={change}
        source={<div />}
        results={<div />}
      />,
    );
    const separator = screen.getByRole('slider');
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0, clientX: 100, isPrimary: true });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 500 });
    fireEvent.pointerUp(separator, { pointerId: 1 });
    expect(change).not.toHaveBeenCalled();
  });
  it('source navigation unfolds collapsed original and selects actual annotation', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    vi.spyOn(api, 'page').mockResolvedValue(page);
    const navigate = vi.fn();
    render(
      <Workspace
        project={project}
        route={{
          ...emptyRoute,
          projectId: project.id,
          layout: { ...defaultLayout, pdfVisible: false },
        }}
        navigate={navigate}
        query=""
        onQuery={vi.fn()}
        ready
        job={null}
        onJobChange={vi.fn()}
        onProjectReload={vi.fn()}
        onUpload={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: '来源定位' }));
    expect(navigate).toHaveBeenCalledWith(
      expect.objectContaining({
        page: compound.source.page,
        tab: 'annotations',
        compoundId: compound.id,
        layout: { ...defaultLayout, pdfVisible: true },
      }),
    );
  });
});
