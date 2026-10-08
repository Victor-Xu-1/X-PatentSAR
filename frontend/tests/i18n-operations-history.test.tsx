import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { DeletionDialog } from '../src/features/history/DeletionDialog';
import { HistoryDialog } from '../src/features/history/HistoryDialog';
import { historyEntry, historyList, trashed } from './history-fixtures';
import { deferred, setupOperationsLocale, switchTo } from './i18n-operations-fixtures';

setupOperationsLocale();

describe('operations locale: history', () => {
  it('keeps history titles, record IDs, page size and server read count stable on a language switch', async () => {
    const entry = trashed(historyEntry({ kind: 'job', title: '设置已保存。' }));
    const read = vi.spyOn(api, 'history').mockResolvedValue(historyList([entry]));
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
    await screen.findByText(entry.title);
    await userEvent.selectOptions(screen.getByLabelText('History records per page'), '100');
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    const dialog = screen.getByRole('dialog', { name: 'Trash' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '回收站' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Trash' })).toBe(dialog);
    expect(screen.getByLabelText('History records per page')).toHaveValue('100');
    expect(within(dialog).getByRole('button', { name: 'Restore 设置已保存。' })).toBeEnabled();
    expect(within(dialog).getByText('Records: 1 · Page 1')).toBeVisible();
    expect(within(dialog).getByText(entry.title).closest('li')).toHaveAttribute(
      'data-history-id',
      entry.id,
    );
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '回收站' })).toBe(dialog);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it('switches a blocked deletion confirmation without translating user titles or raw server reasons', async () => {
    const entry = historyEntry({
      title: '保存',
      can_delete: false,
      blocked_reason: '设置已保存。',
    });
    const read = vi.spyOn(api, 'historyEntry').mockResolvedValue(entry);
    const remove = vi.spyOn(api, 'deleteHistory');
    render(<DeletionDialog target={entry} action="delete" onClose={vi.fn()} onChanged={vi.fn()} />);
    await screen.findByText(entry.blocked_reason!);
    const dialog = screen.getByRole('dialog', { name: 'Delete Project?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '删除项目？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Delete Project?' })).toBe(dialog);
    expect(within(dialog).getByText('保存')).toBeVisible();
    expect(within(dialog).getByText('设置已保存。')).toBeVisible();
    expect(within(dialog).getByText(/No disk space is reclaimed/)).toBeVisible();
    expect(within(dialog).getByRole('button', { name: 'Confirm move to Trash' })).toBeDisabled();
    switchTo('zh-CN');
    expect(read).toHaveBeenCalledTimes(1);
    expect(remove).not.toHaveBeenCalled();
  });

  it('relocalizes a retained history mutation error without replaying or losing the refresh guard', async () => {
    const entry = historyEntry({ title: '保存' });
    const pending = deferred<never>();
    const read = vi.spyOn(api, 'historyEntry').mockResolvedValue(entry);
    const remove = vi.spyOn(api, 'deleteHistory').mockReturnValue(pending.promise);
    render(<DeletionDialog target={entry} action="delete" onClose={vi.fn()} onChanged={vi.fn()} />);
    const confirm = await screen.findByRole('button', { name: 'Confirm move to Trash' });
    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    switchTo('zh-CN');
    await act(async () => pending.reject('synthetic-private-body'));
    expect(screen.getByRole('alert')).toHaveTextContent('操作结果无法确认，请先刷新核对状态。');
    switchTo('en');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The operation result could not be confirmed.',
    );
    expect(screen.getByText(/Submission stopped/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Confirm move to Trash' })).toBeDisabled();
    expect(screen.getByText('保存')).toBeVisible();
    expect(screen.queryByText(/synthetic-private-body/)).not.toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
