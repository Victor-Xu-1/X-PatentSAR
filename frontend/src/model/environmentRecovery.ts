import { UiError } from '../i18n';
import { decodeEnvironmentOperationId, decodeEnvironmentRequest } from '../api/environmentDecoders';
import { count, object, string } from '../api/validation';
import type {
  EnvironmentOperationRequest,
  EnvironmentSettingsUpdate,
} from '../api/environmentTypes';
import { hasEnvironmentControlCharacters } from './environment';
export const pendingEnvironmentKey = 'patentsar.environment.pending.v1';
export type PendingEnvironment =
  | { kind: 'operation'; request: EnvironmentOperationRequest }
  | ({ kind: 'settings' } & EnvironmentSettingsUpdate)
  | { kind: 'cancel'; operation_id: string };
function boundedText(value: unknown, path?: string): string {
  const result = string(value, path);
  if (!result || result.length > 512 || hasEnvironmentControlCharacters(result))
    throw new UiError('恢复记录无效');
  return result;
}
function settingsIntent(value: unknown): Extract<PendingEnvironment, { kind: 'settings' }> {
  const settings = object({ install_root: boundedText, expected_revision: count })(value);
  const input = value as Record<string, unknown>;
  // Older install-only records must not acquire guessed file locations on replay.
  if (!('upload_root' in input) && !('result_root' in input))
    return { kind: 'settings', ...settings };
  return {
    kind: 'settings',
    ...settings,
    ...object({ upload_root: boundedText, result_root: boundedText })(value),
  };
}
export function readPendingEnvironment(): {
  pending: PendingEnvironment | null;
  error: Error | null;
} {
  try {
    const raw = window.sessionStorage.getItem(pendingEnvironmentKey);
    if (!raw) return { pending: null, error: null };
    if (raw.length > 16_384) throw new UiError('恢复记录过大');
    const value = JSON.parse(raw) as unknown;
    const kind = object({ kind: string })(value).kind;
    const pending: PendingEnvironment =
      kind === 'operation'
        ? { kind, request: object({ request: decodeEnvironmentRequest })(value).request }
        : kind === 'settings'
          ? settingsIntent(value)
          : kind === 'cancel'
            ? {
                kind,
                operation_id: object({ operation_id: decodeEnvironmentOperationId })(value)
                  .operation_id,
              }
            : (() => {
                throw new UiError('未知恢复记录');
              })();
    return { pending, error: null };
  } catch {
    return {
      pending: null,
      error: new UiError(
        '恢复信息无法读取，未执行任何操作。请先检查配置状态，再确认清除损坏记录。',
      ),
    };
  }
}
export function persistPendingEnvironment(pending: PendingEnvironment): void {
  try {
    window.sessionStorage.setItem(pendingEnvironmentKey, JSON.stringify(pending));
  } catch {
    throw new UiError('无法保存环境操作的恢复信息，未发送请求。请允许本地站点的会话存储后再试。');
  }
}
export function clearPendingEnvironment(): void {
  window.sessionStorage.removeItem(pendingEnvironmentKey);
}
