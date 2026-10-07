import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Dialog } from '../src/components/Dialog';
import { Header } from '../src/components/Header';

const headerProps = {
  view: 'new-task' as const,
  project: null,
  version: null,
  onUpload: vi.fn(),
  onRecent: vi.fn(),
  onNavigate: vi.fn(),
  onAnalysis: vi.fn(),
  disabled: true,
};

function emulateNativeDialogFocus() {
  // jsdom opens the dialog without the browser's normal initial focus step.
  // Real native-dialog focus and viewport behavior remain a browser check.
  vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.setAttribute('open', '');
    this.querySelector<HTMLButtonElement>('button')?.focus();
  });
}

describe('shared-control craft: connection boundary', () => {
  it('keeps the brand inert with the rest of navigation before connection is ready', async () => {
    render(<Header {...headerProps} />);
    const brand = screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' });
    expect(brand).toHaveAttribute('aria-disabled', 'true');
    expect(brand).not.toHaveAttribute('href');
    expect(brand).toHaveAttribute('tabindex', '-1');
    await userEvent.click(brand);
    fireEvent.keyDown(brand, { key: 'Enter' });
    expect(headerProps.onUpload).not.toHaveBeenCalled();
    for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
    expect(screen.getByLabelText('软件版本')).toHaveTextContent('版本待连接');
  });

  it('restores the existing brand destination and callback when connection becomes ready', async () => {
    const { rerender } = render(<Header {...headerProps} />);
    rerender(<Header {...headerProps} disabled={false} version="0.1.0" />);
    const brand = screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' });
    expect(brand).toHaveAttribute('href', '#/new-task');
    expect(brand).not.toHaveAttribute('aria-disabled');
    expect(brand).not.toHaveAttribute('tabindex', '-1');
    brand.focus();
    await userEvent.keyboard('{Enter}');
    expect(headerProps.onUpload).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('软件版本')).toHaveTextContent('v0.1.0');
  });
});

describe('shared-control craft: deferred dialog focus', () => {
  it('honors the initial field when it arrives after the loading state', async () => {
    emulateNativeDialogFocus();
    const props = { title: '异步修正', onClose: vi.fn() };
    const { rerender } = render(
      <Dialog {...props}>
        <output>正在读取数据…</output>
      </Dialog>,
    );
    expect(screen.getByRole('button', { name: '关闭对话框' })).toHaveFocus();
    rerender(
      <Dialog {...props}>
        <input aria-label="修正化合物编号" data-initial-focus />
      </Dialog>,
    );
    await waitFor(() => expect(screen.getByLabelText('修正化合物编号')).toHaveFocus());
  });

  it('waits for an initially disabled field without focusing an unavailable control', async () => {
    emulateNativeDialogFocus();
    const props = { title: '等待可用输入', onClose: vi.fn() };
    const { rerender } = render(
      <Dialog {...props}>
        <input aria-label="初始字段" data-initial-focus disabled />
      </Dialog>,
    );
    expect(screen.getByRole('button', { name: '关闭对话框' })).toHaveFocus();
    rerender(
      <Dialog {...props}>
        <input aria-label="初始字段" data-initial-focus />
      </Dialog>,
    );
    await waitFor(() => expect(screen.getByLabelText('初始字段')).toHaveFocus());
  });

  it('does not steal focus after the user chooses another available control', async () => {
    emulateNativeDialogFocus();
    const props = { title: '保留用户焦点', onClose: vi.fn() };
    // Keep the same host subtree; replacing a single child with a nested array
    // unmounts the chosen button and tests React reconciliation, not focus theft.
    const body = (ready: boolean) => (
      <div>
        <button type="button">读取状态</button>
        {ready && <input aria-label="稍后字段" data-initial-focus />}
      </div>
    );
    const { rerender } = render(<Dialog {...props}>{body(false)}</Dialog>);
    const chosen = screen.getByRole('button', { name: '读取状态' });
    await userEvent.click(chosen);
    await act(async () => {
      rerender(<Dialog {...props}>{body(true)}</Dialog>);
    });
    expect(screen.getByRole('button', { name: '读取状态' })).toBe(chosen);
    expect(chosen.isConnected).toBe(true);
    expect(chosen).toHaveFocus();
  });

  it.each(['pointer', 'keyboard'])(
    'preserves focus after %s intent even on the native initial control',
    async (intent) => {
      emulateNativeDialogFocus();
      const props = { title: '保留操作意图', onClose: vi.fn() };
      const { rerender } = render(<Dialog {...props}>正在读取数据…</Dialog>);
      const close = screen.getByRole('button', { name: '关闭对话框' });
      if (intent === 'pointer') fireEvent.pointerDown(close);
      else fireEvent.keyDown(close, { key: 'Shift' });
      await act(async () => {
        rerender(
          <Dialog {...props}>
            <input aria-label="稍后字段" data-initial-focus />
          </Dialog>,
        );
      });
      expect(close).toHaveFocus();
    },
  );

  it('keeps Escape and close blocked during the existing uncertain-write boundary', async () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <Dialog title="保存边界" onClose={onClose}>
        <input aria-label="初始字段" data-initial-focus />
      </Dialog>,
    );
    rerender(
      <Dialog title="保存边界" onClose={onClose} busy>
        <input aria-label="初始字段" data-initial-focus disabled />
      </Dialog>,
    );
    const close = screen.getByRole('button', { name: '关闭对话框' });
    expect(close).toBeDisabled();
    await userEvent.click(close);
    const cancel = new Event('cancel', { cancelable: true });
    fireEvent(screen.getByRole('dialog', { name: '保存边界' }), cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(onClose).not.toHaveBeenCalled();
  });
});
