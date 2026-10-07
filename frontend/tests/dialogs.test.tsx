import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ExportDialog } from '../src/features/results/ExportDialog';
import { AttachPdfDialog } from '../src/features/projects/AttachPdfDialog';
import { Dialog } from '../src/components/Dialog';
import { project } from './fixtures';

describe('accessible dialogs and explicit mutations', () => {
  it('exports current filters across all matching pages, not selected IDs', async () => {
    const download = vi
      .spyOn(api, 'export')
      .mockResolvedValue(new Blob(['contract'], { type: 'text/csv' }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:contract-only');
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const filters = {
      q: 'I-',
      confidence: 'unknown',
      review: '',
      target: '测试靶点',
      page: 4,
      page_size: 10,
    };
    render(
      <ExportDialog project={project} selected={['I-7']} filters={filters} onClose={vi.fn()} />,
    );
    await userEvent.selectOptions(screen.getByLabelText('导出范围'), 'filtered');
    await userEvent.click(screen.getByText('生成并下载'));
    await waitFor(() => expect(download).toHaveBeenCalledWith(project.id, 'csv', [], filters));
  });
  it('sets initial dialog focus and restores the opener on close', async () => {
    function Parent() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>打开</button>
          {open && (
            <Dialog title="焦点测试" onClose={() => setOpen(false)}>
              <input data-initial-focus aria-label="对话框输入" />
            </Dialog>
          )}
        </>
      );
    }
    render(<Parent />);
    const user = userEvent.setup();
    await user.click(screen.getByText('打开'));
    expect(screen.getByLabelText('对话框输入')).toHaveFocus();
    await user.click(screen.getByLabelText('关闭对话框'));
    expect(screen.getByText('打开')).toHaveFocus();
  });
  it('handles Escape through the native dialog cancel event', () => {
    const close = vi.fn();
    render(
      <Dialog title="关闭测试" onClose={close}>
        内容
      </Dialog>,
    );
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(close).toHaveBeenCalledOnce();
  });
  it.each([true, false])(
    'restores a refreshed opener or its scoped fallback (%s)',
    async (replace) => {
      function Parent() {
        const [open, setOpen] = useState(false);
        const [refreshed, setRefreshed] = useState(false);
        return (
          <section data-dialog-focus-scope>
            <input data-dialog-focus-fallback aria-label="表格搜索" />
            {(!refreshed || replace) && (
              <button
                key={refreshed ? 'new' : 'old'}
                data-focus-key="crop:I-7"
                onClick={() => setOpen(true)}
              >
                打开结构
              </button>
            )}
            {open && (
              <Dialog title="刷新焦点测试" onClose={() => setOpen(false)}>
                <button onClick={() => setRefreshed(true)}>刷新原始表格</button>
              </Dialog>
            )}
          </section>
        );
      }
      render(<Parent />);
      const user = userEvent.setup();
      const old = screen.getByText('打开结构');
      await user.click(old);
      await user.click(screen.getByText('刷新原始表格'));
      expect(old.isConnected).toBe(false);
      await user.click(screen.getByLabelText('关闭对话框'));
      expect(
        replace ? screen.getByText('打开结构') : screen.getByLabelText('表格搜索'),
      ).toHaveFocus();
    },
  );
  it('does not allow closing an uncertain in-flight write', () => {
    const close = vi.fn();
    render(
      <Dialog title="写入测试" onClose={close} busy>
        内容
      </Dialog>,
    );
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText('关闭对话框')).toBeDisabled();
  });
  it.each([false, true])(
    'keeps the parent modal open when only the nested modal receives cancel (busy=%s)',
    (busy) => {
      const parentClose = vi.fn();
      const childClose = vi.fn();
      render(
        <Dialog title="历史列表" onClose={parentClose}>
          <Dialog title="删除确认" onClose={childClose} busy={busy}>
            <button data-initial-focus>取消删除</button>
          </Dialog>
        </Dialog>,
      );
      fireEvent(
        screen.getByRole('dialog', { name: '删除确认' }),
        new Event('cancel', { bubbles: true, cancelable: true }),
      );
      expect(parentClose).not.toHaveBeenCalled();
      expect(childClose).toHaveBeenCalledTimes(busy ? 0 : 1);
    },
  );
  it('exports selected IDs and labels unaccepted output as review-only', async () => {
    const download = vi
      .spyOn(api, 'export')
      .mockResolvedValue(new Blob(['actual-response'], { type: 'text/csv' }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:contract-only');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(
      <ExportDialog
        project={project}
        selected={['I-7', 'I-8']}
        filters={{ q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText(/下载仅为复核材料/)).toBeVisible();
    await userEvent.click(screen.getByText('生成并下载'));
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith(project.id, 'csv', ['I-7', 'I-8'], {
        q: '',
        confidence: '',
        review: '',
        target: '',
        page: 1,
        page_size: 10,
      }),
    );
    expect(await screen.findByText('文件已从服务端生成并交给浏览器下载。')).toBeVisible();
  });
  it('rejects invalid PDFs before any upload write', async () => {
    const upload = vi.spyOn(api, 'attachPdf');
    render(<AttachPdfDialog project={project} onClose={vi.fn()} onUploaded={vi.fn()} />);
    const user = userEvent.setup();
    await user.upload(
      screen.getByLabelText('原始专利 PDF 文件'),
      new File(['not-pdf'], 'renamed.pdf', { type: 'application/pdf' }),
    );
    await user.click(screen.getByText('上传并核对原始 PDF'));
    expect(await screen.findByRole('alert')).toHaveTextContent('文件头');
    expect(upload).not.toHaveBeenCalled();
  });
});
