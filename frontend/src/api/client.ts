import type { Decoder } from './validation';
import { ContractError } from './validation';
import { decodeSession } from './decoders';
import type { Session } from './types';
import { boundedResponse } from './response';
import { ApiError, errorFrom } from './errors';
import { UiError } from '../i18n';
async function readJson(response: Response): Promise<unknown> {
  if (Number(response.headers.get('Content-Length')) > 8 * 1024 * 1024)
    throw new ApiError(0, 'response_limit', 'API 响应过大，已停止加载。');
  const value = await response.text();
  if (value.length > 8 * 1024 * 1024)
    throw new ApiError(0, 'response_limit', 'API 响应过大，已停止加载。');
  try {
    return JSON.parse(value) as unknown;
  } catch {
    throw new ApiError(
      response.status,
      'invalid_json',
      '服务返回了无效 JSON，请检查 API 是否运行。',
    );
  }
}

export class ApiClient {
  private session: Session | null = null;
  private bootstrapping: Promise<Session> | null = null;
  constructor(
    private readonly transport: typeof fetch = (...args) => fetch(...args),
    private readonly timeout = 30_000,
  ) {}

  resetSession() {
    this.session = null;
    this.bootstrapping = null;
  }
  bootstrap(): Promise<Session> {
    if (this.session) return Promise.resolve(this.session);
    if (!this.bootstrapping) {
      this.bootstrapping = this.send('/session', { method: 'GET' }, undefined)
        .then(readJson)
        .then(decodeSession)
        .then((session) => {
          this.session = session;
          return session;
        })
        .finally(() => {
          this.bootstrapping = null;
        });
    }
    return this.bootstrapping;
  }

  private async send(
    path: string,
    init: RequestInit,
    signal: AbortSignal | undefined,
    timeoutMs = this.timeout,
  ): Promise<Response> {
    const write = init.method !== 'GET';
    const attempts = write ? 1 : 2;
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
        if (response.ok)
          return await boundedResponse(
            response,
            path.endsWith('/export') ? 128 * 1024 * 1024 : 8 * 1024 * 1024,
          );
        if (!write && attempt === 0 && [502, 503, 504].includes(response.status)) {
          await response.body?.cancel();
          await this.backoff(signal);
          continue;
        }
        if (response.status === 401) this.resetSession();
        let payload: unknown = null;
        try {
          payload = await readJson(response);
        } catch {
          /* Non-JSON errors retain the HTTP status without leaking server HTML. */
        }
        throw errorFrom(response.status, payload);
      } catch (error) {
        if (signal?.aborted) throw signal.reason;
        if (error instanceof ApiError) throw error;
        if (!write && attempt === 0) {
          await this.backoff(signal);
          continue;
        }
        throw new ApiError(
          0,
          controller.signal.aborted ? 'timeout' : 'network_error',
          write
            ? '连接中断，写入结果未知。请先刷新状态，再决定是否重新提交。'
            : '无法连接 API 服务，请检查服务地址并重新加载。',
          write,
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
    if (path !== '/health') await this.bootstrap();
    signal?.throwIfAborted();
    return decode(await readJson(await this.send(path, { method: 'GET' }, signal)));
  }
  private async write(
    path: string,
    method: 'POST' | 'PUT',
    body: BodyInit,
    contentType: string,
    options: { signal?: AbortSignal; timeoutMs?: number } = {},
  ): Promise<Response> {
    const session = await this.bootstrap();
    return this.send(
      path,
      {
        method,
        body,
        headers: { 'Content-Type': contentType, 'X-CSRF-Token': session.csrf_token },
      },
      options.signal,
      options.timeoutMs,
    );
  }
  async mutate<T>(
    path: string,
    method: 'POST' | 'PUT',
    payload: unknown,
    decode: Decoder<T>,
    options: { signal?: AbortSignal; timeoutMs?: number } = {},
  ): Promise<T> {
    const response = await this.write(
      path,
      method,
      JSON.stringify(payload),
      'application/json',
      options,
    );
    return this.decodeMutation(response, decode);
  }
  async upload<T>(path: string, file: File, decode: Decoder<T>): Promise<T> {
    return this.decodeMutation(await this.write(path, 'POST', file, 'application/pdf'), decode);
  }
  private async decodeMutation<T>(response: Response, decode: Decoder<T>): Promise<T> {
    try {
      return decode(await readJson(response));
    } catch (error) {
      throw new ApiError(
        response.status,
        'invalid_write_response',
        '服务已响应，但无法确认写入结果。请先检查已保存状态，不要盲目重新提交。{detail}',
        true,
        { detail: error instanceof ContractError ? error : new UiError('响应格式无效。') },
      );
    }
  }
  async download(path: string, payload: unknown): Promise<Blob> {
    const response = await this.write(path, 'POST', JSON.stringify(payload), 'application/json');
    const type = response.headers.get('Content-Type') ?? '';
    if (!/^(text\/csv|application\/json)/i.test(type))
      throw new ApiError(0, 'invalid_download', '导出响应格式无效，未保存文件。');
    const blob = await response.blob();
    if (blob.size > 128 * 1024 * 1024)
      throw new ApiError(0, 'download_limit', '导出文件超过 128 MiB 限制。');
    return blob;
  }
}
