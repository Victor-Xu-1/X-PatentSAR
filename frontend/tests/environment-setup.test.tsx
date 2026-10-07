import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';
import { health } from './fixtures';

beforeEach(() => {
  sessionStorage.removeItem(pendingEnvironmentKey);
  vi.spyOn(api, 'environments').mockResolvedValue(completeEnvironmentCatalog());
  vi.spyOn(api, 'runtime').mockResolvedValue({
    product: health.product,
    storage: { state_root: '/srv/wsl/state', platform: 'linux' },
    interpreters: [],
    capabilities: health.capabilities,
  });
  vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
});
afterEach(() => sessionStorage.removeItem(pendingEnvironmentKey));
const props = () => ({ product: health.product, operationId: null, onOperation: vi.fn() });
function startOperation() {
  return vi.spyOn(api, 'createEnvironmentOperation').mockImplementation(async (request) => ({
    ...environmentOperation,
    request_id: request.request_id,
    action: request.action,
    component_ids: request.component_ids,
    completed_components: [],
  }));
}

describe('complete setup uses only the published plan', () => {
  it('defaults absent setup metadata to an empty plan and rejects invalid supplied values', () => {
    const legacy: Record<string, unknown> = { ...completeEnvironmentCatalog() };
    delete legacy.setup_component_ids;
    expect(decodeEnvironmentCatalog(legacy)).toMatchObject({ setup_component_ids: [] });
    for (const setup_component_ids of [null, 'all', ['cuda'], ['base', 'base']]) {
      expect(() =>
        decodeEnvironmentCatalog({
          ...completeEnvironmentCatalog(),
          setup_component_ids,
        }),
      ).toThrow('契约');
    }
  });
  it('presents one compact overview and no fragmented install controls before consent', async () => {
    const start = startOperation();
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByRole('heading', { name: '完整运行环境' })).toBeVisible();
    expect(screen.getByText('已就绪 0/6')).toBeVisible();
    expect(screen.getByText('PDF 提取 · 结构识别 · 六项指标')).toBeVisible();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeEnabled();
    expect(screen.queryAllByRole('button', { name: /^安装 / })).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: '推荐组合' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '存储位置' })).toBeVisible();
    expect(screen.queryByLabelText('集成环境安装目录')).not.toBeInTheDocument();
    expect(screen.queryByText('运行诊断')).not.toBeInTheDocument();
    expect(screen.queryByText(/操作历史|操作日志/)).not.toBeInTheDocument();
    expect(screen.queryByText(/目标：|实测：|安装位置：/)).not.toBeInTheDocument();
    expect(api.runtime).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
    expect(start).not.toHaveBeenCalled();
  });
  it('discloses all six components then sends exactly one install request after one consent', async () => {
    const catalog = completeEnvironmentCatalog();
    const start = startOperation();
    const options = props();
    render(<EnvironmentPage {...options} />);
    const opener = await screen.findByRole('button', { name: '一键部署全部环境' });
    await userEvent.click(opener);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(catalog.settings.install_root);
    expect(dialog).toHaveTextContent('CPU');
    expect(dialog.querySelectorAll('[data-install-component]')).toHaveLength(6);
    const ids = Array.from(dialog.querySelectorAll('[data-install-component]')).map((entry) =>
      entry.getAttribute('data-install-component'),
    );
    expect(ids).toEqual(catalog.setup_component_ids);
    for (const component of catalog.components) {
      const entry = dialog.querySelector('[data-install-component="' + component.id + '"]')!;
      expect(entry).toHaveTextContent(component.name);
      expect(entry).toHaveTextContent(component.version);
      expect(entry).toHaveTextContent(component.license);
      expect(entry).toHaveTextContent(component.source_url);
      expect(entry).toHaveTextContent('下载：');
    }
    expect(dialog.querySelector('[data-install-component="admet"]')).not.toBeNull();
    expect(dialog.querySelector('[data-install-component="admet-models"]')).not.toBeNull();
    const confirm = within(dialog).getByRole('button', { name: '确认下载并安装' });
    expect(confirm).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('checkbox'));
    await userEvent.click(confirm);
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'install',
        component_ids: catalog.setup_component_ids,
        expected_revision: 3,
        request_id: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/),
      }),
    );
    expect(options.onOperation).toHaveBeenCalledWith(environmentOperation.id);
  });
  it.each(['unchecked', 'stale'] as const)(
    'allows existing %s paths only in complete deployment, not single install',
    async (verification) => {
      const catalog = completeEnvironmentCatalog();
      catalog.components = catalog.components.map((component) => ({
        ...component,
        presence: 'present',
        verification,
        status: 'unchecked',
        location: '/srv/wsl/envs/previous-' + component.id,
      }));
      vi.spyOn(api, 'environments').mockResolvedValue(catalog);
      const start = startOperation();
      render(<EnvironmentPage {...props()} />);
      await userEvent.click(await screen.findByRole('button', { name: '存储位置' }));
      await userEvent.click(screen.getByText('环境详情', { selector: 'summary' }));
      expect(screen.getByRole('button', { name: '先检测 基础运行环境' })).toBeDisabled();
      await userEvent.click(screen.getByRole('button', { name: '取消' }));
      await userEvent.click(screen.getByRole('button', { name: '一键部署全部环境' }));
      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveTextContent('复检');
      await userEvent.click(within(dialog).getByRole('checkbox'));
      await userEvent.click(within(dialog).getByRole('button', { name: '确认下载并安装' }));
      await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
      expect(start.mock.calls[0]![0].component_ids).toEqual(catalog.setup_component_ids);
    },
  );
  it('disables setup for missing/partial plan metadata without guessing from presets or legacy ready', async () => {
    const ready = readyEnvironmentCatalog();
    const invalid = [
      { ...ready, setup_component_ids: [] },
      { ...ready, setup_component_ids: ready.setup_component_ids.slice(0, 4) },
      { ...ready, components: ready.components.slice(0, 4) },
    ];
    const start = startOperation();
    for (const catalog of invalid) {
      vi.spyOn(api, 'environments').mockResolvedValue(catalog);
      const view = render(<EnvironmentPage {...props()} />);
      expect(await screen.findByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
      expect(screen.getByText(/完整部署计划/)).toBeVisible();
      expect(screen.queryByRole('button', { name: '环境已就绪' })).not.toBeInTheDocument();
      view.unmount();
    }
    expect(start).not.toHaveBeenCalled();
  });
  it('does not infer verified-ready from old component defaults', async () => {
    const ready = readyEnvironmentCatalog();
    const components = ready.components.map((component) => {
      const legacy: Record<string, unknown> = { ...component };
      for (const key of ['presence', 'verification', 'checked_at', 'last_check'])
        delete legacy[key];
      return legacy;
    });
    vi.spyOn(api, 'environments').mockResolvedValue(
      decodeEnvironmentCatalog({
        ...ready,
        components,
        setup_component_ids: [],
      }),
    );
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByText('已就绪 0/6')).toBeVisible();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
    expect(screen.queryByText('已安装·已验证')).not.toBeInTheDocument();
  });
  it('disables ready setup and rechecks exactly the server plan without an install', async () => {
    const catalog = readyEnvironmentCatalog();
    vi.spyOn(api, 'environments').mockResolvedValue(catalog);
    const start = startOperation();
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByRole('button', { name: '环境已就绪' })).toBeDisabled();
    expect(screen.getByText('已就绪 6/6')).toBeVisible();
    expect(screen.queryAllByRole('button', { name: /^已安装 / })).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: '重新检测' }));
    expect(start).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        action: 'inspect',
        component_ids: catalog.setup_component_ids,
      }),
    );
  });
  it.each(['status', 'license', 'location', 'setup', 'dependency', 'revision'] as const)(
    'invalidates consent if selected %s metadata changes',
    async (field) => {
      const catalog = completeEnvironmentCatalog();
      const changed = completeEnvironmentCatalog();
      if (field === 'setup')
        changed.setup_component_ids = [...changed.setup_component_ids].reverse();
      else if (field === 'revision') changed.settings = { ...changed.settings, revision: 4 };
      else
        changed.components = changed.components.map((component) =>
          component.id !== 'base'
            ? component
            : {
                ...component,
                ...(field === 'status'
                  ? ({ presence: 'present', status: 'ready', verification: 'current' } as const)
                  : {}),
                ...(field === 'license' ? { license: 'changed-license' } : {}),
                ...(field === 'location' ? { location: '/srv/wsl/envs/new-binding' } : {}),
                ...(field === 'dependency' ? { dependencies: [] } : {}),
              },
        );
      vi.spyOn(api, 'environments').mockResolvedValueOnce(catalog).mockResolvedValue(changed);
      const start = startOperation();
      render(<EnvironmentPage {...props()} />);
      await userEvent.click(await screen.findByRole('button', { name: '一键部署全部环境' }));
      const dialog = screen.getByRole('dialog');
      await userEvent.click(within(dialog).getByRole('checkbox'));
      await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
      await waitFor(() => expect(api.environments).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(within(dialog).getByRole('button', { name: '确认下载并安装' })).toBeDisabled(),
      );
      expect(start).not.toHaveBeenCalled();
    },
  );
  it('keeps active progress/cancel visible, with identifiers/logs/history collapsed', async () => {
    const catalog = completeEnvironmentCatalog();
    catalog.active_operation = {
      ...environmentOperation,
      component_ids: catalog.setup_component_ids,
    };
    catalog.operations = [catalog.active_operation];
    vi.spyOn(api, 'environments').mockResolvedValue(catalog);
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(catalog.active_operation);
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByRole('button', { name: '取消此环境操作' })).toBeVisible();
    expect(screen.getByRole('progressbar', { name: '环境操作已完成组件' })).toBeVisible();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
    expect(screen.queryByText('操作详情')).not.toBeInTheDocument();
    expect(screen.queryByText(/操作历史|操作日志/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('环境操作日志')).not.toBeInTheDocument();
  });
  it('reports a failed producer visibly without claiming ready or making another write', async () => {
    const failed = {
      ...environmentOperation,
      status: 'failed' as const,
      error: { code: 'environment_resource_limit', message: '检测资源不足，未重装' },
    };
    const catalog = completeEnvironmentCatalog();
    catalog.operations = [failed];
    vi.spyOn(api, 'environments').mockResolvedValue(catalog);
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(failed);
    const start = startOperation();
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByText('检测资源不足，未重装')).toBeVisible();
    expect(screen.queryByRole('button', { name: '环境已就绪' })).not.toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
  });
  it('keeps complete uncertain requests across reload without replaying them', async () => {
    const catalog = completeEnvironmentCatalog();
    const start = vi
      .spyOn(api, 'createEnvironmentOperation')
      .mockRejectedValue(new ApiError(0, 'network_error', '结果未知', true));
    const view = render(<EnvironmentPage {...props()} />);
    await userEvent.click(await screen.findByRole('button', { name: '一键部署全部环境' }));
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: '确认下载并安装' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('结果未知');
    const request = start.mock.calls[0]![0];
    expect(request.component_ids).toEqual(catalog.setup_component_ids);
    view.unmount();
    await act(async () => {
      render(<EnvironmentPage {...props()} />);
    });
    expect(start).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem(pendingEnvironmentKey)!)).toMatchObject({ request });
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
  });
});
