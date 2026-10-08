import type { ApiClient } from './client';
import { ApiError, errorFrom } from './errors';
import { boundedResponse } from './response';
import type { Decoder } from './validation';

/** Only the SAR raw-upload/DELETE/byte endpoints absent from the shared client. */
export function sarTransport(
  client: ApiClient,
  transport: typeof fetch = (...args) => fetch(...args),
) {
  async function send(
    path: string,
    method: 'POST' | 'DELETE' | 'GET',
    body?: BodyInit,
    contentType?: string,
    signal?: AbortSignal,
  ) {
    const session = await client.bootstrap();
    signal?.throwIfAborted();
    const controller = new AbortController();
    const relay = () => controller.abort(signal?.reason);
    signal?.addEventListener('abort', relay, { once: true });
    const timer = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await transport(`/api/v1${path}`, {
        method,
        credentials: 'same-origin',
        signal: controller.signal,
        ...(body === undefined ? {} : { body }),
        headers: {
          Accept: method === 'GET' ? 'text/csv, application/json' : 'application/json',
          ...(method === 'GET' ? {} : { 'X-CSRF-Token': session.csrf_token }),
          ...(contentType ? { 'Content-Type': contentType } : {}),
        },
      });
      const buffered = await boundedResponse(
        response,
        method === 'GET' ? 128 * 1024 * 1024 : 8 * 1024 * 1024,
      );
      signal?.throwIfAborted();
      if (!buffered.ok) {
        if (buffered.status === 401) client.resetSession();
        let payload: unknown = null;
        try {
          payload = JSON.parse(await buffered.text()) as unknown;
        } catch {
          /* Preserve status, never render server HTML. */
        }
        throw errorFrom(buffered.status, payload);
      }
      return buffered;
    } catch (error) {
      if (signal?.aborted) throw signal.reason;
      if (error instanceof ApiError) {
        if (error.status !== 0) throw error;
        throw new ApiError(error.status, error.code, error.source, method !== 'GET', error.values);
      }
      throw new ApiError(
        0,
        'sar_transport',
        method === 'GET'
          ? '无法连接 API 服务，请检查服务地址并重新加载。'
          : '连接中断，写入结果未知。请先刷新状态，再决定是否重新提交。',
        method !== 'GET',
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', relay);
    }
  }
  return {
    upload: async <T>(path: string, file: File, decode: Decoder<T>) => {
      const response = await send(
        path,
        'POST',
        file,
        file.type === 'text/csv' ? 'text/csv' : 'application/octet-stream',
      );
      try {
        return decode(JSON.parse(await response.text()) as unknown);
      } catch {
        throw new ApiError(
          response.status,
          'invalid_write_response',
          'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
          true,
        );
      }
    },
    remove: async (path: string) => {
      const response = await send(path, 'DELETE');
      if (response.status !== 204)
        throw new ApiError(
          response.status,
          'invalid_write_response',
          'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
          true,
        );
    },
    export: async (path: string, format: 'csv' | 'json', signal: AbortSignal) => {
      const response = await send(path, 'GET', undefined, undefined, signal);
      const type = response.headers.get('Content-Type') ?? '';
      if (!(format === 'csv' ? /^text\/csv(?:;|$)/i : /^application\/json(?:;|$)/i).test(type))
        throw new ApiError(0, 'invalid_download', '导出响应格式无效，未保存文件。');
      return response.blob();
    },
  };
}
