import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { ReviewDialog } from '../src/features/results/ReviewDialog';
import { ExportDialog } from '../src/features/results/ExportDialog';
import { UploadDialog } from '../src/features/projects/UploadDialog';
import { Dialog } from '../src/components/Dialog';
import { compound, project, results } from './fixtures';

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
  it('retains a draft on review conflict and requires explicit latest-revision reload', async () => {
    const save = vi
      .spyOn(api, 'review')
      .mockRejectedValueOnce(new ApiError(409, 'revision_conflict', '记录已更新'))
      .mockResolvedValueOnce({
        decision: 'needs_review',
        note: '草稿',
        revision: 3,
        updated_at: project.updated_at,
      });
    vi.spyOn(api, 'results').mockResolvedValue({
      ...results,
      items: [
        {
          ...compound,
          review: {
            decision: 'approved',
            note: '他人注记',
            revision: 2,
            updated_at: project.updated_at,
          },
        },
      ],
    });
    const saved = vi.fn();
    render(
      <ReviewDialog projectId={project.id} compound={compound} onClose={vi.fn()} onSaved={saved} />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('复核注记'), '草稿');
    await user.click(screen.getByText('保存复核注记'));
    expect(await screen.findByText('此记录已被更新，未覆盖他人的复核。')).toBeVisible();
    expect(screen.getByText('保存复核注记')).toBeDisabled();
    expect(screen.getByLabelText('复核注记')).toHaveValue('草稿');
    await user.click(screen.getByText('载入最新版本并保留草稿'));
    expect(await screen.findByText('他人注记')).toBeVisible();
    await user.click(screen.getByText('保存复核注记'));
    expect(save).toHaveBeenLastCalledWith(project.id, compound.id, 'needs_review', '草稿', 2);
    expect(saved).toHaveBeenCalledOnce();
  });
  it('does not turn a failed write into a saved review', async () => {
    vi.spyOn(api, 'review').mockRejectedValue(new ApiError(0, 'network_error', '结果未知', true));
    const saved = vi.fn();
    render(
      <ReviewDialog projectId={project.id} compound={compound} onClose={vi.fn()} onSaved={saved} />,
    );
    await userEvent.click(screen.getByText('保存复核注记'));
    expect(await screen.findByRole('alert')).toHaveTextContent('结果未知');
    expect(saved).not.toHaveBeenCalled();
  });
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
    await waitFor(() => expect(download).toHaveBeenCalledWith(project.id, 'csv', ['I-7', 'I-8']));
    expect(await screen.findByText('文件已从服务端生成并交给浏览器下载。')).toBeVisible();
  });
  it('rejects invalid PDFs before any upload write', async () => {
    const upload = vi.spyOn(api, 'upload');
    render(<UploadDialog project={null} onClose={vi.fn()} onUploaded={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('项目名称'), '测试');
    await user.upload(
      screen.getByLabelText('原始专利 PDF 文件'),
      new File(['not-pdf'], 'renamed.pdf', { type: 'application/pdf' }),
    );
    await user.click(screen.getByText('上传并创建项目'));
    expect(await screen.findByRole('alert')).toHaveTextContent('文件头');
    expect(upload).not.toHaveBeenCalled();
  });
});
