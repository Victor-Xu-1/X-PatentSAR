import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResizeHandle } from '../src/components/ResizeHandle';
import { AppFrame } from '../src/components/AppFrame';
import { defaultSidebarLayout, normalizeSidebarLayout } from '../src/model/sidebarLayout';
import { emptyRoute, parseRoute, routeHash } from '../src/model/route';

describe('one bounded resize interaction', () => {
  it('previews only the owning pointer and commits once on release', () => {
    const preview = vi.fn(),
      commit = vi.fn();
    render(
      <ResizeHandle
        label="列宽"
        value={100}
        min={80}
        max={400}
        resetValue={100}
        onPreview={preview}
        onCommit={commit}
      />,
    );
    const handle = screen.getByRole('slider');
    fireEvent.pointerDown(handle, { pointerId: 1, button: 2, clientX: 50 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 200 });
    expect(preview).not.toHaveBeenCalled();
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 50, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 200 });
    expect(preview).not.toHaveBeenCalled();
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 125 });
    expect(preview).toHaveBeenCalledWith(175);
    expect(commit).not.toHaveBeenCalled();
    fireEvent.pointerUp(handle, { pointerId: 2 });
    expect(commit).not.toHaveBeenCalled();
    fireEvent.pointerUp(handle, { pointerId: 1 });
    fireEvent.lostPointerCapture(handle, { pointerId: 1 });
    expect(commit).toHaveBeenCalledExactlyOnceWith(175);
    expect(preview).toHaveBeenLastCalledWith(null);
  });
  it.each(['pointerCancel', 'lostPointerCapture', 'escape'])('rolls back on %s', (action) => {
    const preview = vi.fn(),
      commit = vi.fn();
    render(
      <ResizeHandle
        label="列宽"
        value={100}
        min={80}
        max={400}
        resetValue={100}
        onPreview={preview}
        onCommit={commit}
      />,
    );
    const handle = screen.getByRole('slider');
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 50, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 900 });
    expect(preview).toHaveBeenCalledWith(400);
    if (action === 'escape') fireEvent.keyDown(handle, { key: 'Escape' });
    else if (action === 'pointerCancel') fireEvent.pointerCancel(handle, { pointerId: 1 });
    else fireEvent.lostPointerCapture(handle, { pointerId: 1 });
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(commit).not.toHaveBeenCalled();
    expect(preview).toHaveBeenLastCalledWith(null);
  });
  it('supports keyboard bounds, reset and invalid container geometry', async () => {
    const preview = vi.fn(),
      commit = vi.fn();
    render(
      <ResizeHandle
        label="列宽"
        value={100}
        min={80}
        max={400}
        resetValue={120}
        fromPointer={() => NaN}
        onPreview={preview}
        onCommit={commit}
      />,
    );
    const handle = screen.getByRole('slider');
    handle.focus();
    await userEvent.keyboard('{ArrowLeft}{ArrowRight}{Home}{End}');
    expect(commit.mock.calls.map(([value]) => value)).toEqual([92, 108, 80, 400]);
    fireEvent.doubleClick(handle);
    expect(commit).toHaveBeenLastCalledWith(120);
    commit.mockClear();
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 50, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 300 });
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(commit).not.toHaveBeenCalled();
  });
});

describe('refreshable sidebar layout', () => {
  it('validates URL values and roundtrips on workspace and management routes', () => {
    expect(normalizeSidebarLayout({ width: NaN })).toEqual(defaultSidebarLayout);
    expect(normalizeSidebarLayout({ width: -50 }).width).toBe(184);
    expect(normalizeSidebarLayout({ width: Infinity }).width).toBe(232);
    expect(normalizeSidebarLayout({ width: 10000 }).width).toBe(360);
    for (const view of ['workspace', 'projects', 'jobs', 'settings', 'new-task'] as const) {
      const route = { ...emptyRoute, view, sidebar: { width: 288, collapsed: true } };
      expect(parseRoute(routeHash(route))).toEqual(route);
    }
  });
  it('snaps drag-to-collapse while retaining the previous expanded width', () => {
    function Frame() {
      const [layout, setLayout] = useState({ width: 288, collapsed: false });
      return (
        <AppFrame
          layout={layout}
          onChange={setLayout}
          narrow={false}
          menuOpen={false}
          leading={null}
          sidebar={(collapsed) => <aside>{collapsed ? '收起' : '展开'}</aside>}
        >
          <div>结果</div>
        </AppFrame>
      );
    }
    render(<Frame />);
    const handle = screen.getByRole('slider');
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 288, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 80 });
    expect(screen.getByText('收起')).toBeVisible();
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(handle).toHaveAttribute('aria-valuenow', '56');
    fireEvent.pointerDown(handle, { pointerId: 2, button: 0, clientX: 56, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 256 });
    fireEvent.pointerCancel(handle, { pointerId: 2 });
    expect(handle).toHaveAttribute('aria-valuenow', '56');
    fireEvent.doubleClick(handle);
    expect(handle).toHaveAttribute('aria-valuenow', '232');
    expect(screen.getByText('展开')).toBeVisible();
  });
  it('keeps mobile navigation expanded and excludes desktop-only drag controls', () => {
    render(
      <AppFrame
        layout={{ width: 288, collapsed: true }}
        onChange={vi.fn()}
        narrow
        menuOpen
        leading={null}
        sidebar={(collapsed) => <aside>{String(collapsed)}</aside>}
      >
        <div>结果</div>
      </AppFrame>,
    );
    expect(screen.getByText('false')).toBeVisible();
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
    expect(document.querySelector('.app-shell')).toHaveStyle({ '--sidebar-width': '288px' });
  });
  it('cancels a drag when switching to mobile instead of restoring a stale preview', () => {
    const props = {
      layout: defaultSidebarLayout,
      onChange: vi.fn(),
      menuOpen: false,
      leading: null,
      sidebar: () => <aside>导航</aside>,
      children: <div>结果</div>,
    };
    const { rerender } = render(<AppFrame {...props} narrow={false} />);
    const handle = screen.getByRole('slider');
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 232, isPrimary: true });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 300 });
    expect(document.querySelector('.app-shell')).toHaveStyle({ '--sidebar-width': '300px' });
    rerender(<AppFrame {...props} narrow />);
    rerender(<AppFrame {...props} narrow={false} />);
    expect(document.querySelector('.app-shell')).toHaveStyle({ '--sidebar-width': '232px' });
    expect(props.onChange).not.toHaveBeenCalled();
  });
});
