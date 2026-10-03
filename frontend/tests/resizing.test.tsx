import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResizeHandle } from '../src/components/ResizeHandle';

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
