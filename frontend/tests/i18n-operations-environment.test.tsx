import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import { ComponentLibrary } from '../src/features/environment/ComponentLibrary';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { EnvironmentProgress } from '../src/features/environment/EnvironmentProgress';
import { InstallConfirmation } from '../src/features/environment/InstallConfirmation';
import { StorageLocations } from '../src/features/environment/StorageLocations';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';
import { health } from './fixtures';
import { recoverySettings } from './llm-recovery-fixtures';
import { change, setupOperationsLocale, switchTo } from './i18n-operations-fixtures';

setupOperationsLocale();

describe('operations locale: environment', () => {
  it('renders the English environment page and retains details without installing or reloading on a flip', async () => {
    switchTo('en');
    const read = vi.spyOn(api, 'environments').mockResolvedValue(completeEnvironmentCatalog());
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
    expect(await screen.findByText('Ready 0/8')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Environment details' }));
    const dialog = screen.getByRole('dialog', { name: 'Environment details' });
    await userEvent.click(within(dialog).getByText('Component details', { selector: 'summary' }));
    expect(
      within(dialog).getByRole('heading', { name: 'Local stereo-rescue runtime' }),
    ).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '环境详情' })).toBe(dialog);
    expect(
      within(dialog).getByText('组件详情', { selector: 'summary' }).closest('details'),
    ).toHaveAttribute('open');
    expect(read).toHaveBeenCalledTimes(1);
    expect(install).not.toHaveBeenCalled();
  });

  it('retains a storage draft and named validation error across English and Chinese', async () => {
    const settings = completeEnvironmentCatalog().settings;
    const save = vi.fn();
    render(
      <StorageLocations
        settings={settings}
        disabled={false}
        busy={false}
        requestError={null}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    change('Upload directory', '../专利');
    const input = screen.getByLabelText('Upload directory');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The upload directory must be within',
    );
    switchTo('zh-CN');
    expect(await screen.findByRole('alert')).toHaveTextContent('上传文件目录须位于');
    switchTo('en');
    expect(screen.getByLabelText('Upload directory')).toBe(input);
    expect(input).toHaveValue('../专利');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The upload directory must be within the server-approved root ' + settings.allowed_data_root,
    );
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toHaveTextContent('上传文件目录须位于');
    expect(save).not.toHaveBeenCalled();
  });

  it('preserves download/license consent and the exact component plan without installing', async () => {
    const catalog = completeEnvironmentCatalog();
    const confirm = vi.fn();
    render(
      <InstallConfirmation
        plan={{
          scope: 'complete',
          components: catalog.components,
          settings: catalog.settings,
          requested: catalog.setup_component_ids,
        }}
        currentRevision={catalog.settings.revision}
        planCurrent
        busy={false}
        onClose={vi.fn()}
        onConfirm={confirm}
      />,
    );
    const dialog = screen.getByRole('dialog');
    const consent = within(dialog).getByRole('checkbox');
    expect(screen.getByRole('button', { name: 'Confirm download & installation' })).toBeDisabled();
    await userEvent.click(consent);
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认完整环境部署' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Confirm complete environment setup' })).toBe(dialog);
    expect(within(dialog).getByRole('checkbox')).toBe(consent);
    expect(consent).toBeChecked();
    expect(screen.getByRole('button', { name: 'Confirm download & installation' })).toBeEnabled();
    const ids = Array.from(dialog.querySelectorAll('[data-install-component]')).map((node) =>
      node.getAttribute('data-install-component'),
    );
    expect(ids).toEqual(catalog.setup_component_ids);
    for (const component of catalog.components) expect(dialog).toHaveTextContent(component.version);
    switchTo('zh-CN');
    expect(consent).toBeChecked();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('localizes reviewed component IDs while retaining paths, versions, licenses and diagnostics', () => {
    switchTo('en');
    const catalog = readyEnvironmentCatalog();
    const component = {
      ...catalog.components[0]!,
      version: '版本原文',
      detected_version: '实测原文',
      location: '/srv/wsl/envs/基础提取环境',
      license: '模型许可',
      problem: '设置已保存。',
      checks: [{ name: '模型', ok: true, message: '设置已保存。' }],
    };
    render(
      <ComponentLibrary
        components={[component]}
        disabled={false}
        onInspect={vi.fn()}
        onInstall={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Managed installer' })).toBeVisible();
    expect(screen.getByText('Target: 版本原文')).toBeVisible();
    expect(screen.getByText('Detected: 实测原文')).toBeVisible();
    expect(screen.getByText('Location: /srv/wsl/envs/基础提取环境')).toBeVisible();
    expect(screen.getByText('License: 模型许可')).toBeInTheDocument();
    expect(screen.getByText('Passed · 模型：设置已保存。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Installed Managed installer' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check Managed installer' })).toBeEnabled();
  });

  it('updates environment progress and cancel confirmation but keeps raw failures verbatim', async () => {
    const cancel = vi.fn();
    render(
      <EnvironmentProgress
        selected={{ ...environmentOperation, error: { code: 'raw', message: '设置已保存。' } }}
        selectionId={environmentOperation.id}
        loading={false}
        busy={false}
        readError={false}
        onCancel={cancel}
        onReload={vi.fn()}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: 'Cancel this environment operation' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Cancel environment setup?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '取消环境配置？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Cancel environment setup?' })).toBe(dialog);
    expect(
      screen.getByRole('progressbar', { name: 'Completed environment components' }),
    ).toHaveAttribute('value', '1');
    expect(screen.getByText('设置已保存。')).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '取消环境配置？' })).toBe(dialog);
    expect(cancel).not.toHaveBeenCalled();
  });

  it('keeps an uncertain environment request across language changes and remount without replay', async () => {
    const catalog = completeEnvironmentCatalog();
    vi.spyOn(api, 'environments').mockResolvedValue(catalog);
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    const start = vi
      .spyOn(api, 'createEnvironmentOperation')
      .mockRejectedValue(
        new ApiError(
          0,
          'network',
          '连接中断，写入结果未知。请先刷新状态，再决定是否重新提交。',
          true,
        ),
      );
    const page = () => (
      <EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />
    );
    const view = render(page());
    await userEvent.click(
      await screen.findByRole('button', { name: 'Set up complete environment' }),
    );
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm download & installation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('the write result is unknown');
    const saved = sessionStorage.getItem(pendingEnvironmentKey);
    expect(saved).not.toBeNull();
    expect(start.mock.calls[0]![0].component_ids).toEqual(catalog.setup_component_ids);
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toHaveTextContent('连接中断，写入结果未知');
    switchTo('en');
    expect(screen.getByRole('alert')).toHaveTextContent('the write result is unknown');
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBe(saved);
    view.unmount();
    render(page());
    expect(
      await screen.findByRole('region', { name: 'Environment operation recovery' }),
    ).toBeVisible();
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBe(saved);
    expect(start).toHaveBeenCalledTimes(1);
  });
});
