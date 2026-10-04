import { beforeEach, describe, expect, it, vi } from 'vitest';
import { convertMolfile } from '../src/features/structure-editor/structureConversion';
import { client } from '../src/api';
import { json, session } from './fixtures';

const molfile = 'raw MDL\r\nCFG=1 atom; CFG=2 bond; STEABS\r\n';
beforeEach(() => client.resetSession());

describe('authenticated bounded local structure conversion', () => {
  it.each([null, 'F[C@H](Br)Cl', 'F/C=C/F', '[13CH3][C@H](O)C(=O)[O-].[Na+]'])(
    'accepts the canonical plain result %s without changing chemistry',
    async (smiles) => {
      const transport = vi
        .fn()
        .mockResolvedValueOnce(json(session))
        .mockResolvedValueOnce(json({ smiles }));
      vi.stubGlobal('fetch', transport);
      expect(await convertMolfile(molfile, new AbortController().signal)).toBe(smiles);
      expect(transport).toHaveBeenNthCalledWith(
        1,
        '/api/v1/session',
        expect.objectContaining({
          method: 'GET',
          credentials: 'same-origin',
        }),
      );
      const request = transport.mock.calls[1]![1] as RequestInit;
      expect(request.method).toBe('POST');
      expect(request.credentials).toBe('same-origin');
      // Boolean comparison avoids printing a session token on a failed assertion.
      expect(new Headers(request.headers).get('X-CSRF-Token') === session.csrf_token).toBe(true);
      expect(request.body).toBe(JSON.stringify({ molfile }));
    },
  );
  it.each([
    {},
    [],
    { smiles: undefined },
    { smiles: '' },
    { smiles: 0 },
    { smiles: {} },
    { smiles: 'x'.repeat(2049) },
    { smiles: ' CCO' },
    { smiles: 'CCO\n' },
    { smiles: 'CCO |o1:1|' },
  ])('fails malformed or structured responses closed (%j)', async (payload) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json(payload)),
    );
    await expect(convertMolfile(molfile, new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid_write_response',
    });
  });
  it.each([401, 403, 422, 503])('does not retry or fall back after HTTP %s', async (status) => {
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(
        json(
          {
            error: { code: 'structure_conversion_invalid', message: 'Unsupported structure' },
          },
          status,
        ),
      );
    vi.stubGlobal('fetch', transport);
    await expect(convertMolfile(molfile, new AbortController().signal)).rejects.toMatchObject({
      code: 'structure_conversion_invalid',
      status,
    });
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('rejects oversized UTF-8 MDL before fetching and bounds streamed responses', async () => {
    const transport = vi.fn();
    vi.stubGlobal('fetch', transport);
    await expect(convertMolfile('界'.repeat(43691), new AbortController().signal)).rejects.toThrow(
      '编辑范围',
    );
    expect(transport).not.toHaveBeenCalled();
    transport
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(
        new Response('', { headers: { 'Content-Length': String(8 * 1024 * 1024 + 1) } }),
      );
    await expect(convertMolfile(molfile, new AbortController().signal)).rejects.toMatchObject({
      code: 'response_limit',
    });
  });
  it.each(['session', 'conversion'])(
    'bounds the entire %s fetch including ignored aborts',
    async (stage) => {
      vi.useFakeTimers();
      const transport = vi.fn();
      if (stage === 'conversion') transport.mockResolvedValueOnce(json(session));
      transport.mockReturnValueOnce(new Promise<Response>(() => {}));
      vi.stubGlobal('fetch', transport);
      const request = convertMolfile(molfile, new AbortController().signal);
      const assertion = expect(request).rejects.toThrow('结构转换超时');
      await vi.advanceTimersByTimeAsync(15001);
      await assertion;
      expect((transport.mock.calls.at(-1)![1].signal as AbortSignal).aborted).toBe(
        stage === 'conversion',
      );
      expect(transport).toHaveBeenCalledTimes(stage === 'session' ? 1 : 2);
      if (stage === 'conversion') expect(vi.getTimerCount()).toBe(0);
    },
  );
});
