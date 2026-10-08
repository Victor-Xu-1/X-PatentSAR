import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { createSARApi } from '../src/api/sarApi';
import { initialMapping } from '../src/features/sar/csvMapping';
import {
  csvPreview,
  sarDataset,
  sarDrawing,
  sarJob,
  sarMolecule,
  sarPair,
  sarRegion,
} from './sar-fixtures';
import { json, session } from './fixtures';

const id = 'f'.repeat(32);
describe('SAR wire uses the existing session boundary', () => {
  it.each(['text/csv', 'application/octet-stream'])(
    'uploads raw %s bytes with encoded original filename and existing CSRF',
    async (type) => {
      const transport = vi.fn<typeof fetch>(async (url) =>
        json(String(url).endsWith('/session') ? session : csvPreview),
      );
      const shared = new ApiClient(transport);
      const api = createSARApi(shared, transport);
      const file = new File(['identifier_label,smiles\n007B,CCO'], '原文 & data.csv', { type });
      expect(await api.preview(file)).toEqual(csvPreview);
      const [url, request] = transport.mock.calls[1]!;
      expect(new URL(String(url), 'http://localhost').searchParams.get('filename')).toBe(file.name);
      expect(String(url)).toMatch(/^\/api\/v1\/sar\/csv\/preview\?/);
      expect(request?.body).toBe(file);
      expect(request?.credentials).toBe('same-origin');
      expect(new Headers(request?.headers).get('Content-Type')).toBe(type);
      expect(new Headers(request?.headers).get('X-CSRF-Token')).toBe(session.csrf_token);
      expect(transport).toHaveBeenCalledTimes(2);
    },
  );
  it('preserves exact long-CSV request payload and request identity', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(
        String(url).endsWith('/session')
          ? session
          : { ...sarDataset, source_kind: 'csv', source_project_id: null },
        201,
      ),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    const payload = { ...initialMapping(csvPreview), token: csvPreview.token, request_id: id };
    await api.createCSV(payload);
    expect(String(transport.mock.calls[1]?.[0])).toBe('/api/v1/sar/datasets/csv');
    expect(JSON.parse(String(transport.mock.calls[1]?.[1]?.body))).toEqual(payload);
  });
  it('reads paged searchable rows, graph drawing and scoped jobs without any mutation', async () => {
    const transport = vi.fn<typeof fetch>(async (url) => {
      const path = String(url);
      if (path.endsWith('/session')) return json(session);
      if (path.endsWith('/drawing')) return json(sarDrawing);
      if (path.includes('/molecules?'))
        return json({ items: [sarMolecule], total: 80, page: 2, page_size: 50 });
      if (path.endsWith('/jobs')) return json({ items: [sarJob], total: 1 });
      if (path.includes('/pairs?'))
        return json({ items: [sarPair], total: 1, page: 1, page_size: 50, job: sarJob });
      if (path.endsWith('/job-control')) return json(sarJob);
      if (path.endsWith('/sar/datasets')) return json({ items: [sarDataset], total: 1 });
      return json(sarDataset);
    });
    const api = createSARApi(new ApiClient(transport), transport);
    const signal = new AbortController().signal;
    await api.datasets(signal);
    await api.dataset(sarDataset.id, signal);
    await api.molecules(sarDataset.id, 2, '原文 & 007B', signal);
    await api.drawing(sarDataset.id, sarMolecule.id, signal);
    await api.jobs(sarDataset.id, signal);
    await api.job(sarJob.id, sarDataset.id, signal);
    await api.pairs(sarJob.id, sarDataset.id, 1, signal);
    expect(transport.mock.calls.every(([, request]) => request?.method === 'GET')).toBe(true);
    const query = new URL(
      String(transport.mock.calls.find(([url]) => String(url).includes('/molecules?'))?.[0]),
      'http://localhost',
    ).searchParams;
    expect(Object.fromEntries(query)).toEqual({ page: '2', page_size: '50', query: '原文 & 007B' });
    expect(
      transport.mock.calls.some(([url]) => String(url).includes('reference%2Fcontrol/drawing')),
    ).toBe(true);
  });
  it('submits immutable graph/revision/indices and refuses a mismatched region response', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(
        String(url).endsWith('/session') ? session : { ...sarRegion, graph_sha256: '0'.repeat(64) },
      ),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    const payload = {
      molecule_id: sarMolecule.id,
      expected_dataset_revision: 2,
      expected_graph_sha256: sarMolecule.graph_sha256!,
      atom_indices: [1],
    };
    await expect(api.saveRegion(sarDataset.id, payload)).rejects.toMatchObject({
      uncertain: true,
      code: 'invalid_write_response',
    });
    expect(JSON.parse(String(transport.mock.calls[1]?.[1]?.body))).toEqual(payload);
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('creates an analysis with explicit missing-context consent, grade order and immutable revision', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : sarJob, 202),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    const payload = {
      request_id: id,
      expected_dataset_revision: 2,
      region_id: sarRegion.id,
      metric_id: 'metric-control',
      direction: 'lower' as const,
      grade_order: [],
      confirm_context: false,
    };
    await api.analyse(sarDataset.id, payload);
    expect(JSON.parse(String(transport.mock.calls[1]?.[1]?.body))).toEqual(payload);
  });
  it('uses DELETE 204 only, including staging cleanup, with no extraction job request', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session') ? json(session) : new Response(null, { status: 204 }),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await api.discardPreview(csvPreview.token);
    await api.removeDataset(sarDataset.id);
    await api.removeJob(sarJob.id);
    expect(transport.mock.calls.slice(1).map(([, request]) => request?.method)).toEqual([
      'DELETE',
      'DELETE',
      'DELETE',
    ]);
    expect(
      transport.mock.calls
        .slice(1)
        .every(
          ([, request]) => new Headers(request?.headers).get('X-CSRF-Token') === session.csrf_token,
        ),
    ).toBe(true);
  });
  it('does not replay a cleanup-unverified SAR job deletion', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json(
            {
              error: {
                code: 'sar_process_unverified',
                message: 'Verify owned SAR worker cleanup.',
              },
            },
            409,
          ),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await expect(api.removeJob(sarJob.id)).rejects.toMatchObject({
      status: 409,
      code: 'sar_process_unverified',
      uncertain: false,
    });
    expect(transport.mock.calls[1]?.[0]).toBe('/api/v1/sar/jobs/job-control');
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('GET exports actual bytes of the requested format, not a JSON POST or local calculation', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('identifier,value\n007B,<10', {
            headers: { 'Content-Type': 'text/csv; charset=utf-8' },
          }),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    const blob = await api.export(sarJob.id, 'csv', new AbortController().signal);
    expect(await blob.text()).toContain('007B,<10');
    expect(transport.mock.calls[1]?.[0]).toBe('/api/v1/sar/jobs/job-control/export?format=csv');
    expect(transport.mock.calls[1]?.[1]?.method).toBe('GET');
    expect(transport.mock.calls[1]?.[1]?.body).toBeUndefined();
  });
  it('retains the full JSON recomputation payload as raw download bytes', async () => {
    const bytes = JSON.stringify({
      molecules: [
        {
          id: 'raw/control',
          label: '原始编号',
          molfile: 'raw MDL document',
          observations: sarMolecule.observations,
        },
      ],
      pairs: [sarPair],
    });
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response(bytes, { headers: { 'Content-Type': 'application/json' } }),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    expect(await (await api.export(sarJob.id, 'json', new AbortController().signal)).text()).toBe(
      bytes,
    );
    expect(transport.mock.calls[1]?.[0]).toBe('/api/v1/sar/jobs/job-control/export?format=json');
  });
  it('cancel is an empty JSON mutation and resume preserves exact input SHA', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : sarJob),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await api.cancel(sarJob.id, sarDataset.id);
    await api.resume(sarJob.id, sarDataset.id, { expected_input_sha256: sarJob.input_sha256 });
    expect(JSON.parse(String(transport.mock.calls[1]?.[1]?.body))).toEqual({});
    expect(JSON.parse(String(transport.mock.calls[2]?.[1]?.body))).toEqual({
      expected_input_sha256: sarJob.input_sha256,
    });
  });
});
describe('SAR uncertain writes and untrusted reads fail closed', () => {
  it('retains an uncertain identity when the same logical payload is explicitly submitted after navigation', async () => {
    let attempts = 0;
    const transport = vi.fn<typeof fetch>(async (url) => {
      if (String(url).endsWith('/session')) return json(session);
      if (++attempts === 1) throw new TypeError('lost connection');
      return json(sarDataset, 201);
    });
    const api = createSARApi(new ApiClient(transport), transport);
    const fields = { project_id: sarDataset.source_project_id!, title: null };
    await expect(api.createProject({ ...fields, request_id: id })).rejects.toMatchObject({
      uncertain: true,
      requestId: id,
    });
    expect(transport).toHaveBeenCalledTimes(2);
    await api.createProject({ ...fields, request_id: '1'.repeat(32) });
    expect(JSON.parse(String(transport.mock.calls[2]?.[1]?.body)).request_id).toBe(id);
    await api.createProject({ ...fields, request_id: '2'.repeat(32) });
    expect(JSON.parse(String(transport.mock.calls[3]?.[1]?.body)).request_id).toBe('2'.repeat(32));
  });
  it('preserves uncertainty and the response-limit cause after a write response exceeds the shared bound', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('{}', {
            status: 201,
            headers: { 'Content-Length': String(9 * 1024 * 1024) },
          }),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await expect(
      api.createProject({ project_id: 'project-control', title: null, request_id: id }),
    ).rejects.toMatchObject({ uncertain: true, code: 'response_limit' });
    await expect(api.preview(new File(['id,smiles'], 'a.csv'))).rejects.toMatchObject({
      uncertain: true,
      code: 'response_limit',
    });
    expect(transport).toHaveBeenCalledTimes(3);
  });
  it('does not replay a lost raw-file or JSON write', async () => {
    const transport = vi.fn<typeof fetch>(async (url) => {
      if (String(url).endsWith('/session')) return json(session);
      throw new TypeError('lost connection');
    });
    const api = createSARApi(new ApiClient(transport), transport);
    await expect(api.preview(new File(['id,smiles'], 'a.csv'))).rejects.toMatchObject({
      uncertain: true,
    });
    expect(transport).toHaveBeenCalledTimes(2);
    await expect(
      api.createProject({ project_id: 'project-control', title: null, request_id: id }),
    ).rejects.toMatchObject({ uncertain: true });
    expect(transport).toHaveBeenCalledTimes(3);
  });
  it('retains uncertainty after a successful but malformed preview or delete response', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : {}, 201),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await expect(api.preview(new File(['id,smiles'], 'a.csv'))).rejects.toMatchObject({
      uncertain: true,
    });
    await expect(api.removeDataset(sarDataset.id)).rejects.toMatchObject({ uncertain: true });
    expect(transport).toHaveBeenCalledTimes(3);
  });
  it('keeps 409 and auth failures explicit and never renders server HTML', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('<h1>private traceback</h1>', { status: 409 }),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    await expect(api.removeDataset(sarDataset.id)).rejects.toMatchObject({
      status: 409,
      uncertain: false,
    });
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('rejects foreign dataset/job/molecule and unexpected pagination identities', async () => {
    const transport = vi.fn<typeof fetch>(async (url) => {
      if (String(url).endsWith('/session')) return json(session);
      if (String(url).endsWith('/drawing'))
        return json({ ...sarDrawing, molecule: { ...sarMolecule, id: 'foreign' } });
      if (String(url).includes('/molecules?'))
        return json({ items: [], total: 0, page: 8, page_size: 50 });
      return json({ ...sarDataset, id: 'foreign' });
    });
    const api = createSARApi(new ApiClient(transport), transport);
    const signal = new AbortController().signal;
    await expect(api.dataset(sarDataset.id, signal)).rejects.toThrow();
    await expect(api.molecules(sarDataset.id, 1, '', signal)).rejects.toThrow();
    await expect(api.drawing(sarDataset.id, sarMolecule.id, signal)).rejects.toThrow();
  });
  it('does not issue a stale aborted export or render an HTML export', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('<html>unsafe</html>', { headers: { 'Content-Type': 'text/html' } }),
    );
    const shared = new ApiClient(transport);
    await shared.bootstrap();
    const api = createSARApi(shared, transport);
    const controller = new AbortController();
    controller.abort();
    await expect(api.export(sarJob.id, 'csv', controller.signal)).rejects.toThrow();
    expect(transport).toHaveBeenCalledOnce();
    await expect(api.export(sarJob.id, 'csv', new AbortController().signal)).rejects.toThrow(
      '导出响应格式',
    );
  });
});
