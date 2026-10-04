import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { environmentCatalog, environmentOperation } from './environment-fixtures';
import { health } from './fixtures';

beforeEach(() => {
  sessionStorage.removeItem(pendingEnvironmentKey);
  vi.spyOn(api, 'environments').mockResolvedValue(environmentCatalog);
  vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
  vi.spyOn(api, 'runtime').mockResolvedValue({
    product: health.product,
    storage: { state_root: '/srv/wsl/state', platform: 'linux' },
    interpreters: [],
    capabilities: health.capabilities,
  });
});
afterEach(() => sessionStorage.removeItem(pendingEnvironmentKey));
const props = () => ({ operationId: null, onOperation: vi.fn(), product: health.product });
describe('one environment workspace and explicit installation authority', () => {
  it('renders server inventory/groups/versions and never starts installation by rendering', async () => {
    const start = vi.spyOn(api, 'createEnvironmentOperation');
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByRole('heading', { name: '安装位置' })).toBeVisible();
    expect(screen.getByRole('heading', { name: '推荐组合' })).toBeVisible();
    expect(screen.getByRole('heading', { name: '组件库' })).toBeVisible();
    expect(document.querySelector('[data-component="base"] .component-title')).toHaveTextContent(
      'locked-base',
    );
    const details = document.querySelector('[data-component="base"] details')!;
    expect(details).not.toHaveAttribute('open');
    expect(details.querySelector('.component-metadata')).not.toBeVisible();
    await userEvent.click(details.querySelector('summary')!);
    expect(details.querySelector('.component-metadata')).toBeVisible();
    expect(screen.getByText('解释器缺失')).toBeVisible();
    expect(start).not.toHaveBeenCalled();
  });
  it('requires CPU/download/license confirmation for bundles, restores focus and submits exact IDs', async () => {
    const start = vi
      .spyOn(api, 'createEnvironmentOperation')
      .mockResolvedValue(environmentOperation);
    const options = props();
    render(<EnvironmentPage {...options} />);
    const opener = await screen.findByRole('button', { name: '安装组合 推荐基础组合' });
    await userEvent.click(opener);
    expect(screen.getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
    expect(screen.getByRole('dialog')).toHaveTextContent('CPU');
    expect(screen.getByRole('dialog')).toHaveTextContent('Apache-2.0 / BSD');
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(opener).toHaveFocus();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(opener);
    await userEvent.click(screen.getByLabelText('我已确认安装目录、CPU 下载范围及上述许可证'));
    await userEvent.click(screen.getByRole('button', { name: '确认下载并安装' }));
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'install',
          component_ids: ['installer', 'base'],
          expected_revision: 3,
          request_id: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/),
        }),
      ),
    );
    expect(options.onOperation).toHaveBeenCalledWith(environmentOperation.id);
  });
  it('retains the same request ID after uncertain writes and checks catalog before permitting retry', async () => {
    const start = vi
      .spyOn(api, 'createEnvironmentOperation')
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '结果未知', true))
      .mockResolvedValueOnce(environmentOperation);
    render(<EnvironmentPage {...props()} />);
    await userEvent.click(await screen.findByRole('button', { name: '检测全部组件' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('结果未知');
    const first = start.mock.calls[0]![0];
    expect(JSON.parse(sessionStorage.getItem(pendingEnvironmentKey)!)).toMatchObject({
      kind: 'operation',
      request: first,
    });
    expect(screen.queryByRole('button', { name: '使用相同请求 ID 重试' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '检查服务器状态' }));
    await userEvent.click(await screen.findByRole('button', { name: '使用相同请求 ID 重试' }));
    expect(start).toHaveBeenLastCalledWith(first);
    expect(start).toHaveBeenCalledTimes(2);
  });
  it('recovers an uncertain persisted request after reload without resubmitting it', async () => {
    const request = {
      action: 'install',
      component_ids: ['installer', 'base'],
      request_id: environmentOperation.request_id,
      expected_revision: 3,
    };
    sessionStorage.setItem(pendingEnvironmentKey, JSON.stringify({ kind: 'operation', request }));
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...environmentCatalog,
      active_operation: environmentOperation,
      operations: [environmentOperation],
    });
    const start = vi.spyOn(api, 'createEnvironmentOperation');
    const options = props();
    render(<EnvironmentPage {...options} />);
    await userEvent.click(await screen.findByRole('button', { name: '检查服务器状态' }));
    await waitFor(() => expect(options.onOperation).toHaveBeenCalledWith(environmentOperation.id));
    expect(start).not.toHaveBeenCalled();
  });
  it('shows durable interrupted/failure logs as inert text, not installed/ready success', async () => {
    const operation = {
      ...environmentOperation,
      status: 'interrupted' as const,
      log_tail: ['<script>untrusted log</script>'],
      error: { code: 'restart', message: '服务重启中断' },
      applied: false,
    };
    vi.spyOn(api, 'environmentOperation').mockResolvedValue(operation);
    render(<EnvironmentPage {...props()} operationId={operation.id} />);
    expect(await screen.findByText('restart：服务重启中断')).toBeVisible();
    expect(screen.getByText('<script>untrusted log</script>')).toBeVisible();
    expect(screen.getByText(/部分安装不代表可用/)).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
  });
  it('disables mutation when management is unsupported and preserves runtime diagnostics', async () => {
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...environmentCatalog,
      settings: { ...environmentCatalog.settings, enabled: false, reason: '未批准安装根目录' },
    });
    render(<EnvironmentPage {...props()} />);
    expect(await screen.findByText('未批准安装根目录')).toBeVisible();
    expect(screen.getByRole('button', { name: '检测全部组件' })).toBeDisabled();
    await userEvent.click(screen.getByText('运行诊断'));
    expect(screen.getByText('产品与存储')).toBeVisible();
  });
  it('rejects out-of-scope roots before writing and saves allowed roots with optimistic revision', async () => {
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue({
      ...environmentCatalog.settings,
      install_root: '/srv/wsl/envs/new',
      revision: 4,
    });
    render(<EnvironmentPage {...props()} />);
    const input = await screen.findByLabelText('环境安装目录');
    fireEvent.change(input, { target: { value: 'C:\\wrong' } });
    await userEvent.click(screen.getByRole('button', { name: '保存安装位置' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('目录');
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '/srv/wsl/envs/new' } });
    await userEvent.click(screen.getByRole('button', { name: '保存安装位置' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith('/srv/wsl/envs/new', 3));
  });
  it('requires owned-operation cancellation confirmation and refreshes actual status', async () => {
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...environmentCatalog,
      active_operation: environmentOperation,
    });
    const cancel = vi
      .spyOn(api, 'cancelEnvironmentOperation')
      .mockResolvedValue({ ...environmentOperation, status: 'cancelled' });
    render(<EnvironmentPage {...props()} operationId={environmentOperation.id} />);
    expect(await screen.findByRole('button', { name: '查看当前环境操作' })).toBeVisible();
    expect(screen.getByRole('button', { name: '检测全部组件' })).toBeDisabled();
    await userEvent.click(await screen.findByRole('button', { name: '取消此环境操作' }));
    expect(cancel).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认取消此环境操作' }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith(environmentOperation.id));
  });
});
