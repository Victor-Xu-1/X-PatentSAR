import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { useEnvironmentMutations } from '../src/features/environment/useEnvironmentMutations';
import { parseRoute, routeHash } from '../src/model/route';
import { pendingEnvironmentKey, readPendingEnvironment } from '../src/model/environmentRecovery';
import { environmentCatalog, environmentOperation } from './environment-fixtures';

beforeEach(() => {
  sessionStorage.removeItem(pendingEnvironmentKey);
  vi.spyOn(api, 'environments').mockResolvedValue(environmentCatalog);
});
afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.removeItem(pendingEnvironmentKey);
});
const pending = {
  kind: 'operation' as const,
  request: {
    action: 'install' as const,
    component_ids: ['base' as const],
    request_id: 'stable_request_recovery_123',
    expected_revision: 3,
  },
};
function hook() {
  const selected = vi.fn(),
    refresh = vi.fn();
  return { ...renderHook(() => useEnvironmentMutations(selected, refresh)), selected, refresh };
}
describe('durable environment mutation recovery', () => {
  it('retains selected operation in only the environment URL across refresh', () => {
    const route = parseRoute('#/settings?operation=owned-operation-1');
    expect(route.operationId).toBe('owned-operation-1');
    expect(routeHash(route)).toBe('#/settings?operation=owned-operation-1');
    expect(parseRoute('#/projects?operation=owned-operation-1').operationId).toBeUndefined();
    expect(parseRoute('#/settings?operation=../../unowned').operationId).toBeUndefined();
  });
  it('treats own storage as untrusted and never touches unrelated recovery data', () => {
    sessionStorage.setItem('other.feature', 'keep');
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({
        kind: 'operation',
        request: { ...pending.request, component_ids: ['cuda'] },
      }),
    );
    expect(readPendingEnvironment().error).toBeInstanceOf(Error);
    expect(sessionStorage.getItem('other.feature')).toBe('keep');
    sessionStorage.removeItem('other.feature');
  });
  it('sends no write if the request cannot first be persisted', async () => {
    const start = vi.spyOn(api, 'createEnvironmentOperation');
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage denied');
    });
    const state = hook();
    await act(() => state.result.current.start('inspect', ['base'], 3));
    expect(start).not.toHaveBeenCalled();
    expect(state.result.current.error?.message).toContain('未发送请求');
    expect(state.result.current.storageError).toBe(true);
    write.mockRestore();
  });
  it('keeps an unknown write across unmount and does not replay on remount', async () => {
    let resolve!: (value: typeof environmentOperation) => void;
    const start = vi.spyOn(api, 'createEnvironmentOperation').mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const state = hook();
    let request!: Promise<unknown>;
    act(() => {
      request = state.result.current.start('install', ['base'], 3);
    });
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    state.unmount();
    await act(async () => {
      resolve(environmentOperation);
      await request;
    });
    const reloaded = hook();
    expect(reloaded.result.current.pending?.kind).toBe('operation');
    expect(start).toHaveBeenCalledTimes(1);
  });
  it('does not offer retry after a failed read or while another server operation is active', async () => {
    sessionStorage.setItem(pendingEnvironmentKey, JSON.stringify(pending));
    const catalog = vi
      .spyOn(api, 'environments')
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '读取失败'));
    const state = hook();
    await act(() => state.result.current.check());
    expect(state.result.current.checked).toBe(false);
    catalog.mockResolvedValue({ ...environmentCatalog, active_operation: environmentOperation });
    await act(() => state.result.current.check());
    expect(state.result.current.checked).toBe(false);
    expect(state.result.current.error?.message).toContain('另一项环境操作');
  });
  it('does not lose the idempotency record on ambiguous HTTP 500', async () => {
    vi.spyOn(api, 'createEnvironmentOperation').mockRejectedValue(
      new ApiError(500, 'unexpected', '服务器内部错误'),
    );
    const state = hook();
    await act(() => state.result.current.start('install', ['base'], 3));
    expect(state.result.current.pending).not.toBeNull();
    expect(sessionStorage.getItem(pendingEnvironmentKey)).not.toBeNull();
    expect(state.result.current.checked).toBe(false);
  });
  it('does not claim a different operation with a matching request ID but conflicting parameters', async () => {
    sessionStorage.setItem(pendingEnvironmentKey, JSON.stringify(pending));
    vi.spyOn(api, 'environments').mockResolvedValue({
      ...environmentCatalog,
      operations: [
        { ...environmentOperation, request_id: pending.request.request_id, action: 'inspect' },
      ],
    });
    const state = hook();
    await act(() => state.result.current.check());
    expect(state.result.current.pending).not.toBeNull();
    expect(state.result.current.checked).toBe(false);
    expect(state.selected).not.toHaveBeenCalled();
    expect(state.result.current.error?.message).toContain('参数不一致');
  });
  it('resolves unknown settings through actual current root and unknown cancel through terminal state', async () => {
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({
        kind: 'settings',
        install_root: environmentCatalog.settings.install_root,
        expected_revision: 3,
      }),
    );
    const settings = hook();
    await act(() => settings.result.current.check());
    expect(settings.result.current.pending).toBeNull();
    settings.unmount();
    sessionStorage.setItem(
      pendingEnvironmentKey,
      JSON.stringify({ kind: 'cancel', operation_id: environmentOperation.id }),
    );
    vi.spyOn(api, 'environmentOperation').mockResolvedValue({
      ...environmentOperation,
      status: 'cancelled',
    });
    const cancel = hook();
    await act(() => cancel.result.current.check());
    expect(cancel.result.current.pending).toBeNull();
    expect(cancel.selected).toHaveBeenCalledWith(environmentOperation.id);
  });
  it('requires a successful server read before corrupt-record cleanup and preserves other keys', async () => {
    sessionStorage.setItem(pendingEnvironmentKey, 'invalid JSON');
    sessionStorage.setItem('other.feature', 'keep');
    const state = hook();
    act(() => state.result.current.discardCorrupt());
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBe('invalid JSON');
    await act(() => state.result.current.check());
    act(() => state.result.current.discardCorrupt());
    expect(state.result.current.storageError).toBe(false);
    expect(sessionStorage.getItem(pendingEnvironmentKey)).toBeNull();
    expect(sessionStorage.getItem('other.feature')).toBe('keep');
    sessionStorage.removeItem('other.feature');
  });
  it('preserves accepted results as pending when recovery storage cannot be cleared', async () => {
    vi.spyOn(api, 'createEnvironmentOperation').mockResolvedValue(environmentOperation);
    const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('Storage denied');
    });
    const state = hook();
    await act(() => state.result.current.start('install', ['base'], 3));
    expect(state.result.current.pending?.kind).toBe('operation');
    expect(state.result.current.storageError).toBe(true);
    expect(state.selected).toHaveBeenCalledWith(environmentOperation.id);
    remove.mockRestore();
  });
});
