import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { EnvironmentProgress } from '../src/features/environment/EnvironmentProgress';
import { InstallConfirmation } from '../src/features/environment/InstallConfirmation';
import { StorageLocations } from '../src/features/environment/StorageLocations';
import { JobRecord } from '../src/features/jobs/JobRecord';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { dateText, acceptanceLabels } from '../src/model/presentation';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
import { job, project, projectListResource } from './fixtures';

describe('supporting-page craft and accessible state contracts', () => {
  it('uses the visible task-details caption as its sole accessible name', () => {
    render(<JobRecord job={job} />);
    const disclosure = screen.getByText('任务详情', { selector: 'summary' });
    expect(disclosure).toHaveAccessibleName('任务详情');
    expect(screen.queryByLabelText('提取阶段详情')).not.toBeInTheDocument();
    expect(disclosure.parentElement).not.toHaveAttribute('open');
    fireEvent.click(disclosure);
    expect(disclosure.parentElement).toHaveAttribute('open');
    expect(screen.getByText(`任务 ${job.id}`)).toBeVisible();
  });

  it.each([true, false])(
    'associates visible recent-file metadata with its open button (PDF available: %s)',
    (available) => {
      const value = {
        ...project,
        title: '很长的原始专利名称'.repeat(8),
        pdf: { ...project.pdf, available },
        acceptance: { state: 'failed' as const, errors: ['retained source finding'] },
      };
      render(
        <ProjectsPage
          resource={{ data: { items: [value] }, loading: false, error: null, reload: vi.fn() }}
          onOpen={vi.fn()}
          onUpload={vi.fn()}
        />,
      );
      const open = screen.getByRole('button', { name: `打开 ${value.title}` });
      const source = available ? `${value.pdf.page_count} 页` : '原文未提供';
      expect(open).toHaveAccessibleDescription(
        `${source} ${acceptanceLabels.failed} ${dateText(value.updated_at)}`,
      );
      expect(open.querySelector('strong')).toHaveTextContent(value.title);
      expect(open.querySelector('time')).toHaveAttribute('datetime', value.updated_at);
      expect(value.acceptance.errors).toEqual(['retained source finding']);
    },
  );

  it('exposes the actual task history as a named native list and preserves keyboard opening', async () => {
    const finished = {
      ...job,
      status: 'complete' as const,
      stages: job.stages.map((stage) => ({ ...stage, status: 'ok' as const })),
    };
    vi.spyOn(api, 'jobs').mockResolvedValue({
      items: [finished, { ...finished, id: 'second-contract-job' }],
    });
    vi.spyOn(api, 'job').mockResolvedValue(finished);
    const onOpen = vi.fn();
    render(<JobsPage projects={projectListResource([project])} ready onOpen={onOpen} />);
    const list = await screen.findByRole('list', { name: '提取任务记录' });
    expect(list.tagName).toBe('UL');
    const rows = within(list)
      .getAllByRole('listitem')
      .filter((row) => row.parentElement === list);
    expect(rows).toHaveLength(2);
    expect(rows.every((row) => row.tagName === 'LI')).toBe(true);
    expect(within(list).getAllByLabelText('任务详情')).toHaveLength(2);
    const open = within(rows[0]!).getByRole('button', { name: project.title });
    open.focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(project.id);
  });

  it.each(['install', 'inspect'] as const)(
    'distinguishes queued %s from a running operation without fabricating counts',
    (action) => {
      const selected = {
        ...environmentOperation,
        action,
        status: 'queued' as const,
        started_at: null,
        completed_components: [],
      };
      const props = {
        selected,
        selectionId: selected.id,
        loading: false,
        busy: false,
        readError: false,
        onCancel: vi.fn().mockResolvedValue(undefined),
        onReload: vi.fn(),
      };
      const view = render(<EnvironmentProgress {...props} />);
      expect(
        screen.getByText(action === 'install' ? '等待配置环境' : '等待检测环境'),
      ).toBeVisible();
      const progress = screen.getByRole('progressbar', { name: '环境操作已完成组件' });
      expect(progress).toHaveAttribute('value', '0');
      expect(progress).toHaveAttribute('max', String(selected.component_ids.length));
      view.rerender(
        <EnvironmentProgress
          {...props}
          selected={{ ...selected, status: 'running', started_at: environmentOperation.created_at }}
        />,
      );
      expect(
        screen.getByText(action === 'install' ? '正在配置环境' : '正在检测环境'),
      ).toBeVisible();
      expect(progress).toHaveAttribute('value', '0');
      expect(props.onCancel).not.toHaveBeenCalled();
    },
  );

  it('announces a storage revision conflict while preserving all drafts and the explicit CAS recovery', async () => {
    const settings = completeEnvironmentCatalog().settings;
    const save = vi.fn().mockResolvedValue(null);
    const props = {
      settings,
      disabled: false,
      busy: false,
      requestError: null,
      onClose: vi.fn(),
      onSave: save,
    };
    const view = render(<StorageLocations {...props} />);
    const next = '/srv/wsl/data/patentsar/review-next';
    fireEvent.change(screen.getByLabelText('生成结果目录'), { target: { value: next } });
    const updated = {
      ...settings,
      result_root: '/srv/wsl/data/patentsar/server-next',
      revision: settings.revision + 1,
    };
    view.rerender(<StorageLocations {...props} settings={updated} />);
    expect(screen.getByRole('alert')).toHaveTextContent('服务器配置已更新，未覆盖你的输入');
    expect(screen.getByLabelText('生成结果目录')).toHaveValue(next);
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '使用最新版本并保留输入' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('生成结果目录')).toHaveValue(next);
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(save).toHaveBeenCalledExactlyOnceWith(
      { install_root: settings.install_root, upload_root: settings.upload_root, result_root: next },
      updated.revision,
    );
  });

  it.each([
    ['revision', '安装目录配置已变化'],
    ['plan', '组件状态或依赖计划已变化'],
    ['license', '服务端未提供完整许可证信息'],
  ] as const)(
    'announces and associates invalidated %s consent without submitting installation',
    async (kind, reason) => {
      const catalog = completeEnvironmentCatalog();
      const plan = {
        scope: 'complete' as const,
        settings: catalog.settings,
        components: catalog.components,
        requested: catalog.setup_component_ids,
      };
      const props = {
        plan,
        currentRevision: catalog.settings.revision,
        planCurrent: true,
        busy: false,
        onClose: vi.fn(),
        onConfirm: vi.fn().mockResolvedValue(undefined),
      };
      const view = render(<InstallConfirmation {...props} />);
      await userEvent.click(screen.getByRole('checkbox'));
      expect(screen.getByRole('button', { name: '确认下载并安装' })).toBeEnabled();
      view.rerender(
        <InstallConfirmation
          {...props}
          currentRevision={catalog.settings.revision + (kind === 'revision' ? 1 : 0)}
          planCurrent={kind !== 'plan'}
          plan={
            kind === 'license'
              ? {
                  ...plan,
                  components: plan.components.map((component, index) =>
                    index === 0 ? { ...component, license: '' } : component,
                  ),
                }
              : plan
          }
        />,
      );
      const alert = screen.getByRole('alert');
      expect(alert).toHaveTextContent(reason);
      const consent = screen.getByRole('checkbox');
      expect(consent).toBeDisabled();
      expect(consent).toHaveAccessibleDescription(alert.textContent!);
      const install = screen.getByRole('button', { name: '确认下载并安装' });
      expect(install).toBeDisabled();
      await userEvent.click(install);
      expect(props.onConfirm).not.toHaveBeenCalled();
      expect(screen.getByRole('list', { name: '环境安装计划' })).toBeVisible();
      await userEvent.click(screen.getByRole('button', { name: '取消' }));
      expect(props.onClose).toHaveBeenCalledOnce();
    },
  );
});
