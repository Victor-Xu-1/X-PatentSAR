import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
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
it('shows loading, empty inventory and failed reads without substituting catalog data', async () => {
  let resolve!: (catalog: typeof environmentCatalog) => void;
  vi.spyOn(api, 'environments').mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(<EnvironmentPage {...props()} />);
  expect(await screen.findByText('正在读取真实环境组件目录…')).toBeVisible();
  await act(async () => resolve({ ...environmentCatalog, components: [], presets: [] }));
  expect(
    await within(await screen.findByLabelText('完整运行环境')).findByText(/服务端尚未提供组件目录/),
  ).toBeVisible();
  expect(screen.getByRole('button', { name: '检测全部组件' })).toBeDisabled();
  vi.spyOn(api, 'environments').mockRejectedValue(
    new ApiError(503, 'unavailable', '目录服务尚未就绪'),
  );
  await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('目录服务尚未就绪');
  expect(screen.queryByText('locked-base')).not.toBeInTheDocument();
});
it('reports unavailable environment endpoints without claiming server history is empty', async () => {
  vi.spyOn(api, 'environments').mockRejectedValue(
    new ApiError(404, 'endpoint_missing', 'API endpoint does not exist.'),
  );
  render(<EnvironmentPage {...props()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('当前后端未提供环境管理');
  expect(screen.queryByText(/操作历史/)).not.toBeInTheDocument();
  expect(screen.queryByText('运行诊断')).not.toBeInTheDocument();
});
it('preserves dirty location across revision changes and requires explicit conflict reconciliation', async () => {
  const changed = {
    ...environmentCatalog,
    settings: {
      ...environmentCatalog.settings,
      install_root: '/srv/wsl/envs/server-choice',
      revision: 4,
    },
  };
  vi.spyOn(api, 'environments')
    .mockResolvedValueOnce(environmentCatalog)
    .mockResolvedValue(changed);
  const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue({
    ...changed.settings,
    install_root: '/srv/wsl/envs/operator-choice',
    revision: 5,
  });
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('修改位置'));
  const input = await screen.findByLabelText('环境安装目录');
  fireEvent.change(input, { target: { value: '/srv/wsl/envs/operator-choice' } });
  await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
  const accept = await screen.findByRole('button', { name: '使用最新版本并保留输入' });
  expect(input).toHaveValue('/srv/wsl/envs/operator-choice');
  expect(screen.getByRole('button', { name: '保存安装位置' })).toBeDisabled();
  await userEvent.click(accept);
  await userEvent.click(screen.getByRole('button', { name: '保存安装位置' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('/srv/wsl/envs/operator-choice', 4));
});
it('supports component-only confirmation, focuses consent and locks dismissal during submission', async () => {
  let resolve!: (operation: typeof environmentOperation) => void;
  const start = vi.spyOn(api, 'createEnvironmentOperation').mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  const opener = await screen.findByRole('button', { name: '安装 基础运行环境' });
  await userEvent.click(opener);
  const dialog = screen.getByRole('dialog');
  const consent = within(dialog).getByRole('checkbox');
  expect(consent).toHaveFocus();
  await userEvent.click(consent);
  const confirm = within(dialog).getByRole('button', { name: '确认下载并安装' });
  await userEvent.click(confirm);
  expect(start).toHaveBeenCalledWith(
    expect.objectContaining({ component_ids: ['installer', 'base'] }),
  );
  expect(within(dialog).getByRole('button', { name: '取消' })).toBeDisabled();
  fireEvent(dialog, new Event('cancel', { cancelable: true }));
  expect(dialog).toBeVisible();
  await act(async () =>
    resolve({
      ...environmentOperation,
      component_ids: ['installer', 'base'],
      completed_components: [],
    }),
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  view.unmount();
});
it('cannot confirm unlicensed components and does not let history reads become write authority', async () => {
  vi.spyOn(api, 'environments').mockResolvedValue({
    ...environmentCatalog,
    components: environmentCatalog.components.map((item) => ({
      ...item,
      license: item.id === 'base' ? '' : item.license,
    })),
  });
  const start = vi.spyOn(api, 'createEnvironmentOperation');
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 基础运行环境' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('不能确认安装');
  expect(screen.getByRole('checkbox')).toBeDisabled();
  expect(screen.getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
  expect(start).not.toHaveBeenCalled();
});
it('marks last-known progress stale after polling errors and disables cancellation until a real read', async () => {
  const read = vi
    .spyOn(api, 'environmentOperation')
    .mockResolvedValueOnce(environmentOperation)
    .mockRejectedValue(new ApiError(503, 'unavailable', '操作读取失败'));
  render(<EnvironmentPage {...props()} operationId={environmentOperation.id} />);
  expect(await screen.findByLabelText('环境配置进度')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
  expect(await screen.findByText(/当前显示上次已知状态/)).toBeVisible();
  expect(screen.getByRole('button', { name: '取消此环境操作' })).toBeDisabled();
  expect(read).toHaveBeenCalledTimes(2);
});
