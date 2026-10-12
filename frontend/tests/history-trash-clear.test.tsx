import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { decodeTrashPlan, decodeTrashClearReceipt } from '../src/api/historyTrashDecoders';
import { HistoryDialog } from '../src/features/history/HistoryDialog';
import { TrashClearDialog } from '../src/features/history/TrashClearDialog';
import { historyList } from './history-fixtures';
import { setLocale } from '../src/i18n';

const plan = {
  revision: 'a'.repeat(64),
  total: 204,
  counts: { project: 1, job: 201, export: 1, environment_operation: 1 },
  blocked: 0,
  files_total: 2,
  bytes_total: 1024,
  retained_targets: 1,
  pending: null,
};
const receipt = {
  request_id: '1'.repeat(32),
  plan_revision: plan.revision,
  cleared: plan.total,
  counts: plan.counts,
  completed_at: '2026-10-13T00:00:00Z',
  started_at: '2026-10-13T00:00:00Z',
  status: 'complete' as const,
  files_total: 2,
  files_deleted: 2,
  files_retained: 0,
  bytes_removed: 1024,
  retained_targets: 1,
};

beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'history').mockResolvedValue(historyList([]));
  vi.spyOn(api, 'trashPlan').mockResolvedValue(plan);
  vi.spyOn(api, 'clearTrash').mockImplementation(async (request) => ({
    ...receipt,
    request_id: request.request_id,
  }));
  vi.spyOn(api, 'trashClearReceipt').mockResolvedValue(receipt);
});

it('offers one all-type/all-page clear even when the selected trash category is empty', async () => {
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
  await userEvent.click(screen.getByRole('button', { name: /^Empty Trash$/ }));
  const dialog = screen.getByRole('dialog', { name: 'Empty Trash?' });
  expect(await within(dialog).findByText('All record types and pages: 204 records.')).toBeVisible();
  expect(api.clearTrash).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm empty all' }));
  expect(await within(dialog).findByText('Permanently removed 204 records.')).toBeVisible();
  expect(api.clearTrash).toHaveBeenCalledTimes(1);
  expect(api.clearTrash).toHaveBeenCalledWith({
    request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
    expected_revision: plan.revision,
    expected_total: 204,
  });
});

it('keeps confirmation safe through locale changes and never clears on open or cancel', async () => {
  const onClose = vi.fn();
  render(<TrashClearDialog onClose={onClose} onDone={vi.fn()} />);
  await screen.findByText('All record types and pages: 204 records.');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByText('全部类型、全部分页，共 204 条记录。')).toBeVisible();
  expect(screen.getByText(/只删除已核实未被引用/)).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(api.clearTrash).not.toHaveBeenCalled();
});

it('blocks empty, unavailable and ownership-blocked plans without enabling stale confirmation', async () => {
  vi.mocked(api.trashPlan).mockResolvedValue({ ...plan, blocked: 1 });
  render(<TrashClearDialog onClose={vi.fn()} onDone={vi.fn()} />);
  expect(await screen.findByText(/1 records have active/)).toBeVisible();
  expect(screen.getByRole('button', { name: 'Confirm empty all' })).toBeDisabled();
  expect(api.clearTrash).not.toHaveBeenCalled();
});

it('resolves an unknown response with the exact receipt, without automatically repeating deletion', async () => {
  vi.mocked(api.clearTrash).mockRejectedValue(
    new ApiError(0, 'network_error', 'Lost response', true),
  );
  vi.mocked(api.trashClearReceipt).mockImplementation(async (id) => ({
    ...receipt,
    request_id: id,
  }));
  const done = vi.fn();
  render(<TrashClearDialog onClose={vi.fn()} onDone={done} />);
  await screen.findByText('All record types and pages: 204 records.');
  await userEvent.click(screen.getByRole('button', { name: 'Confirm empty all' }));
  expect(await screen.findByText(/The clear result is unconfirmed/)).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Confirm empty all' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Check Trash' }));
  expect(await screen.findByText('Permanently removed 204 records.')).toBeVisible();
  expect(api.clearTrash).toHaveBeenCalledTimes(1);
  expect(done).toHaveBeenCalledOnce();
});

it('requires a deliberate retry with the identical captured request after checked absence', async () => {
  vi.mocked(api.clearTrash).mockRejectedValueOnce(
    new ApiError(0, 'network_error', 'Lost response', true),
  );
  vi.mocked(api.trashClearReceipt).mockRejectedValue(
    new ApiError(404, 'history_clear_not_found', 'No receipt'),
  );
  render(<TrashClearDialog onClose={vi.fn()} onDone={vi.fn()} />);
  await screen.findByText('All record types and pages: 204 records.');
  await userEvent.click(screen.getByRole('button', { name: 'Confirm empty all' }));
  await screen.findByText(/The clear result is unconfirmed/);
  const original = vi.mocked(api.clearTrash).mock.calls[0]![0];
  await userEvent.click(screen.getByRole('button', { name: 'Check Trash' }));
  const retry = await screen.findByRole('button', { name: 'Retry this clear request' });
  expect(api.clearTrash).toHaveBeenCalledTimes(1);
  await userEvent.click(retry);
  await screen.findByText('Permanently removed 204 records.');
  expect(vi.mocked(api.clearTrash).mock.calls[1]![0]).toEqual(original);
});

it('shows incomplete file cleanup honestly and resumes the exact frozen request only on a click', async () => {
  const pending = {
    ...receipt,
    status: 'cleanup_pending' as const,
    files_deleted: 1,
    completed_at: null,
  };
  vi.mocked(api.trashPlan).mockResolvedValue({
    ...plan,
    total: 0,
    counts: { project: 0, job: 0, export: 0, environment_operation: 0 },
    files_total: 0,
    bytes_total: 0,
    pending,
  });
  render(<TrashClearDialog onClose={vi.fn()} onDone={vi.fn()} />);
  expect(
    await screen.findByText('File cleanup is incomplete. Continue the saved operation.'),
  ).toBeVisible();
  expect(api.clearTrash).not.toHaveBeenCalled();
  const resume = screen.getByRole('button', { name: 'Continue file cleanup' });
  expect(resume).toBeEnabled();
  await userEvent.dblClick(resume);
  expect(await screen.findByText('Deleted 2/2 files.')).toBeVisible();
  expect(api.clearTrash).toHaveBeenCalledTimes(1);
  expect(api.clearTrash).toHaveBeenCalledWith({
    request_id: pending.request_id,
    expected_revision: pending.plan_revision,
    expected_total: pending.cleared,
  });
});

it('rejects incomplete, nonfinite and contradictory clear claims rather than showing fake completion', () => {
  expect(decodeTrashPlan(plan)).toEqual(plan);
  for (const malformed of [
    { ...plan, total: 25 },
    { ...plan, blocked: 205 },
    { ...plan, total: 25001 },
    { ...plan, counts: { ...plan.counts, job: -1 } },
    { ...plan, counts: { ...plan.counts, unknown: 1 } },
  ])
    expect(() => decodeTrashPlan(malformed)).toThrow();
  expect(decodeTrashClearReceipt(receipt)).toEqual(receipt);
  for (const malformed of [
    { ...receipt, files_deleted: 3 },
    { ...receipt, cleared: 1 },
    { ...receipt, cleared: Infinity },
    { ...receipt, status: 'cleanup_pending' },
  ])
    expect(() => decodeTrashClearReceipt(malformed)).toThrow();
});
