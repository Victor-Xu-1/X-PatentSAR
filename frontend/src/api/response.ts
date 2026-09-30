import { ApiError } from './errors';

// Buffer under the request's deadline so a server that stalls after headers cannot hang a read.
export async function boundedResponse(response: Response, limit: number): Promise<Response> {
  if (Number(response.headers.get('Content-Length')) > limit)
    throw new ApiError(0, 'response_limit', 'API 响应超过大小限制，已停止加载。');
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
