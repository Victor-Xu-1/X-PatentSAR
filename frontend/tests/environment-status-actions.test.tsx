import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { EnvironmentCatalog, EnvironmentComponent } from '../src/api/environmentTypes';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { environmentCatalog, environmentOperation } from './environment-fixtures';
import { readyEnvironmentCatalog } from './environment-setup-fixtures';
import { health } from './fixtures';

beforeEach(() => {
  sessionStorage.removeItem(pendingEnvironmentKey);
  vi.spyOn(api, 'environments').mockResolvedValue(environmentCatalog);
  vi.spyOn(api, 'runtime').mockResolvedValue({
    product: health.product,
    storage: { state_root: '/srv/wsl/state', platform: 'linux' },
    interpreters: [],
    capabilities: health.capabilities,
  });
  vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
});
afterEach(() => sessionStorage.removeItem(pendingEnvironmentKey));
const props = () => ({ operationId: null, onOperation: vi.fn(), product: health.product });
function catalogWithBase(overrides: Partial<EnvironmentComponent>): EnvironmentCatalog {
  return {
    ...environmentCatalog,
    components: environmentCatalog.components.map((component) => {
      if (component.id === 'installer') return { ...component, installable: false };
      return component.id === 'base' ? { ...component, ...overrides } : component;
    }),
  };
}
function startOperation() {
  return vi.spyOn(api, 'createEnvironmentOperation').mockImplementation(async (request) => ({
    ...environmentOperation,
    action: request.action,
    request_id: request.request_id,
    component_ids: request.component_ids,
    completed_components: [],
  }));
}
const failedBase = {
  presence: 'present' as const,
  verification: 'current' as const,
  status: 'incompatible' as const,
  location: '/srv/wsl/envs/existing-base/bin/python',
  detected_version: 'actual-incompatible-version',
  checked_at: '2026-10-04T12:00:00Z',
  problem: '锁定版本不匹配',
};

it.each([
  { status: 'incompatible' as const, badge: '版本不兼容' },
  { status: 'missing' as const, badge: '缺少依赖' },
])(
  'repairs a currently $status existing component only after full closure/license consent',
  async ({ status, badge }) => {
    vi.spyOn(api, 'environments').mockResolvedValue(catalogWithBase({ ...failedBase, status }));
    const start = startOperation();
    render(<EnvironmentPage {...props()} />);
    await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
    await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
    await userEvent.click(await screen.findByRole('button', { name: '修复 基础运行环境' }));
    const dialog = screen.getByRole('dialog');
    expect(start).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent(badge);
    const entries = dialog.querySelectorAll('[data-install-component]');
    expect(
      Array.from(entries).map((entry) => entry.getAttribute('data-install-component')),
    ).toEqual(['installer', 'base']);
    expect(dialog.querySelector('[data-install-component="installer"]')).toHaveTextContent('复用');
    expect(dialog).toHaveTextContent('MIT');
    expect(dialog).toHaveTextContent('Apache-2.0 / BSD');
    expect(within(dialog).getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole('checkbox'));
    await userEvent.click(within(dialog).getByRole('button', { name: '确认下载并安装' }));
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'install',
          component_ids: ['installer', 'base'],
          expected_revision: 3,
        }),
      ),
    );
    expect(start).toHaveBeenCalledTimes(1);
  },
);
it('does not bypass a ready prerequisite license when repairing a failed component', async () => {
  const catalog = catalogWithBase(failedBase);
  catalog.components = catalog.components.map((component) =>
    component.id === 'installer' ? { ...component, license: '' } : component,
  );
  vi.spyOn(api, 'environments').mockResolvedValue(catalog);
  const start = startOperation();
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '修复 基础运行环境' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('不能确认安装');
  expect(screen.getByRole('checkbox')).toBeDisabled();
  expect(start).not.toHaveBeenCalled();
});
it('keeps a verified-ready noninstallable dependency in the consented missing-component plan', async () => {
  vi.spyOn(api, 'environments').mockResolvedValue(catalogWithBase({}));
  const start = startOperation();
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 基础运行环境' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog.querySelectorAll('[data-install-component]')).toHaveLength(2);
  expect(dialog.querySelector('[data-install-component="installer"]')).toHaveTextContent('复用');
  await userEvent.click(within(dialog).getByRole('checkbox'));
  await userEvent.click(within(dialog).getByRole('button', { name: '确认下载并安装' }));
  await waitFor(() =>
    expect(start).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'install',
        component_ids: ['installer', 'base'],
      }),
    ),
  );
});
it.each(['unchecked', 'stale'] as const)(
  'only starts explicit advanced inspection for a %s component',
  async (verification) => {
    vi.spyOn(api, 'environments').mockResolvedValue(
      catalogWithBase({
        ...failedBase,
        verification,
      }),
    );
    const start = startOperation();
    render(<EnvironmentPage {...props()} />);
    await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
    await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
    const opener = await screen.findByRole('button', { name: '检测 基础运行环境' });
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(opener);
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'inspect',
          component_ids: ['base'],
        }),
      ),
    );
    expect(screen.getByRole('dialog', { name: '环境详情' })).toBeVisible();
    expect(screen.queryByRole('dialog', { name: '确认环境安装' })).not.toBeInTheDocument();
    expect(start).toHaveBeenCalledTimes(1);
  },
);
it('only refreshes metadata for installed components, with no operation POST or heavy probe', async () => {
  const catalog = readyEnvironmentCatalog();
  const read = vi.spyOn(api, 'environments').mockResolvedValue(catalog);
  const start = startOperation();
  render(<EnvironmentPage {...props()} />);
  expect(await screen.findByRole('button', { name: '环境已就绪' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  expect(start).not.toHaveBeenCalled();
});
it('explicitly inspects every listed component from the all-component detection button', async () => {
  const start = startOperation();
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '检测全部组件' }));
  expect(start).toHaveBeenCalledWith(
    expect.objectContaining({
      action: 'inspect',
      component_ids: environmentCatalog.components.map((component) => component.id),
    }),
  );
});
it('cannot submit a now-ready install after a metadata refresh while consent is open', async () => {
  const ready = catalogWithBase({ ...failedBase, status: 'ready', problem: null });
  vi.spyOn(api, 'environments').mockResolvedValueOnce(environmentCatalog).mockResolvedValue(ready);
  const start = startOperation();
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 基础运行环境' }));
  const dialog = screen.getByRole('dialog');
  await userEvent.click(within(dialog).getByRole('checkbox'));
  // A normal catalog reload can finish while a previously opened confirmation remains.
  await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
  const confirmation = within(dialog).getByRole('button', { name: '确认下载并安装' });
  await waitFor(() => expect(confirmation).toBeDisabled());
  expect(confirmation).toBeDisabled();
  await userEvent.click(confirmation);
  expect(start).not.toHaveBeenCalled();
});
