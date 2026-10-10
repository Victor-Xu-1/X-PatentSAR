import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { environmentOperation, prerequisiteCatalog } from './environment-fixtures';
import { health } from './fixtures';
import { recoverySettings } from './llm-recovery-fixtures';

beforeEach(() => {
  // This suite owns environment consent/retry, not the independent API module's
  // settings transport. Its load error must not make alert selection timing-dependent.
  vi.spyOn(llmApi, 'settings').mockResolvedValue({
    ...recoverySettings,
    mode: 'off',
    status: 'disabled',
    data_consent: false,
    key_configured: false,
  });
  sessionStorage.removeItem(pendingEnvironmentKey);
  vi.spyOn(api, 'environments').mockResolvedValue(prerequisiteCatalog());
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
it.each([
  { label: '安装 基础运行环境', ids: ['installer', 'base'] },
  { label: '安装 ADMET 模型', ids: ['installer', 'admet', 'admet-models'] },
])(
  'requires consent to the full server prerequisite closure for $label',
  async ({ label, ids }) => {
    const catalog = prerequisiteCatalog();
    vi.spyOn(api, 'environments').mockResolvedValue(catalog);
    const start = vi
      .spyOn(api, 'createEnvironmentOperation')
      .mockImplementation(async (request) => ({
        ...environmentOperation,
        request_id: request.request_id,
        component_ids: request.component_ids,
      }));
    render(<EnvironmentPage {...props()} />);
    await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
    await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
    await userEvent.click(await screen.findByRole('button', { name: label }));
    const dialog = screen.getByRole('dialog');
    const entries = dialog.querySelectorAll('.installation-plan li');
    expect(Array.from(entries).map((item) => item.getAttribute('data-install-component'))).toEqual(
      ids,
    );
    for (const id of ids) {
      const component = catalog.components.find((item) => item.id === id)!;
      expect(dialog).toHaveTextContent(component.name);
      expect(dialog).toHaveTextContent(component.version);
      expect(dialog).toHaveTextContent(component.license);
    }
    if (ids.includes('admet')) {
      expect(dialog).toHaveTextContent('1.3 GiB');
      expect(dialog).toHaveTextContent('13.4 MiB');
    }
    expect(dialog).toHaveTextContent('前置依赖');
    expect(within(dialog).getByRole('button', { name: '确认下载并安装' })).toBeDisabled();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('checkbox'));
    await userEvent.click(within(dialog).getByRole('button', { name: '确认下载并安装' }));
    await waitFor(() =>
      expect(start).toHaveBeenCalledWith(
        expect.objectContaining({ action: 'install', component_ids: ids, expected_revision: 3 }),
      ),
    );
  },
);
it('requires the prerequisite license, not only the selected model license', async () => {
  const catalog = prerequisiteCatalog();
  catalog.components = catalog.components.map((item) =>
    item.id === 'admet' ? { ...item, license: '' } : item,
  );
  vi.spyOn(api, 'environments').mockResolvedValue(catalog);
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 ADMET 模型' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('不能确认安装');
  expect(screen.getByRole('checkbox')).toBeDisabled();
});
it('shows malformed dependency errors without offering confirmation or sending a request', async () => {
  const catalog = prerequisiteCatalog();
  catalog.components = catalog.components.map((item) =>
    item.id === 'base' ? { ...item, dependencies: ['base'] } : item,
  );
  vi.spyOn(api, 'environments').mockResolvedValue(catalog);
  const start = vi.spyOn(api, 'createEnvironmentOperation');
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 基础运行环境' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('依赖');
  expect(start).not.toHaveBeenCalled();
});
it('persists and retries exactly the already-consented closure after an uncertain write', async () => {
  const start = vi
    .spyOn(api, 'createEnvironmentOperation')
    .mockRejectedValueOnce(new ApiError(0, 'network_error', '结果未知', true))
    .mockImplementation(async (request) => ({
      ...environmentOperation,
      request_id: request.request_id,
      component_ids: request.component_ids,
    }));
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '安装 ADMET 模型' }));
  await userEvent.click(screen.getByRole('checkbox'));
  await userEvent.click(screen.getByRole('button', { name: '确认下载并安装' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('结果未知');
  const submitted = start.mock.calls[0]![0];
  expect(submitted.component_ids).toEqual(['installer', 'admet', 'admet-models']);
  expect(JSON.parse(sessionStorage.getItem(pendingEnvironmentKey)!)).toMatchObject({
    kind: 'operation',
    request: submitted,
  });
  await userEvent.click(screen.getByRole('button', { name: '检查状态' }));
  await userEvent.click(await screen.findByRole('button', { name: '重试原操作' }));
  expect(start).toHaveBeenCalledTimes(2);
  expect(start).toHaveBeenLastCalledWith(submitted);
});
it('keeps inspection to the requested component without implicitly inspecting all prerequisites', async () => {
  const start = vi.spyOn(api, 'createEnvironmentOperation').mockImplementation(async (request) => ({
    ...environmentOperation,
    action: request.action,
    request_id: request.request_id,
    component_ids: request.component_ids,
    completed_components: [],
  }));
  render(<EnvironmentPage {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: '环境详情' }));
  await userEvent.click(screen.getByText('组件详情', { selector: 'summary' }));
  await userEvent.click(await screen.findByRole('button', { name: '检测 ADMET 模型' }));
  expect(start).toHaveBeenCalledWith(
    expect.objectContaining({ action: 'inspect', component_ids: ['admet-models'] }),
  );
  expect(screen.getByRole('dialog', { name: '环境详情' })).toBeVisible();
  expect(screen.queryByRole('dialog', { name: '确认环境安装' })).not.toBeInTheDocument();
});
