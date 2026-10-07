import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { ApiError } from '../src/api/errors';
import { decodeEnvironmentSettings } from '../src/api/environmentDecoders';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { useEnvironmentMutations } from '../src/features/environment/useEnvironmentMutations';
import { pendingEnvironmentKey, readPendingEnvironment } from '../src/model/environmentRecovery';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
import { health, json, session } from './fixtures';

const locations = {
  install_root: '/srv/wsl/envs/next',
  upload_root: '/srv/wsl/data/patentsar/uploads-next',
  result_root: '/srv/wsl/data/patentsar/results-next',
};
const fields = [
  ['install_root', '集成环境安装目录'],
  ['upload_root', '上传文件目录'],
  ['result_root', '生成结果目录'],
] as const;
function catalog() {
  const current = completeEnvironmentCatalog();
  return {
    ...current,
    settings: {
      ...current.settings,
      upload_root: '/srv/wsl/data/patentsar/uploads',
      result_root: '/srv/wsl/data/patentsar/results',
      allowed_data_root: '/srv/wsl/data',
    },
  };
}
const props = () => ({ operationId: null, onOperation: vi.fn(), product: health.product });
async function openStorage() {
  await userEvent.click(await screen.findByRole('button', { name: '存储位置' }));
  return screen.getByRole('dialog', { name: '存储位置' });
}
function editLocations(values = locations) {
  for (const [key, label] of fields)
    fireEvent.change(screen.getByLabelText(label), { target: { value: values[key] } });
}
beforeEach(() => {
  sessionStorage.removeItem(pendingEnvironmentKey);
  client.resetSession();
});
afterEach(() => sessionStorage.removeItem(pendingEnvironmentKey));

describe('storage locations API contract', () => {
  it('retains all three paths and both approved roots in settings responses', () => {
    expect(decodeEnvironmentSettings(catalog().settings)).toEqual(catalog().settings);
  });
  it.each([true, false])('retains the explicit editable capability %s', (editable) => {
    expect(decodeEnvironmentSettings({ ...catalog().settings, editable })).toMatchObject({
      editable,
    });
  });
  it.each([undefined, null, 1, 'true', {}])(
    'requires editable to be a supplied boolean, not an inferred permission: %j',
    (editable) => {
      const settings: Record<string, unknown> = { ...catalog().settings, editable };
      if (editable === undefined) delete settings.editable;
      expect(() => decodeEnvironmentSettings(settings)).toThrow('契约');
    },
  );
  it.each(['upload_root', 'result_root', 'allowed_data_root'])(
    'requires the additive string %s rather than inventing a default path',
    (field) => {
      const settings: Record<string, unknown> = { ...catalog().settings };
      delete settings[field];
      expect(() => decodeEnvironmentSettings(settings)).toThrow('契约');
      settings[field] = 42;
      expect(() => decodeEnvironmentSettings(settings)).toThrow('契约');
    },
  );
  it('uses one authenticated PUT with exactly all roots and the expected revision', async () => {
    const transport = vi.fn<typeof fetch>(async (input) =>
      String(input).endsWith('/session')
        ? json(session)
        : json({ ...catalog().settings, ...locations, revision: 4 }),
    );
    vi.stubGlobal('fetch', transport);
    await api.updateEnvironmentSettings(locations, 3);
    const writes = transport.mock.calls.filter(([, init]) => init?.method === 'PUT');
    expect(writes).toHaveLength(1);
    expect(writes[0]![0]).toBe('/api/v1/environments/settings');
    expect(JSON.parse(String(writes[0]![1]?.body))).toEqual({
      ...locations,
      expected_revision: 3,
    });
    expect(writes[0]![1]?.credentials).toBe('same-origin');
    expect((writes[0]![1]!.headers as Record<string, string>)['X-CSRF-Token']).toBe(
      session.csrf_token,
    );
  });
});

describe('minimal storage dialog and atomic revisioned save', () => {
  beforeEach(() => {
    vi.spyOn(api, 'environments').mockResolvedValue(catalog());
  });
  it('keeps paths off the primary page and component details collapsed in the single dialog', async () => {
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    render(<EnvironmentPage {...props()} />);
    const opener = await screen.findByRole('button', { name: '存储位置' });
    expect(screen.getAllByRole('button', { name: '存储位置' })).toHaveLength(1);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: '存储位置' });
    for (const [key, label] of fields)
      expect(within(dialog).getByLabelText(label)).toHaveValue(catalog().settings[key]);
    expect(within(dialog).getByLabelText('集成环境安装目录')).toHaveFocus();
    expect(dialog).toHaveTextContent('仅影响后续写入，不会移动已有文件');
    expect(dialog).toHaveTextContent('提取产物及 CSV/JSON 导出副本');
    expect(dialog).toHaveTextContent('下载位置仍由浏览器设置');
    expect(within(dialog).getByRole('button', { name: '保存' })).toBeDisabled();
    const details = within(dialog)
      .getByText('环境详情', { selector: 'summary' })
      .closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(within(dialog).getByRole('heading', { name: '组件库' })).not.toBeVisible();
    expect(save).not.toHaveBeenCalled();
    expect(install).not.toHaveBeenCalled();
  });
  it('cancels every draft without saving and restores focus and the persisted values on reopen', async () => {
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '存储位置' })).toHaveFocus();
    await openStorage();
    for (const [key, label] of fields)
      expect(screen.getByLabelText(label)).toHaveValue(catalog().settings[key]);
    expect(save).not.toHaveBeenCalled();
  });
  it('saves the three normalized paths atomically and rereads them after page refresh', async () => {
    let current = catalog();
    vi.spyOn(api, 'environments').mockImplementation(async () => current);
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockImplementation(async () => {
      current = { ...current, settings: { ...current.settings, ...locations, revision: 4 } };
      return current.settings;
    });
    const first = render(<EnvironmentPage {...props()} />);
    await openStorage();
    editLocations({ ...locations, upload_root: ` ${locations.upload_root}// ` });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(locations, 3));
    expect(save).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    first.unmount();
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    for (const [key, label] of fields)
      expect(screen.getByLabelText(label)).toHaveValue(locations[key]);
  });
  it('includes unchanged roots when editing only the result directory', async () => {
    const saved = { ...catalog().settings, result_root: locations.result_root, revision: 4 };
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue(saved);
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    fireEvent.change(screen.getByLabelText('生成结果目录'), {
      target: { value: locations.result_root },
    });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        {
          install_root: catalog().settings.install_root,
          upload_root: catalog().settings.upload_root,
          result_root: locations.result_root,
        },
        3,
      ),
    );
  });
  it('preserves unchanged current legacy data roots outside a new allowed prefix when editing only installation', async () => {
    const current = catalog();
    current.settings.allowed_data_root = '/srv/wsl/data/new-approved';
    vi.spyOn(api, 'environments').mockResolvedValue(current);
    const saved = { ...current.settings, install_root: locations.install_root, revision: 4 };
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue(saved);
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    fireEvent.change(screen.getByLabelText('集成环境安装目录'), {
      target: { value: locations.install_root },
    });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledExactlyOnceWith(
        {
          install_root: locations.install_root,
          upload_root: current.settings.upload_root,
          result_root: current.settings.result_root,
        },
        3,
      ),
    );
  });
  it.each(['upload_root', 'result_root'] as const)(
    'validates changed %s against the new prefix while preserving the other unchanged current root',
    async (key) => {
      const current = catalog();
      current.settings.allowed_data_root = '/srv/wsl/data/new-approved';
      vi.spyOn(api, 'environments').mockResolvedValue(current);
      const selected = {
        install_root: current.settings.install_root,
        upload_root: current.settings.upload_root,
        result_root: current.settings.result_root,
        [key]: `/srv/wsl/data/new-approved/${key}`,
      };
      const save = vi
        .spyOn(api, 'updateEnvironmentSettings')
        .mockResolvedValue({ ...current.settings, ...selected, revision: 4 });
      render(<EnvironmentPage {...props()} />);
      await openStorage();
      editLocations(selected);
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith(selected, 3));
    },
  );
  it.each(['upload_root', 'result_root'] as const)(
    'rejects changed noncurrent %s outside the approved prefix rather than granting a legacy-directory exemption',
    async (key) => {
      const current = catalog();
      current.settings.allowed_data_root = '/srv/wsl/data/new-approved';
      vi.spyOn(api, 'environments').mockResolvedValue(current);
      const save = vi.spyOn(api, 'updateEnvironmentSettings');
      render(<EnvironmentPage {...props()} />);
      await openStorage();
      const label = fields.find(([field]) => field === key)![1];
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: `${current.settings[key]}-different` },
      });
      await userEvent.click(screen.getByRole('button', { name: '保存' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(label);
      expect(save).not.toHaveBeenCalled();
    },
  );
  it('permits path repair with enabled=false and editable=true while installation and inspection remain disabled', async () => {
    const current = catalog();
    const broken = {
      ...current,
      settings: {
        ...current.settings,
        install_root: '/srv/wsl/previous-envs/unsafe-prefix',
        enabled: false,
        editable: true,
        reason: 'opaque_backend_reason',
      },
    };
    vi.spyOn(api, 'environments').mockResolvedValue(broken);
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue({
      ...broken.settings,
      install_root: locations.install_root,
      enabled: true,
      revision: 4,
    });
    const start = vi.spyOn(api, 'createEnvironmentOperation');
    render(<EnvironmentPage {...props()} />);
    const dialog = await openStorage();
    for (const [, label] of fields) expect(screen.getByLabelText(label)).toBeEnabled();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '检测全部组件' })).toBeDisabled();
    await userEvent.click(within(dialog).getByText('环境详情', { selector: 'summary' }));
    const componentActions = within(dialog).getAllByRole('button', {
      name: /^(安装|检测|修复|先检测) /,
    });
    expect(componentActions.length).toBeGreaterThan(0);
    for (const button of componentActions) expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText('集成环境安装目录'), {
      target: { value: locations.install_root },
    });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledExactlyOnceWith(
        {
          install_root: locations.install_root,
          upload_root: current.settings.upload_root,
          result_root: current.settings.result_root,
        },
        3,
      ),
    );
    expect(start).not.toHaveBeenCalled();
  });
  it('does not infer storage edit permission from enabled=true when editable=false', async () => {
    const current = catalog();
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...current,
      settings: { ...current.settings, enabled: true, editable: false },
    });
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    for (const [, label] of fields) expect(screen.getByLabelText(label)).toBeDisabled();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '一键部署全部环境' })).toBeEnabled();
    expect(save).not.toHaveBeenCalled();
  });
  it('shows save errors inside the dialog and retains every draft for correction', async () => {
    vi.spyOn(api, 'updateEnvironmentSettings').mockRejectedValue(
      new ApiError(422, 'invalid_storage_location', '上传文件目录不可用'),
    );
    render(<EnvironmentPage {...props()} />);
    const dialog = await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('上传文件目录不可用');
    for (const [key, label] of fields)
      expect(screen.getByLabelText(label)).toHaveValue(locations[key]);
    expect(screen.getByRole('button', { name: '取消' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled();
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBeNull();
  });
  it('can reconcile an uncertain save from within the modal without discarding its drafts', async () => {
    let current = catalog();
    vi.spyOn(api, 'environments').mockImplementation(async () => current);
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockImplementation(async () => {
      current = { ...current, settings: { ...current.settings, ...locations, revision: 4 } };
      throw new ApiError(0, 'network_error', '保存结果未知', true);
    });
    render(<EnvironmentPage {...props()} />);
    const dialog = await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await userEvent.click(await within(dialog).findByRole('button', { name: '检查状态' }));
    await waitFor(() => expect(sessionStorage.getItem(pendingEnvironmentKey)).toBeNull());
    for (const [key, label] of fields)
      expect(screen.getByLabelText(label)).toHaveValue(locations[key]);
    expect(
      within(dialog).queryByRole('button', { name: '使用最新版本并保留输入' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    expect(save).toHaveBeenCalledTimes(1);
  });
  it('adopts a refreshed server revision automatically when the form is pristine', async () => {
    const current = catalog();
    vi.spyOn(api, 'environments')
      .mockResolvedValueOnce(current)
      .mockResolvedValue({
        ...current,
        settings: { ...current.settings, ...locations, revision: 4 },
      });
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    await userEvent.click(screen.getByRole('button', { name: '刷新环境目录' }));
    await waitFor(() =>
      expect(screen.getByLabelText('上传文件目录')).toHaveValue(locations.upload_root),
    );
    expect(
      screen.queryByRole('button', { name: '使用最新版本并保留输入' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  });
  it('keeps recovery controls reachable if the catalog refresh fails while a storage dialog is open', async () => {
    vi.spyOn(api, 'environments')
      .mockResolvedValueOnce(catalog())
      .mockResolvedValueOnce(catalog())
      .mockRejectedValue(new ApiError(503, 'unavailable', '目录读取失败'));
    vi.spyOn(api, 'updateEnvironmentSettings').mockRejectedValue(
      new ApiError(0, 'network_error', '保存结果未知', true),
    );
    render(<EnvironmentPage {...props()} />);
    const dialog = await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await userEvent.click(await within(dialog).findByRole('button', { name: '检查状态' }));
    expect(await screen.findByText('目录读取失败')).toBeVisible();
    expect(screen.getByRole('button', { name: '检查状态' })).toBeVisible();
    expect(sessionStorage.getItem(pendingEnvironmentKey)).not.toBeNull();
  });
  it.each([
    ['install_root', '/srv/wsl/data/not-environments'],
    ['upload_root', '/srv/wsl/envs/not-data'],
    ['result_root', '/srv/wsl/data-other/results'],
    ['upload_root', 'C:\\uploads'],
    ['result_root', '\\\\host\\results'],
    ['upload_root', '/srv/wsl/data/../outside'],
    ['result_root', '//srv/wsl/data/results'],
  ] as const)('rejects invalid %s without sending any part of the save', async (key, value) => {
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    editLocations({ ...locations, [key]: value });
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('目录');
    expect(save).not.toHaveBeenCalled();
  });
  it('retains all drafts on a revision conflict and requires explicit use of the latest revision', async () => {
    let current = catalog();
    vi.spyOn(api, 'environments').mockImplementation(async () => current);
    const save = vi
      .spyOn(api, 'updateEnvironmentSettings')
      .mockImplementationOnce(async () => {
        current = {
          ...current,
          settings: { ...current.settings, result_root: '/srv/wsl/data/server', revision: 4 },
        };
        throw new ApiError(409, 'environment_revision_conflict', '配置已更新');
      })
      .mockResolvedValue({ ...catalog().settings, ...locations, revision: 5 });
    render(<EnvironmentPage {...props()} />);
    await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    const reconcile = await screen.findByRole('button', { name: '使用最新版本并保留输入' });
    for (const [key, label] of fields)
      expect(screen.getByLabelText(label)).toHaveValue(locations[key]);
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
    await userEvent.click(reconcile);
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith(locations, 4));
    expect(save).toHaveBeenCalledTimes(2);
  });
  it('disables edits, saves and dismissal while the atomic request is in flight', async () => {
    let resolve!: (settings: ReturnType<typeof catalog>['settings']) => void;
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    render(<EnvironmentPage {...props()} />);
    const dialog = await openStorage();
    editLocations();
    await userEvent.click(screen.getByRole('button', { name: '保存' }));
    for (const [, label] of fields) expect(screen.getByLabelText(label)).toBeDisabled();
    expect(screen.getByRole('button', { name: '取消' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '关闭对话框' })).toBeDisabled();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(dialog).toBeVisible();
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => resolve({ ...catalog().settings, ...locations, revision: 4 }));
  });
  it.each(['active operation', 'unsupported platform'])(
    'allows read-only location viewing but no writes during %s',
    async (state) => {
      const current = catalog();
      vi.spyOn(api, 'environments').mockResolvedValue(
        state === 'active operation'
          ? {
              ...current,
              active_operation: environmentOperation,
              settings: { ...current.settings, editable: true },
            }
          : {
              ...current,
              settings: {
                ...current.settings,
                enabled: false,
                editable: false,
                reason: 'opaque_backend_reason',
              },
            },
      );
      vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
      const save = vi.spyOn(api, 'updateEnvironmentSettings');
      render(<EnvironmentPage {...props()} />);
      await openStorage();
      for (const [, label] of fields) expect(screen.getByLabelText(label)).toBeDisabled();
      expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
      expect(screen.getByRole('button', { name: '取消' })).toBeEnabled();
      expect(save).not.toHaveBeenCalled();
    },
  );
});

describe('atomic storage write recovery', () => {
  it.each([
    { upload_root: locations.upload_root },
    { result_root: locations.result_root },
    { upload_root: 42, result_root: locations.result_root },
    { upload_root: locations.upload_root, result_root: '/srv/wsl/data/unsafe\nvalue' },
    { upload_root: locations.upload_root, result_root: 'x'.repeat(513) },
  ])(
    'rejects partial or malformed new recovery records instead of replaying an install-only save: %j',
    (fileRoots) => {
      sessionStorage.setItem(
        pendingEnvironmentKey,
        JSON.stringify({
          kind: 'settings',
          install_root: locations.install_root,
          expected_revision: 3,
          ...fileRoots,
        }),
      );
      expect(readPendingEnvironment().pending).toBeNull();
      expect(readPendingEnvironment().error).toBeInstanceOf(Error);
    },
  );
  it('replays a valid legacy install-only recovery record without inventing data paths', async () => {
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({
        kind: 'settings',
        install_root: locations.install_root,
        expected_revision: 3,
      }),
    );
    vi.spyOn(api, 'environments').mockResolvedValue(catalog());
    const save = vi.spyOn(api, 'updateEnvironmentSettings').mockResolvedValue({
      ...catalog().settings,
      install_root: locations.install_root,
      revision: 4,
    });
    const state = renderHook(() => useEnvironmentMutations(vi.fn(), vi.fn()));
    await act(() => state.result.current.check());
    await act(() => state.result.current.retry());
    expect(save).toHaveBeenCalledExactlyOnceWith(locations.install_root, 3);
  });
  it('does not offer a settings replay while another environment operation is active', async () => {
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({ kind: 'settings', ...locations, expected_revision: 3 }),
    );
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...catalog(),
      active_operation: environmentOperation,
    });
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    const state = renderHook(() => useEnvironmentMutations(vi.fn(), vi.fn()));
    await act(() => state.result.current.check());
    expect(state.result.current.checked).toBe(false);
    await act(() => state.result.current.retry());
    expect(save).not.toHaveBeenCalled();
  });
  it('preserves all roots across an uncertain response and remount, then checks every root before retry', async () => {
    const save = vi
      .spyOn(api, 'updateEnvironmentSettings')
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '保存结果未知', true))
      .mockResolvedValue({ ...catalog().settings, ...locations, revision: 4 });
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...catalog(),
      settings: { ...catalog().settings, install_root: locations.install_root, revision: 4 },
    });
    const first = renderHook(() => useEnvironmentMutations(vi.fn(), vi.fn()));
    await act(() => first.result.current.save(locations, 3));
    expect(JSON.parse(sessionStorage.getItem(pendingEnvironmentKey)!)).toEqual({
      kind: 'settings',
      ...locations,
      expected_revision: 3,
    });
    first.unmount();
    const second = renderHook(() => useEnvironmentMutations(vi.fn(), vi.fn()));
    expect(save).toHaveBeenCalledTimes(1);
    await act(() => second.result.current.check());
    expect(second.result.current.pending).not.toBeNull();
    await act(() => second.result.current.retry());
    expect(save).toHaveBeenLastCalledWith(locations, 3);
  });
  it('clears uncertainty only when all three persisted roots match the server', async () => {
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({ kind: 'settings', ...locations, expected_revision: 3 }),
    );
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...catalog(),
      settings: { ...catalog().settings, ...locations, revision: 4 },
    });
    const save = vi.spyOn(api, 'updateEnvironmentSettings');
    const state = renderHook(() => useEnvironmentMutations(vi.fn(), vi.fn()));
    await act(() => state.result.current.check());
    expect(state.result.current.pending).toBeNull();
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBeNull();
    expect(save).not.toHaveBeenCalled();
  });
});
