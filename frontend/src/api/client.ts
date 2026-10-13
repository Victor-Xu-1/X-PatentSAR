import type { Decoder } from './validation';
import { ContractError } from './validation';
import { decodeSession } from './decoders';
import type { Session } from './types';
import { LocalSession } from './localSession';
import { boundedResponse, readJson } from './response';
import { ApiError, errorFrom } from './errors';
import { UiError } from '../i18n';
export class ApiClient {
  private readonly sessions = new LocalSession(() =>
    this.send('/session', { method: 'GET' }, undefined).then(readJson).then(decodeSession),
  );
  constructor(
    private readonly transport: typeof fetch = (...args) => fetch(...args),
    private readonly timeout = 30_000,
  ) {}

  resetSession() {
    this.sessions.reset();
  }
  bootstrap(): Promise<Session> {
    return this.sessions.bootstrap();
  }

  private async send(
    path: string,
    init: RequestInit,
    signal: AbortSignal | undefined,
    timeoutMs = this.timeout,
    mayWrite = init.method !== 'GET',
  ): Promise<Response> {
    const retryable = init.method === 'GET';
    const attempts = retryable ? 2 : 1;
    for (let attempt = 0; attempt < attempts; attempt++) {
      signal?.throwIfAborted();
      const controller = new AbortController();
      const relay = () => controller.abort(signal?.reason);
      signal?.addEventListener('abort', relay, { once: true });
      const timer = setTimeout(
        () => controller.abort(new DOMException('Timeout', 'TimeoutError')),
        timeoutMs,
      );
      try {
        const response = await this.transport(`/api/v1${path}`, {
          ...init,
          credentials: 'same-origin',
          signal: controller.signal,
          headers: { Accept: 'application/json', ...init.headers },
        });
        if (response.ok) {
          try {
            return await boundedResponse(
              response,
              path.split('?')[0]?.endsWith('/export') ? 128 * 1024 * 1024 : 8 * 1024 * 1024,
            );
          } catch (error) {
            if (mayWrite && error instanceof ApiError)
              throw this.unconfirmedResponse(response.status, error);
            throw error;
          }
        }
        if (retryable && attempt === 0 && [502, 503, 504].includes(response.status)) {
          await response.body?.cancel();
          await this.backoff(signal);
          continue;
        }
        let payload: unknown = null;
        try {
          payload = await readJson(await boundedResponse(response, 8 * 1024 * 1024));
        } catch {
          /* Non-JSON errors retain the HTTP status without leaking server HTML. */
        }
        const failure = errorFrom(response.status, payload);
        if (mayWrite && response.status >= 500)
          throw new ApiError(
            failure.status,
            failure.code,
            '服务暂时不可用，无法确认写入结果。请先刷新状态。',
            true,
          );
        throw failure;
      } catch (error) {
        if (signal?.aborted) throw signal.reason;
        if (error instanceof ApiError) throw error;
        if (retryable && attempt === 0) {
          await this.backoff(signal);
          continue;
        }
        throw new ApiError(
          0,
          controller.signal.aborted ? 'timeout' : 'network_error',
          mayWrite
            ? '连接中断，写入结果未知。请先刷新状态，再决定是否重新提交。'
            : '无法连接 API 服务，请检查服务地址并重新加载。',
          mayWrite,
        );
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', relay);
      }
    }
    throw new ApiError(0, 'network_error', 'API 请求失败。');
  }
  private backoff(signal: AbortSignal | undefined): Promise<void> {
    return new Promise((resolve, reject) => {
      signal?.throwIfAborted();
      const abort = () => {
        clearTimeout(timer);
        reject(signal?.reason);
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener('abort', abort);
        resolve();
      }, 300);
      signal?.addEventListener('abort', abort, { once: true });
    });
  }
  async get<T>(path: string, decode: Decoder<T>, signal?: AbortSignal): Promise<T> {
    const observed = path !== '/health' ? await this.bootstrap() : null;
    signal?.throwIfAborted();
    const read = async () =>
      decode(await readJson(await this.send(path, { method: 'GET' }, signal)));
    try {
      return await read();
    } catch (error) {
      if (!observed || !(error instanceof ApiError) || error.status !== 401) throw error;
      this.sessions.invalidate(observed);
      // Only the server's explicit same-origin session fault admits one safe GET
      // recovery. No mutation, readonly POST, arbitrary 401 or health is replayed.
      if (error.code !== 'session_required') throw error;
      signal?.throwIfAborted();
      const renewed = await this.bootstrap();
      signal?.throwIfAborted();
      try {
        return await read();
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 401)
          this.sessions.invalidate(renewed);
        throw failure;
      }
    }
  }
  private async authenticatedBody(
    path: string,
    method: 'POST' | 'PUT',
    body: BodyInit,
    contentType: string,
    options: { signal?: AbortSignal; timeoutMs?: number } = {},
    mayWrite = true,
  ): Promise<Response> {
    const session = await this.bootstrap();
    try {
      return await this.send(
        path,
        {
          method,
          body,
          headers: { 'Content-Type': contentType, 'X-CSRF-Token': session.csrf_token },
        },
        options.signal,
        options.timeoutMs,
        mayWrite,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) this.sessions.invalidate(session);
      throw error;
    }
  }
  async mutate<T>(
    path: string,
    method: 'POST' | 'PUT',
    payload: unknown,
    decode: Decoder<T>,
    options: { signal?: AbortSignal; timeoutMs?: number } = {},
  ): Promise<T> {
    const response = await this.authenticatedBody(
      path,
      method,
      JSON.stringify(payload),
      'application/json',
      options,
    );
    return this.decodeMutation(response, decode);
  }
  async upload<T>(path: string, file: File, decode: Decoder<T>): Promise<T> {
    return this.decodeMutation(
      await this.authenticatedBody(path, 'POST', file, 'application/pdf'),
      decode,
    );
  }
  /** Only the audited pure chemistry route is a read. POST keeps CSRF and one attempt. */
  async postRead<T>(
    path: '/chemistry/structure',
    payload: unknown,
    decode: Decoder<T>,
    options: { signal?: AbortSignal; timeoutMs?: number } = {},
  ): Promise<T> {
    if (path !== '/chemistry/structure') throw new ContractError('$.readonly_path');
    const response = await this.authenticatedBody(
      path,
      'POST',
      JSON.stringify(payload),
      'application/json',
      options,
      false,
    );
    try {
      return decode(await readJson(response));
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        response.status,
        'invalid_read_response',
        '结构校验响应无效，暂不能保存。',
      );
    }
  }
  private unconfirmedResponse(status: number, error: unknown): ApiError {
    if (error instanceof ApiError)
      return new ApiError(status, error.code, error.source, true, error.values);
    return new ApiError(
      status,
      'invalid_write_response',
      '服务已响应，但无法确认写入结果。请先检查已保存状态，不要盲目重新提交。{detail}',
      true,
      { detail: error instanceof ContractError ? error : new UiError('响应格式无效。') },
    );
  }
  private async decodeMutation<T>(response: Response, decode: Decoder<T>): Promise<T> {
    try {
      return decode(await readJson(response));
    } catch (error) {
      throw this.unconfirmedResponse(response.status, error);
    }
  }
  async download(path: string, payload: unknown): Promise<Blob> {
    const response = await this.authenticatedBody(
      path,
      'POST',
      JSON.stringify(payload),
      'application/json',
    );
    const type = response.headers.get('Content-Type') ?? '';
    if (!/^(text\/csv|application\/json)/i.test(type))
      throw new ApiError(0, 'invalid_download', '导出响应格式无效，未保存文件。');
    const blob = await response.blob();
    if (blob.size > 128 * 1024 * 1024)
      throw new ApiError(0, 'download_limit', '导出文件超过 128 MiB 限制。');
    return blob;
  }
}
