import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { decodeProjects, decodeProject } from '../src/api/decoders';
import { json, session } from './fixtures';

const missing = () =>
  json({ error: { code: 'session_required', message: 'Session unavailable' } }, 401);

describe('bounded same-origin session read recovery', () => {
  it('renews once and replays only the safe GET after a lost session', async () => {
    let reads = 0;
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : ++reads === 1
          ? missing()
          : json({ items: [] }),
    );
    expect(await new ApiClient(transport).get('/projects', decodeProjects)).toEqual({ items: [] });
    expect(transport.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/session',
      '/api/v1/projects',
      '/api/v1/session',
      '/api/v1/projects',
    ]);
    expect(
      transport.mock.calls.every(
        ([, init]) => init?.method === 'GET' && init.credentials === 'same-origin',
      ),
    ).toBe(true);
  });

  it('shares one renewal across concurrent stale reads, including a late old 401', async () => {
    let sessionReads = 0;
    let releaseLate!: (value: Response) => void;
    const attempts = new Map<string, number>();
    const transport = vi.fn<typeof fetch>(async (url) => {
      const path = String(url);
      if (path.endsWith('/session')) {
        sessionReads++;
        return json(session);
      }
      const count = (attempts.get(path) ?? 0) + 1;
      attempts.set(path, count);
      if (count > 1) return json({ items: [] });
      if (path.endsWith('/projects?late=1'))
        return new Promise<Response>((resolve) => {
          releaseLate = resolve;
        });
      return missing();
    });
    const client = new ApiClient(transport);
    await client.bootstrap();
    const late = client.get('/projects?late=1', decodeProjects);
    await client.get('/projects', decodeProjects);
    releaseLate(missing());
    await late;
    expect(sessionReads).toBe(2);
    expect([...attempts.values()]).toEqual([2, 2]);
  });

  it('stops after one auth renewal even if the recovered read is rejected again', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session') ? json(session) : missing(),
    );
    await expect(new ApiClient(transport).get('/projects', decodeProjects)).rejects.toMatchObject({
      status: 401,
      code: 'session_required',
    });
    expect(transport).toHaveBeenCalledTimes(4);
  });

  it('does not turn unrelated authorization denial into automatic reauthentication', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ error: { code: 'denied', message: 'Denied' } }, 401),
    );
    await expect(new ApiClient(transport).get('/projects', decodeProjects)).rejects.toMatchObject({
      code: 'denied',
    });
    expect(transport).toHaveBeenCalledTimes(2);
  });

  it('never replays a rejected mutation, upload, download or readonly POST', async () => {
    for (const action of ['mutate', 'upload', 'download', 'postRead'] as const) {
      const transport = vi.fn<typeof fetch>(async (url) =>
        String(url).endsWith('/session') ? json(session) : missing(),
      );
      const client = new ApiClient(transport);
      const request =
        action === 'mutate'
          ? client.mutate('/projects/id/jobs', 'POST', {}, decodeProject)
          : action === 'upload'
            ? client.upload('/projects', new File(['%PDF'], 'control.pdf'), decodeProject)
            : action === 'download'
              ? client.download('/projects/id/export', {})
              : client.postRead('/chemistry/structure', {}, (value) => value);
      await expect(request).rejects.toMatchObject({ status: 401 });
      expect(transport).toHaveBeenCalledTimes(2);
      await client.bootstrap();
      expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    }
  });

  it('does not publish a superseded bootstrap or send a write after explicit reconnect', async () => {
    let resolve!: (value: Response) => void;
    const transport = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    );
    const client = new ApiClient(transport);
    const writing = client.mutate('/projects/id/jobs', 'POST', {}, decodeProject);
    client.resetSession();
    resolve(json(session));
    await expect(writing).rejects.toMatchObject({ code: 'session_superseded' });
    expect(transport).toHaveBeenCalledOnce();
  });

  it('does not reissue a protected GET if its caller aborts during shared renewal', async () => {
    const controller = new AbortController();
    let sessions = 0,
      resolve!: (value: Response) => void;
    const transport = vi.fn<typeof fetch>(async (url) => {
      if (!String(url).endsWith('/session')) return missing();
      if (++sessions === 1) return json(session);
      return new Promise<Response>((done) => {
        resolve = done;
      });
    });
    const client = new ApiClient(transport);
    const reading = client.get('/projects', decodeProjects, controller.signal);
    await vi.waitFor(() => expect(sessions).toBe(2));
    controller.abort(new DOMException('cancelled', 'AbortError'));
    resolve(json(session));
    await expect(reading).rejects.toMatchObject({ name: 'AbortError' });
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/projects'))).toHaveLength(
      1,
    );
  });

  it('waits for an obsolete wire response before the explicit reconnect handshake', async () => {
    let resolve!: (value: Response) => void;
    const transport = vi
      .fn<typeof fetch>()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      )
      .mockResolvedValueOnce(json(session));
    const client = new ApiClient(transport);
    const old = client.bootstrap();
    const rejection = expect(old).rejects.toMatchObject({ code: 'session_superseded' });
    client.resetSession();
    const fresh = client.bootstrap();
    expect(transport).toHaveBeenCalledOnce();
    resolve(json(session));
    await rejection;
    await expect(fresh).resolves.toEqual(session);
    expect(transport).toHaveBeenCalledTimes(2);
  });
});
