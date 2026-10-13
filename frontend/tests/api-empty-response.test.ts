import { expect, it, vi } from 'vitest';
import { boundedResponse } from '../src/api/response';
import { createSARApi } from '../src/api/sarApi';
import { ApiClient } from '../src/api/client';
import { json, session } from './fixtures';

function streamed(status: number, text = '') {
  const response = new Response(null, { status, headers: { 'X-Controlled': 'retained' } });
  // Native Chromium may expose an empty stream on a bodyless HTTP status,
  // unlike a constructed Response(null). Exercise that observable contract.
  Object.defineProperty(response, 'body', {
    value: new ReadableStream({
      start(controller) {
        if (text) controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    }),
  });
  return response;
}

it.each([204, 205, 304])(
  'preserves empty streamed HTTP %s without constructing an illegal body',
  async (status) => {
    const result = await boundedResponse(streamed(status), 128);
    expect(result.status).toBe(status);
    expect(result.body).toBeNull();
    expect(await result.text()).toBe('');
    expect(result.headers.get('X-Controlled')).toBe('retained');
  },
);

it('does not turn a confirmed native DELETE into an uncertain write', async () => {
  const transport = vi.fn<typeof fetch>(async (url) =>
    String(url).endsWith('/session') ? json(session) : streamed(204),
  );
  const api = createSARApi(new ApiClient(transport), transport);
  await expect(api.removeJob('controlled')).resolves.toBeUndefined();
  expect(transport.mock.calls[1]![1]!.method).toBe('DELETE');
});

it.each([204, 205, 304])(
  'refuses nonempty HTTP %s rather than discarding evidence',
  async (status) => {
    await expect(boundedResponse(streamed(status, 'unexpected'), 128)).rejects.toMatchObject({
      code: 'invalid_response_body',
    });
  },
);

it('keeps ordinary bodies and response-size guards', async () => {
  const result = await boundedResponse(new Response('value', { status: 200 }), 5);
  expect(await result.text()).toBe('value');
  await expect(boundedResponse(new Response('value'), 4)).rejects.toMatchObject({
    code: 'response_limit',
  });
  const declared = streamed(204);
  declared.headers.set('Content-Length', '999');
  await expect(boundedResponse(declared, 4)).rejects.toMatchObject({ code: 'response_limit' });
});

it('keeps a malformed successful deletion uncertain and never retries it', async () => {
  const transport = vi.fn<typeof fetch>(async (url) =>
    String(url).endsWith('/session') ? json(session) : streamed(204, 'unexpected'),
  );
  const api = createSARApi(new ApiClient(transport), transport);
  await expect(api.removeJob('controlled')).rejects.toMatchObject({
    code: 'invalid_response_body',
    uncertain: true,
  });
  expect(transport).toHaveBeenCalledTimes(2);
});
