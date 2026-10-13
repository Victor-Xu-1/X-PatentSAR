import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { sarApi, createSARApi } from '../src/api/sarApi';
import { ApiClient } from '../src/api/client';
import { decodeSARHistory } from '../src/api/sarHistory';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { emptyRoute, parseRoute, routeHash } from '../src/model/route';
import { setLocale } from '../src/i18n';
import { json, projectListResource, session } from './fixtures';
import { sarDataset, sarJob } from './sar-fixtures';

const item = {
  job: { ...sarJob, status: 'complete' as const },
  dataset_title: 'Dataset 原文',
  title: 'Study 原文',
};
const response = { items: [item], total: 1, page: 1, page_size: 25, active_count: 0 };
beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
  vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [sarDataset], total: 1 });
  vi.spyOn(sarApi, 'history').mockResolvedValue(response);
});
function page() {
  const open = vi.fn();
  render(<JobsPage projects={projectListResource([])} ready onOpen={vi.fn()} onOpenSAR={open} />);
  return open;
}
async function chooseSAR() {
  await userEvent.click(screen.getByRole('tab', { name: 'SAR analysis' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'View results' })).toBeEnabled());
}

it('loads SAR history only on its tab and opens the exact stored dataset/job without submitting work', async () => {
  const open = page();
  const analyse = vi.spyOn(sarApi, 'analyse');
  expect(sarApi.history).not.toHaveBeenCalled();
  await chooseSAR();
  expect(screen.getByRole('tab', { name: 'SAR analysis' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(screen.getByText('Dataset 原文')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'View results' }));
  expect(open).toHaveBeenCalledExactlyOnceWith(item.job.dataset_id, item.job.id);
  expect(analyse).not.toHaveBeenCalled();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('tab', { name: '专利提取' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Study 原文' })).toBeVisible();
  expect(screen.getByRole('button', { name: '查看结果' })).toBeEnabled();
});

it('filters with server queries and retains disabled known records while an error is unresolved', async () => {
  page();
  await chooseSAR();
  await userEvent.selectOptions(screen.getByLabelText('Filter SAR status'), 'complete');
  await waitFor(() =>
    expect(sarApi.history).toHaveBeenLastCalledWith(
      { page: 1, datasetId: '', status: 'complete' },
      expect.any(AbortSignal),
    ),
  );
  vi.mocked(sarApi.history).mockRejectedValue(new Error('History unavailable'));
  await userEvent.click(screen.getByRole('button', { name: 'Refresh SAR tasks' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('History unavailable');
  expect(screen.getByRole('button', { name: 'View results' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Remove SAR job' })).toBeDisabled();
  expect(screen.getByLabelText('Filter SAR status')).toHaveValue('complete');
  vi.mocked(sarApi.history).mockResolvedValue(response);
  await userEvent.click(within(screen.getByRole('alert')).getByRole('button'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'View results' })).toBeEnabled());
});

it('uses existing confirmed soft removal', async () => {
  const remove = vi.spyOn(sarApi, 'removeJob').mockImplementation(async () => {
    vi.mocked(sarApi.history).mockResolvedValue({ ...response, items: [], total: 0 });
  });
  page();
  await chooseSAR();
  await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
  expect(remove).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
  await waitFor(() => expect(remove).toHaveBeenCalledExactlyOnceWith(item.job.id));
  expect(await screen.findByText('No SAR analyses to show')).toBeVisible();
});

it('round-trips only the selected history module, not scientific workflow parameters', () => {
  const route = { ...emptyRoute, view: 'jobs' as const, jobModule: 'sar' as const };
  expect(routeHash(route)).toBe('#/jobs?module=sar');
  expect(parseRoute(routeHash(route))).toEqual(route);
  expect(parseRoute('#/jobs?module=unknown').jobModule).toBeUndefined();
  expect(parseRoute('#/sar?module=sar').jobModule).toBeUndefined();
  expect(routeHash({ ...route, view: 'new-task' })).toBe('#/new-task');
});

it('keeps running tasks visible without a delete action and follows bounded server pages', async () => {
  vi.mocked(sarApi.history).mockImplementation(async (query) => ({
    ...response,
    page: query.page,
    total: 26,
    active_count: 1,
    items: [{ ...item, job: { ...item.job, status: 'running' } }],
  }));
  page();
  await userEvent.click(screen.getByRole('tab', { name: 'SAR analysis' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'View task' })).toBeEnabled());
  expect(screen.queryByRole('button', { name: 'Remove SAR job' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
  await waitFor(() =>
    expect(sarApi.history).toHaveBeenLastCalledWith(
      { page: 2, datasetId: '', status: '' },
      expect.any(AbortSignal),
    ),
  );
  await userEvent.click(screen.getByRole('tab', { name: 'Patent extraction' }));
  expect(screen.getByRole('tab', { name: 'Patent extraction' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

it('checks page identities and bounds and requests only the shared read-only API', async () => {
  expect(decodeSARHistory(response)).toEqual(response);
  for (const bad of [
    { ...response, active_count: 2 },
    { ...response, page_size: 101 },
    { ...response, items: [item, item], total: 2 },
    { ...response, total: 0 },
  ])
    expect(() => decodeSARHistory(bad)).toThrow();
  const transport = vi.fn<typeof fetch>(async (url) =>
    json(String(url).endsWith('/session') ? session : response),
  );
  const client = createSARApi(new ApiClient(transport), transport);
  const query = { page: 1, datasetId: item.job.dataset_id, status: 'complete' as const };
  await client.history(query, new AbortController().signal);
  expect(String(transport.mock.calls[1]![0])).toContain(
    '/sar/jobs?page=1&page_size=25&dataset_id=',
  );
  expect(transport.mock.calls.every(([, request]) => request?.method === 'GET')).toBe(true);
  transport.mockResolvedValue(json({ ...response, page: 2 }));
  await expect(client.history(query, new AbortController().signal)).rejects.toThrow();
});
