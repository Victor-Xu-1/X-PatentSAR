import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import { matchesEnvironmentRequest } from '../../api/environmentDecoders';
import type {
  EnvironmentComponentId,
  EnvironmentOperation,
  EnvironmentSettings,
} from '../../api/environmentTypes';
import { activeEnvironmentOperation } from '../../model/environment';
import {
  clearPendingEnvironment,
  persistPendingEnvironment,
  readPendingEnvironment,
} from '../../model/environmentRecovery';
import type { PendingEnvironment } from '../../model/environmentRecovery';

export function useEnvironmentMutations(onOperation: (id: string) => void, onRefresh: () => void) {
  const [initial] = useState(readPendingEnvironment);
  const [pending, setPending] = useState<PendingEnvironment | null>(initial.pending);
  const [error, setError] = useState<Error | null>(initial.error);
  const [storageError, setStorageError] = useState(initial.error !== null);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  const lock = useRef(false),
    mounted = useRef(true);
  const recoveryController = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      recoveryController.current?.abort();
    };
  }, []);
  function clear() {
    try {
      clearPendingEnvironment();
      setPending(null);
      setChecked(false);
      setStorageError(false);
      return true;
    } catch {
      setStorageError(true);
      setError(
        new Error(
          '服务器结果已读取，但无法清除本功能的恢复记录。请恢复会话存储权限并再次核对；未重放请求。',
        ),
      );
      return false;
    }
  }
  async function dispatch(
    intent: PendingEnvironment,
  ): Promise<EnvironmentSettings | EnvironmentOperation | null> {
    if (lock.current) return null;
    lock.current = true;
    setBusy(true);
    setError(null);
    setChecked(false);
    let sent = false;
    try {
      persistPendingEnvironment(intent);
      setPending(intent);
      sent = true;
      const result =
        intent.kind === 'operation'
          ? await api.createEnvironmentOperation(intent.request)
          : intent.kind === 'settings'
            ? await api.updateEnvironmentSettings(intent.install_root, intent.expected_revision)
            : await api.cancelEnvironmentOperation(intent.operation_id);
      if (mounted.current) {
        clear();
        onRefresh();
        if ('id' in result) onOperation(result.id);
      }
      return result;
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof Error ? e : new Error('环境操作失败。'));
        if (!sent) setStorageError(true);
        else if (e instanceof ApiError && !e.uncertain && e.status >= 400 && e.status < 500)
          clear();
      }
      return null;
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function start(
    action: 'inspect' | 'install',
    component_ids: EnvironmentComponentId[],
    expected_revision: number,
  ) {
    if (pending || storageError || lock.current) return null;
    try {
      return await dispatch({
        kind: 'operation',
        request: { action, component_ids, expected_revision, request_id: crypto.randomUUID() },
      });
    } catch {
      setError(
        new Error('浏览器无法创建安全请求 ID，未发送环境操作。请在受信任的本地浏览器打开页面。'),
      );
      return null;
    }
  }
  async function save(install_root: string, expected_revision: number) {
    if (pending || storageError || lock.current) return null;
    const result = await dispatch({ kind: 'settings', install_root, expected_revision });
    return result && 'revision' in result ? result : null;
  }
  async function cancel(operation_id: string) {
    if (pending || storageError || lock.current) return null;
    return dispatch({ kind: 'cancel', operation_id });
  }
  async function check() {
    if ((!pending && !storageError) || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setChecked(false);
    const controller = new AbortController();
    recoveryController.current = controller;
    try {
      const catalog = await api.environments(controller.signal);
      if (!mounted.current) return;
      if (!pending) {
        setChecked(true);
        onRefresh();
        return;
      }
      if (pending.kind === 'operation') {
        const found = [catalog.active_operation, ...catalog.operations].find(
          (operation) => operation?.request_id === pending.request.request_id,
        );
        if (found) {
          if (!matchesEnvironmentRequest(found, pending.request))
            throw new Error(
              '服务器请求 ID 对应的操作参数不一致。保留恢复记录，不重放或认领另一项操作。',
            );
          clear();
          onOperation(found.id);
          onRefresh();
          return;
        }
      } else if (pending.kind === 'settings') {
        if (
          catalog.settings.install_root === pending.install_root &&
          catalog.settings.revision >= pending.expected_revision
        ) {
          clear();
          onRefresh();
          return;
        }
      } else {
        const operation = await api.environmentOperation(pending.operation_id, controller.signal);
        if (!mounted.current) return;
        if (!activeEnvironmentOperation(operation)) {
          clear();
          onOperation(operation.id);
          onRefresh();
          return;
        }
      }
      if (pending.kind !== 'operation' || !activeEnvironmentOperation(catalog.active_operation))
        setChecked(true);
      else
        setError(new Error('服务器有另一项环境操作正在运行。请等待并再次核对，不重放安装请求。'));
      onRefresh();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e : new Error('无法核对服务器状态。'));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function retry() {
    if (pending && checked && !lock.current) await dispatch(pending);
  }
  function discardCorrupt() {
    if (!checked || pending) return;
    try {
      clearPendingEnvironment();
      setStorageError(false);
      setChecked(false);
      setError(null);
      onRefresh();
    } catch {
      setError(new Error('无法清除本功能的恢复记录。请恢复会话存储权限；未发送请求。'));
    }
  }
  return {
    pending,
    error,
    busy,
    checked,
    storageError,
    start,
    save,
    cancel,
    check,
    retry,
    discardCorrupt,
  };
}
