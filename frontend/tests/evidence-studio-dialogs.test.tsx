import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EnvironmentDetails } from '../src/features/environment/EnvironmentDetails';
import { EnvironmentOverview } from '../src/features/environment/EnvironmentOverview';
import { EnvironmentProgress } from '../src/features/environment/EnvironmentProgress';
import { InstallConfirmation } from '../src/features/environment/InstallConfirmation';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';
import { environmentOperation } from './environment-fixtures';

// Presentation contracts only. Real layout, focus and saved-state acceptance run
// in the parent task's bounded browser checks against isolated workspace state.
describe('Evidence Studio environment and dialog presentation', () => {
  it('groups readiness and actions without exposing paths or a component checklist', async () => {
    const catalog = completeEnvironmentCatalog();
    const inspect = vi.fn();
    const setup = vi.fn();
    const details = vi.fn();
    const { container } = render(
      <EnvironmentOverview
        catalog={catalog}
        disabled={false}
        onSetup={setup}
        onInspect={inspect}
        onDetails={details}
      />,
    );
    expect(screen.getByRole('status', { name: '环境就绪状态' })).toHaveTextContent(
      `已就绪 0/${catalog.components.length}`,
    );
    expect(container.querySelector('.environment-overview-footer')).not.toBeNull();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toHaveClass('primary');
    expect(screen.queryByText(catalog.settings.install_root)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '环境组件库' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '检测全部组件' }));
    expect(inspect).toHaveBeenCalledExactlyOnceWith(catalog.setup_component_ids);
    await userEvent.click(screen.getByRole('button', { name: '环境详情' }));
    expect(details).toHaveBeenCalledOnce();
    expect(setup).not.toHaveBeenCalled();
  });

  it('keeps actual verified readiness distinct from path presence', () => {
    const catalog = readyEnvironmentCatalog();
    catalog.components[0] = {
      ...catalog.components[0]!,
      verification: 'stale',
      status: 'unchecked',
    };
    const { container } = render(
      <EnvironmentOverview
        catalog={catalog}
        disabled={false}
        onSetup={vi.fn()}
        onInspect={vi.fn()}
        onDetails={vi.fn()}
      />,
    );
    expect(screen.getByRole('status', { name: '环境就绪状态' })).toHaveTextContent(
      `已就绪 ${catalog.components.length - 1}/${catalog.components.length} · 1 待检测`,
    );
    expect(container.querySelector('.environment-overview-icon.is-ready')).toBeNull();
    expect(screen.queryByRole('button', { name: '环境已就绪' })).not.toBeInTheDocument();
  });

  it('keeps all three locations together in the existing wide dialog with one save action', async () => {
    const catalog = readyEnvironmentCatalog();
    const save = vi.fn().mockResolvedValue(null);
    render(
      <EnvironmentDetails
        catalog={catalog}
        disabled={false}
        storageDisabled={false}
        busy={false}
        error={null}
        recovery={null}
        onClose={vi.fn()}
        onInspect={vi.fn()}
        onInstall={vi.fn()}
        onSave={save}
      />,
    );
    const dialog = screen.getByRole('dialog', { name: '环境详情' });
    expect(dialog).toHaveClass('dialog-wide', 'environment-details-dialog');
    const group = within(dialog).getByRole('group', { name: '存储目录' });
    expect(within(group).getAllByRole('textbox')).toHaveLength(3);
    const input = within(group).getByLabelText('集成环境安装目录');
    expect(input).toHaveFocus();
    expect(input).toHaveAccessibleDescription(/仅影响后续写入/);
    expect(within(dialog).getByRole('button', { name: '保存' })).toBeDisabled();
    const componentDetails = within(dialog).getByText('组件详情', { selector: 'summary' });
    expect(componentDetails.parentElement).not.toHaveAttribute('open');
    expect(within(dialog).queryByText(/操作日志|操作历史/)).not.toBeInTheDocument();
    await userEvent.clear(input);
    await userEvent.type(input, '/srv/wsl/envs/next-install');
    await userEvent.click(within(dialog).getByRole('button', { name: '保存' }));
    expect(save).toHaveBeenCalledExactlyOnceWith(
      {
        install_root: '/srv/wsl/envs/next-install',
        upload_root: catalog.settings.upload_root,
        result_root: catalog.settings.result_root,
      },
      catalog.settings.revision,
    );
  });

  it('keeps full component licenses visible and source details available before explicit consent', async () => {
    const catalog = completeEnvironmentCatalog();
    const confirm = vi.fn().mockResolvedValue(undefined);
    render(
      <InstallConfirmation
        plan={{
          scope: 'complete',
          settings: catalog.settings,
          components: catalog.components,
          requested: catalog.setup_component_ids,
        }}
        currentRevision={catalog.settings.revision}
        planCurrent
        busy={false}
        onClose={vi.fn()}
        onConfirm={confirm}
      />,
    );
    const dialog = screen.getByRole('dialog', { name: '确认完整环境部署' });
    expect(dialog).toHaveClass('environment-install-dialog');
    const plan = within(dialog).getByRole('list', { name: '环境安装计划' });
    expect(within(plan).getAllByRole('listitem')).toHaveLength(catalog.components.length);
    for (const component of catalog.components) {
      const entry = plan.querySelector(`[data-install-component="${component.id}"]`)!;
      expect(
        within(entry as HTMLElement).getByText(component.license, { exact: false }),
      ).toBeVisible();
      expect(entry).toHaveTextContent(component.source_url);
      expect(entry).toHaveTextContent(component.version);
    }
    expect(within(dialog).getAllByText('来源与位置', { selector: 'summary' })).toHaveLength(
      catalog.components.length,
    );
    const submit = within(dialog).getByRole('button', { name: '确认下载并安装' });
    expect(submit).toBeDisabled();
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('checkbox'));
    await userEvent.click(submit);
    expect(confirm).toHaveBeenCalledOnce();
  });

  it('presents only measured progress and requires cancellation confirmation', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <EnvironmentProgress
        selected={environmentOperation}
        selectionId={environmentOperation.id}
        loading={false}
        busy={false}
        readError={false}
        onCancel={cancel}
        onReload={vi.fn()}
      />,
    );
    const progress = screen.getByRole('progressbar', { name: '环境操作已完成组件' });
    expect(progress).toHaveAttribute('value', '1');
    expect(progress).toHaveAttribute('max', '2');
    expect(container.querySelector('.environment-progress-count')).toHaveTextContent('1/2');
    expect(screen.queryByText(environmentOperation.id)).not.toBeInTheDocument();
    expect(screen.queryByText(environmentOperation.log_tail[0]!)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '取消此环境操作' }));
    expect(cancel).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: '取消环境配置？' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '确认取消此环境操作' }));
    expect(cancel).toHaveBeenCalledExactlyOnceWith(environmentOperation.id);
  });
});
