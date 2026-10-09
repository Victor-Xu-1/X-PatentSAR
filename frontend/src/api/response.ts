import { ApiError } from './errors';

export async function readJson(response: Response): Promise<unknown> {
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

// Buffer under the request's deadline so a server that stalls after headers cannot hang a read.
export async function boundedResponse(response: Response, limit: number): Promise<Response> {
  if (Number(response.headers.get('Content-Length')) > limit) {
    await response.body?.cancel();
    throw new ApiError(0, 'response_limit', 'API 响应超过大小限制，已停止加载。');
  }
  if (!response.body) return response;
  const reader = response.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new ApiError(0, 'response_limit', 'API 响应超过大小限制，已停止加载。');
      }
      chunks.push(Uint8Array.from(next.value));
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return new Response(bytes, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } finally {
    reader.releaseLock();
  }
}
