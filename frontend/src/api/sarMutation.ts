import type { ApiClient } from './client';
import { ApiError } from './errors';
import { ContractError } from './validation';
import type { Decoder } from './validation';
import { UiError } from '../i18n';

export class UncertainSARWrite extends ApiError {
  constructor(
    error: ApiError,
    readonly requestId: string,
  ) {
    super(error.status, error.code, error.source, true, error.values);
  }
}
/** Session-memory identities survive component/navigation changes; no user data is persisted. */
export function createSARMutation(shared: ApiClient) {
  const unresolved = new Map<string, string>();
  return async <T>(path: string, payload: unknown, decode: Decoder<T>): Promise<T> => {
    let key: string | null = null;
    let requestId: string | null = null;
    let wire = payload;
    if (payload && typeof payload === 'object' && 'request_id' in payload) {
      const { request_id: supplied, ...fields } = payload as Record<string, unknown>;
      if (typeof supplied !== 'string' || !/^[a-f0-9]{32}$/.test(supplied))
        throw new ContractError('$.request_id');
      key = path + '\n' + JSON.stringify(fields, Object.keys(fields).sort());
      requestId = unresolved.get(key) ?? supplied;
      if (!unresolved.has(key) && unresolved.size >= 32)
        throw new UiError('尚有过多未确认写入，请先核对服务器状态。');
      unresolved.set(key, requestId);
      wire = { ...fields, request_id: requestId };
    }
    try {
      const result = await shared.mutate(path, 'POST', wire, decode);
      if (key) unresolved.delete(key);
      return result;
    } catch (error) {
      if (error instanceof ApiError && (error.uncertain || error.status === 0)) {
        if (requestId) throw new UncertainSARWrite(error, requestId);
        throw new ApiError(error.status, error.code, error.source, true, error.values);
      }
      if (key) unresolved.delete(key);
      throw error;
    }
  };
}
