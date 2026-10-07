import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import type { HistoryEntry } from '../src/api/historyTypes';
import { DeletionDialog } from '../src/features/history/DeletionDialog';
import { HistoryActions } from '../src/features/history/HistoryActions';
import { HistoryDialog } from '../src/features/history/HistoryDialog';
import { deletionScope, retentionNotice } from '../src/features/history/historyPresentation';
import { historyEntry, historyList, trashed } from './history-fixtures';

beforeEach(() => {
  vi.spyOn(api, 'historyEntry').mockResolvedValue(historyEntry());
  vi.spyOn(api, 'history').mockResolvedValue(historyList([]));
  vi.spyOn(api, 'deleteHistory').mockResolvedValue(trashed(historyEntry()));
  vi.spyOn(api, 'restoreHistory').mockResolvedValue(historyEntry());
});
function options(entry = historyEntry()) {
  return { target: entry, action: 'delete' as const, onClose: vi.fn(), onChanged: vi.fn() };
}

describe('explicit recoverable deletion and authoritative preview', () => {
  it('reads only on click, discloses retained files and cancels without a mutation, restoring focus', async () => {
    const entry = historyEntry();
    const props = options(entry);
    render(<HistoryActions target={entry} onChanged={props.onChanged} iconOnly />);
    expect(api.historyEntry).not.toHaveBeenCalled();
    const opener = screen.getByRole('button', { name: `删除 ${entry.title}` });
    await userEvent.click(opener);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    expect(screen.getByRole('dialog')).toHaveTextContent(deletionScope.project);
    expect(screen.getByRole('dialog')).toHaveTextContent(retentionNotice);
    expect(screen.getByRole('button', { name: '取消' })).toHaveFocus();
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(api.deleteHistory).not.toHaveBeenCalled();
  });
  it('keeps confirm disabled during preview, uses server revision and prevents duplicate/busy dismissal', async () => {
    const entry = historyEntry({ revision: 'd'.repeat(64) });
    let preview!: (value: HistoryEntry) => void;
    let finish!: (value: HistoryEntry) => void;
    vi.mocked(api.historyEntry).mockImplementation(
      () =>
        new Promise((resolve) => {
          preview = resolve;
        }),
    );
    vi.mocked(api.deleteHistory).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const props = options(entry);
    render(<DeletionDialog {...props} />);
    const confirm = screen.getByRole('button', { name: '确认移入回收站' });
    expect(confirm).toBeDisabled();
    expect(screen.getByText('正在核对服务端状态…')).toBeVisible();
    preview(entry);
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(api.deleteHistory).toHaveBeenCalledExactlyOnceWith(entry.kind, entry.id, entry.revision);
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled();
    expect(screen.queryByText('服务端当前不允许此操作。')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '关闭对话框' })).toBeDisabled();
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(props.onClose).not.toHaveBeenCalled();
    finish(trashed(entry));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalledExactlyOnceWith(trashed(entry)));
    expect(screen.getByText('记录已在回收站。')).toBeVisible();
  });
  it.each(['任务仍在运行，不能删除。', '尚未验证进程归属，不能删除。'])(
    'disables from server preview: %s',
    async (reason) => {
      const entry = historyEntry({ kind: 'job', can_delete: false, blocked_reason: reason });
      vi.mocked(api.historyEntry).mockResolvedValue(entry);
      render(<DeletionDialog {...options(entry)} />);
      expect(await screen.findByText(reason)).toBeVisible();
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
      expect(screen.getByRole('dialog')).toHaveTextContent(
        '当前表格、产物、生产记录和检查点文件不变',
      );
      expect(api.deleteHistory).not.toHaveBeenCalled();
    },
  );
  it('surfaces read failure and permits only a read retry until preview succeeds', async () => {
    vi.mocked(api.historyEntry).mockRejectedValueOnce(new Error('读取失败'));
    render(<DeletionDialog {...options()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('读取失败');
    expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    expect(api.historyEntry).toHaveBeenCalledTimes(2);
    expect(api.deleteHistory).not.toHaveBeenCalled();
  });
  it('requires fresh GET after an ambiguous write and retries only on another explicit confirmation', async () => {
    const entry = historyEntry();
    const current = { ...entry, revision: 'c'.repeat(64) };
    vi.mocked(api.historyEntry).mockResolvedValueOnce(entry).mockResolvedValue(current);
    vi.mocked(api.deleteHistory).mockRejectedValueOnce(
      new ApiError(0, 'network_error', '写入结果未知', true),
    );
    render(<DeletionDialog {...options(entry)} />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('写入结果未知');
    expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
    expect(api.historyEntry).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    expect(api.deleteHistory).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    expect(api.deleteHistory).toHaveBeenLastCalledWith(entry.kind, entry.id, current.revision);
    expect(api.deleteHistory).toHaveBeenCalledTimes(2);
  });
  it('reconciles an already committed ambiguous deletion without replay or automatic restore', async () => {
    const entry = historyEntry();
    vi.mocked(api.historyEntry).mockResolvedValueOnce(entry).mockResolvedValue(trashed(entry));
    vi.mocked(api.deleteHistory).mockRejectedValueOnce(
      new ApiError(200, 'invalid_write_response', '结果未知', true),
    );
    const props = options(entry);
    render(<DeletionDialog {...props} />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    expect(await screen.findByText('记录已在回收站。')).toBeVisible();
    expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
    expect(props.onChanged).toHaveBeenCalledExactlyOnceWith(trashed(entry));
    expect(api.deleteHistory).toHaveBeenCalledTimes(1);
    expect(api.restoreHistory).not.toHaveBeenCalled();
  });
  it('also requires a refresh after a conflict, with no background write retry', async () => {
    vi.mocked(api.deleteHistory).mockRejectedValueOnce(
      new ApiError(409, 'history_changed', '修订已变化'),
    );
    render(<DeletionDialog {...options()} />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('修订已变化');
    expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
    expect(api.deleteHistory).toHaveBeenCalledTimes(1);
  });
  it('keeps a child restore blocked until the server says its project is restored', async () => {
    const entry = {
      ...trashed(historyEntry({ kind: 'export' })),
      can_restore: false,
      blocked_reason: '请先恢复所属项目。',
    };
    vi.mocked(api.historyEntry)
      .mockResolvedValueOnce(entry)
      .mockResolvedValueOnce({ ...entry, can_restore: true, blocked_reason: null });
    vi.mocked(api.restoreHistory).mockResolvedValue(historyEntry({ kind: 'export' }));
    const props = options(entry);
    render(<DeletionDialog {...props} action="restore" />);
    expect(await screen.findByText('请先恢复所属项目。')).toBeVisible();
    expect(screen.getByRole('button', { name: '确认恢复' })).toBeDisabled();
    expect(api.restoreHistory).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '确认恢复' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: '确认恢复' }));
    expect(api.restoreHistory).toHaveBeenCalledExactlyOnceWith(
      entry.kind,
      entry.id,
      entry.revision,
    );
    expect(await screen.findByText('记录已恢复。')).toBeVisible();
  });
});

describe('compact history and trash paging', () => {
  it('keeps an unchanged file preview open after uncertainty reconciliation for a new explicit decision', async () => {
    const entry = historyEntry({ kind: 'export' });
    vi.mocked(api.history).mockResolvedValue(historyList([entry]));
    vi.mocked(api.historyEntry).mockResolvedValue(entry);
    vi.mocked(api.deleteHistory)
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '结果未知', true))
      .mockResolvedValue(trashed(entry));
    render(
      <HistoryDialog
        title="已生成文件"
        initialKind="export"
        projectId={entry.project_id!}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: `删除 ${entry.title}` }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    expect(api.history).toHaveBeenCalledOnce();
    expect(api.deleteHistory).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: '确认移入回收站' }));
    await waitFor(() => expect(api.deleteHistory).toHaveBeenCalledTimes(2));
  });
  it('loads only the requested project files and refreshes them after deletion, without touching results', async () => {
    const entry = historyEntry({ kind: 'export', title: 'Synthetic saved.csv' });
    vi.mocked(api.history)
      .mockResolvedValueOnce(historyList([entry]))
      .mockResolvedValue(historyList([]));
    vi.mocked(api.historyEntry).mockResolvedValue(entry);
    vi.mocked(api.deleteHistory).mockResolvedValue(trashed(entry));
    const onChanged = vi.fn();
    const results = vi.spyOn(api, 'results');
    render(
      <HistoryDialog
        title="已生成文件"
        initialKind="export"
        projectId={entry.project_id!}
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: `删除 ${entry.title}` }));
    const dialog = screen.getByRole('dialog', { name: '删除已生成文件？' });
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole('button', { name: '确认移入回收站' }));
    expect(await screen.findByText('没有记录')).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新记录' })).toHaveFocus());
    expect(onChanged).toHaveBeenCalledWith(trashed(entry));
    expect(api.history).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: 'export', project_id: entry.project_id }),
      expect.any(AbortSignal),
    );
    expect(results).not.toHaveBeenCalled();
  });
  it('returns focus to the open trash dialog refresh button when a restored child row disappears', async () => {
    const entry = trashed(historyEntry({ kind: 'job' }));
    vi.mocked(api.history)
      .mockResolvedValueOnce(historyList([entry]))
      .mockResolvedValue(historyList([]));
    vi.mocked(api.historyEntry).mockResolvedValue(entry);
    vi.mocked(api.restoreHistory).mockResolvedValue(historyEntry({ kind: 'job' }));
    render(
      <HistoryDialog
        title="回收站"
        initialKind="job"
        deleted
        filters
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: `恢复 ${entry.title}` }));
    const modal = screen.getByRole('dialog', { name: '恢复任务记录？' });
    await waitFor(() =>
      expect(within(modal).getByRole('button', { name: '确认恢复' })).toBeEnabled(),
    );
    await userEvent.click(within(modal).getByRole('button', { name: '确认恢复' }));
    await screen.findByText('此类型回收站为空。');
    expect(screen.getByRole('dialog', { name: '回收站' })).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新记录' })).toHaveFocus());
  });
  it('supports all trash kind filters and bounded paging, and rereads when reopened', async () => {
    const entry = trashed(historyEntry());
    vi.mocked(api.history).mockImplementation(async (query) =>
      historyList(query.kind === 'project' ? [entry] : [], {
        total: query.kind === 'project' ? 101 : 0,
        page: query.page!,
        page_size: query.page_size!,
      }),
    );
    const props = {
      title: '回收站',
      initialKind: 'project' as const,
      deleted: true,
      filters: true,
      onClose: vi.fn(),
      onChanged: vi.fn(),
    };
    const view = render(<HistoryDialog {...props} />);
    await screen.findByRole('button', { name: `恢复 ${entry.title}` });
    await userEvent.click(screen.getByRole('button', { name: '下一页历史记录' }));
    await waitFor(() =>
      expect(api.history).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
        expect.any(AbortSignal),
      ),
    );
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: '每页历史记录数量' }),
      '100',
    );
    await waitFor(() =>
      expect(api.history).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 1, page_size: 100 }),
        expect.any(AbortSignal),
      ),
    );
    for (const kind of ['job', 'export', 'environment_operation']) {
      await userEvent.selectOptions(screen.getByRole('combobox', { name: '回收站记录类型' }), kind);
      expect(await screen.findByText('此类型回收站为空。')).toBeVisible();
      expect(api.history).toHaveBeenLastCalledWith(
        expect.objectContaining({ kind, deleted: true, page: 1 }),
        expect.any(AbortSignal),
      );
    }
    const before = vi.mocked(api.history).mock.calls.length;
    view.unmount();
    render(<HistoryDialog {...props} />);
    await screen.findByRole('button', { name: `恢复 ${entry.title}` });
    expect(api.history).toHaveBeenCalledTimes(before + 1);
    expect(api.deleteHistory).not.toHaveBeenCalled();
    expect(api.restoreHistory).not.toHaveBeenCalled();
  });
  it('shows recoverable errors and inert untrusted titles, never a disk-space or log claim', async () => {
    const entry = historyEntry({
      kind: 'environment_operation',
      project_id: null,
      title: '<script>inert</script>',
    });
    vi.mocked(api.history)
      .mockRejectedValueOnce(new Error('记录不可用'))
      .mockResolvedValue(historyList([entry]));
    render(
      <HistoryDialog
        title="环境操作记录"
        initialKind="environment_operation"
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('记录不可用');
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(await screen.findByText(entry.title)).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
    expect(screen.queryByText(entry.id)).not.toBeInTheDocument();
    expect(screen.getByRole('dialog')).toHaveTextContent('不释放磁盘空间');
  });
});
