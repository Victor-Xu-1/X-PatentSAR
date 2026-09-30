import { decodeEnvironmentOperationId, decodeEnvironmentRequest } from '../api/environmentDecoders';
import { count, object, string } from '../api/validation';
import type { EnvironmentOperationRequest } from '../api/environmentTypes';
import { hasEnvironmentControlCharacters } from './environment';
export const pendingEnvironmentKey = 'patentsar.environment.pending.v1';
export type PendingEnvironment =
  | { kind: 'operation'; request: EnvironmentOperationRequest }
  | { kind: 'settings'; install_root: string; expected_revision: number }
  | { kind: 'cancel'; operation_id: string };
function boundedText(value: unknown, path?: string): string {
  const result = string(value, path);
  if (!result || result.length > 512 || hasEnvironmentControlCharacters(result))
    throw new Error('恢复记录无效');
  return result;
}
export function readPendingEnvironment(): {
  pending: PendingEnvironment | null;
  error: Error | null;
} {
  try {
    const raw = window.sessionStorage.getItem(pendingEnvironmentKey);
    if (!raw) return { pending: null, error: null };
    if (raw.length > 16_384) throw new Error('恢复记录过大');
    const value = JSON.parse(raw) as unknown;
    const kind = object({ kind: string })(value).kind;
    const pending: PendingEnvironment =
      kind === 'operation'
        ? { kind, request: object({ request: decodeEnvironmentRequest })(value).request }
        : kind === 'settings'
          ? { kind, ...object({ install_root: boundedText, expected_revision: count })(value) }
          : kind === 'cancel'
            ? {
                kind,
                operation_id: object({ operation_id: decodeEnvironmentOperationId })(value)
                  .operation_id,
              }
            : (() => {
                throw new Error('未知恢复记录');
              })();
    return { pending, error: null };
  } catch {
    return {
      pending: null,
      error: new Error(
        '无法读取环境操作恢复记录。未自动重放任何请求；请先刷新服务器操作历史，再明确清除本功能的损坏记录。',
      ),
    };
  }
}
export function persistPendingEnvironment(pending: PendingEnvironment): void {
  try {
    window.sessionStorage.setItem(pendingEnvironmentKey, JSON.stringify(pending));
  } catch {
    throw new Error('无法保存环境操作的恢复信息，未发送请求。请允许本地站点的会话存储后再试。');
  }
}
export function clearPendingEnvironment(): void {
  window.sessionStorage.removeItem(pendingEnvironmentKey);
}
