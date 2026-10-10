import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
import { health, page, results, session, projectListResource } from './fixtures';
import {
  historyEntry,
  historyList,
  trashed,
  historyProject as project,
  historyJob as job,
} from './history-fixtures';

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(api, 'historyEntry').mockResolvedValue(historyEntry());
  vi.spyOn(api, 'history').mockResolvedValue(historyList([]));
  vi.spyOn(api, 'deleteHistory').mockResolvedValue(trashed(historyEntry()));
  vi.spyOn(api, 'restoreHistory').mockResolvedValue(historyEntry());
});
async function confirmDeletion() {
  const dialog = screen.getAllByRole('dialog').at(-1)!;
  const confirm = within(dialog).getByRole('button', { name: '确认移入回收站' });
  await waitFor(() => expect(confirm).toBeEnabled());
  await userEvent.click(confirm);
}

describe('history mutations refresh only affected resource views', () => {
  it('adds per-project files/delete and trash controls, reloads projects and propagates the authoritative change', async () => {
    const entry = historyEntry();
    const resource = { data: { items: [project] }, error: null, loading: false, reload: vi.fn() };
    const onChanged = vi.fn();
    render(
      <ProjectsPage
        resource={resource}
        onOpen={vi.fn()}
        onUpload={vi.fn()}
        onHistoryChanged={onChanged}
      />,
    );
    expect(screen.getByRole('button', { name: `已生成文件 ${project.title}` })).toBeVisible();
    expect(screen.getByRole('button', { name: '回收站' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: `删除 ${project.title}` }));
    await confirmDeletion();
    await waitFor(() => expect(resource.reload).toHaveBeenCalledOnce());
    expect(onChanged).toHaveBeenCalledExactlyOnceWith(trashed(entry));
  });
  it('job delete availability comes from preview, not raw status, and rereads jobs after a confirmed mutation', async () => {
    const terminal = { ...job, status: 'complete' as const };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [terminal] });
    vi.spyOn(api, 'job').mockResolvedValue(terminal);
    const blocked = historyEntry({
      kind: 'job',
      id: job.id,
      can_delete: false,
      blocked_reason: '归属尚未核对。',
    });
    vi.mocked(api.historyEntry)
      .mockResolvedValueOnce(blocked)
      .mockResolvedValue({ ...blocked, can_delete: true, blocked_reason: null });
    vi.mocked(api.deleteHistory).mockResolvedValue(trashed(blocked));
    render(<JobsPage projects={projectListResource([project])} ready={false} onOpen={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: /^删除 / }));
    expect(await screen.findByText('归属尚未核对。')).toBeVisible();
    expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeDisabled();
    expect(api.deleteHistory).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '刷新核对状态' }));
    const before = vi.mocked(api.jobs).mock.calls.length;
    await confirmDeletion();
    await waitFor(() => expect(vi.mocked(api.jobs).mock.calls.length).toBeGreaterThan(before));
    expect(api.deleteHistory).toHaveBeenCalledExactlyOnceWith('job', job.id, blocked.revision);
  });
  it('clears a removed job project filter rather than retaining an inaccessible selection', async () => {
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
    const view = render(
      <JobsPage projects={projectListResource([project])} ready={false} onOpen={vi.fn()} />,
    );
    await screen.findByText('尚无提取任务');
    await userEvent.selectOptions(screen.getByLabelText('筛选任务所属项目'), project.id);
    await waitFor(() =>
      expect(api.jobs).toHaveBeenLastCalledWith(project.id, expect.any(AbortSignal)),
    );
    view.rerender(<JobsPage projects={projectListResource([])} ready={false} onOpen={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('筛选任务所属项目')).toHaveValue(''));
    expect(api.jobs).toHaveBeenLastCalledWith(null, expect.any(AbortSignal));
  });
  it('offers paged access to old jobs omitted from the normal capped list, with deletion and project filtering', async () => {
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
    const old = historyEntry({ kind: 'job', id: '4'.repeat(32), title: '旧的合成任务' });
    vi.mocked(api.history).mockResolvedValue(historyList([old], { total: 501 }));
    vi.mocked(api.historyEntry).mockResolvedValue(old);
    render(<JobsPage projects={projectListResource([project])} ready={false} onOpen={vi.fn()} />);
    await screen.findByText('尚无提取任务');
    await userEvent.selectOptions(screen.getByLabelText('筛选任务所属项目'), project.id);
    await userEvent.click(screen.getByRole('button', { name: '全部记录' }));
    expect(await screen.findByRole('button', { name: `删除 ${old.title}` })).toBeVisible();
    expect(api.history).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: 'job',
        deleted: false,
        project_id: project.id,
        page: 1,
        page_size: 50,
      }),
      expect.any(AbortSignal),
    );
    expect(screen.getByRole('button', { name: '下一页历史记录' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: `删除 ${old.title}` }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认移入回收站' })).toBeEnabled(),
    );
    expect(api.deleteHistory).not.toHaveBeenCalled();
  });
  it('deleted/restored projects stay fresh through navigation and reopen; saved results are not rewritten', async () => {
    window.location.hash = '#/projects';
    const entry = historyEntry();
    let deleted = false;
    vi.spyOn(api, 'session').mockResolvedValue(session);
    vi.spyOn(api, 'health').mockResolvedValue(health);
    vi.spyOn(api, 'projects').mockImplementation(async () => ({ items: deleted ? [] : [project] }));
    vi.spyOn(api, 'project').mockResolvedValue(project);
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'results').mockResolvedValue(results);
    vi.spyOn(api, 'page').mockResolvedValue(page);
    vi.mocked(api.historyEntry).mockImplementation(async () => (deleted ? trashed(entry) : entry));
    vi.mocked(api.history).mockImplementation(async () =>
      historyList(deleted ? [trashed(entry)] : []),
    );
    vi.mocked(api.deleteHistory).mockImplementation(async () => {
      deleted = true;
      return trashed(entry);
    });
    vi.mocked(api.restoreHistory).mockImplementation(async () => {
      deleted = false;
      return entry;
    });
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: `删除 ${project.title}` }));
    await confirmDeletion();
    expect(await screen.findByText('还没有文件')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '回收站' }));
    await userEvent.click(await screen.findByRole('button', { name: `恢复 ${entry.title}` }));
    const restore = screen.getByRole('dialog', { name: '恢复项目？' });
    await waitFor(() =>
      expect(within(restore).getByRole('button', { name: '确认恢复' })).toBeEnabled(),
    );
    await userEvent.click(within(restore).getByRole('button', { name: '确认恢复' }));
    await userEvent.click(await screen.findByRole('button', { name: '关闭' }));
    await userEvent.click(await screen.findByRole('button', { name: `打开 ${project.title}` }));
    expect(await screen.findByTitle('抑制等级 = ++')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '任务记录' }));
    await screen.findByRole('heading', { name: '任务记录' });
    await userEvent.click(screen.getByRole('button', { name: '最近文件' }));
    expect(await screen.findByRole('button', { name: `打开 ${project.title}` })).toBeVisible();
    expect(results.items[0]?.smiles).toBeNull();
    expect(api.deleteHistory).toHaveBeenCalledOnce();
    expect(api.restoreHistory).toHaveBeenCalledOnce();
  });
  it('environment terminal records delete independently, clear stale selection and leave readiness and installation alone', async () => {
    const operation = {
      ...environmentOperation,
      id: '3'.repeat(32),
      status: 'cancelled' as const,
      error: { code: 'fixture', message: '合成终态失败详情' },
    };
    const entry = historyEntry({
      kind: 'environment_operation',
      id: operation.id,
      project_id: null,
      title: '受控环境记录',
    });
    let deleted = false;
    vi.spyOn(api, 'environments').mockImplementation(async () => ({
      ...completeEnvironmentCatalog(),
      operations: deleted ? [] : [operation],
      active_operation: null,
    }));
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(operation);
    vi.mocked(api.historyEntry).mockResolvedValue(entry);
    vi.mocked(api.history).mockImplementation(async () => historyList(deleted ? [] : [entry]));
    vi.mocked(api.deleteHistory).mockImplementation(async () => {
      deleted = true;
      return trashed(entry);
    });
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    const onOperation = vi.fn();
    render(
      <EnvironmentPage
        operationId={operation.id}
        onOperation={onOperation}
        product={health.product}
      />,
    );
    expect(await screen.findByText('合成终态失败详情')).toBeVisible();
    const beforeCatalog = vi.mocked(api.environments).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: '环境详情' }));
    await userEvent.click(screen.getByRole('button', { name: '操作记录' }));
    await userEvent.click(await screen.findByRole('button', { name: `删除 ${entry.title}` }));
    expect(screen.getByRole('dialog', { name: '删除环境操作？' })).toHaveTextContent(
      '不卸载环境，也不改变环境就绪状态',
    );
    await confirmDeletion();
    await waitFor(() => expect(onOperation).toHaveBeenCalledWith(null));
    await waitFor(() => expect(screen.queryByText('合成终态失败详情')).not.toBeInTheDocument());
    expect(vi.mocked(api.environments).mock.calls.length).toBeGreaterThan(beforeCatalog);
    expect(install).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    expect(screen.queryByText(operation.id)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '回收站' }));
    expect(await screen.findByRole('dialog', { name: '回收站' })).toBeVisible();
    expect(screen.getByLabelText('回收站记录类型')).toHaveValue('environment_operation');
  });
});
