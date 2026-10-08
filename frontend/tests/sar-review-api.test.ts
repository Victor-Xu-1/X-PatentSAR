import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { createSARApi } from '../src/api/sarApi';
import { UncertainSARWrite } from '../src/api/sarMutation';
import { initialMapping, mappingValid } from '../src/features/sar/csvMapping';
import { csvPreview, sarDataset, sarInvalid } from './sar-fixtures';
import { json, session } from './fixtures';

describe('SAR review: exact request ownership and metadata', () => {
  it.each([500, 502, 503, 504])(
    'retains the nonce after HTTP %s, without automatic replay',
    async (status) => {
      const transport = vi.fn<typeof fetch>(async (url) =>
        String(url).endsWith('/session')
          ? json(session)
          : json(
              { error: { code: 'sar_write_failed', message: 'Unknown committed state' } },
              status,
            ),
      );
      const api = createSARApi(new ApiClient(transport), transport);
      const payload = {
        project_id: sarDataset.source_project_id!,
        title: 'unchanged raw draft',
        request_id: 'a'.repeat(32),
      };
      await expect(api.createProject(payload)).rejects.toBeInstanceOf(UncertainSARWrite);
      expect(transport).toHaveBeenCalledTimes(2);
      transport.mockImplementation(async () => json(sarDataset, 201));
      // Explicit resubmission from a remounted form must use the original nonce.
      await api.createProject({ ...payload, request_id: 'b'.repeat(32) });
      expect(JSON.parse(String(transport.mock.calls[2]?.[1]?.body)).request_id).toBe(
        payload.request_id,
      );
      expect(transport).toHaveBeenCalledTimes(3);
    },
  );
  it.each(['preview', 'delete'] as const)(
    'treats a raw %s 5xx as uncertain, not a definitive failure',
    async (operation) => {
      const transport = vi.fn<typeof fetch>(async (url) =>
        String(url).endsWith('/session')
          ? json(session)
          : new Response('Unavailable', { status: 503 }),
      );
      const api = createSARApi(new ApiClient(transport), transport);
      await expect(
        operation === 'preview'
          ? api.preview(new File(['id,smiles'], 'raw.csv'))
          : api.removeDataset(sarDataset.id),
      ).rejects.toMatchObject({ status: 503, uncertain: true });
      expect(transport).toHaveBeenCalledTimes(2);
    },
  );
  it('reads invalid molecule metadata independently from drawing, preserving original evidence', async () => {
    const molecule = {
      ...sarInvalid,
      source_page: 19,
      observations: [
        {
          metric_id: 'metric-control',
          value: 'unparsed 原文',
          unit: null,
          context: { assay: 'original assay' },
          source_page: 20,
          source_row: 8,
          source_kind: 'imported',
        },
      ],
    };
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : molecule),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    expect(
      await api.molecule('dataset / 原文', sarInvalid.id, new AbortController().signal),
    ).toEqual(molecule);
    expect(transport.mock.calls[1]?.[0]).toBe(
      '/api/v1/sar/datasets/dataset%20%2F%20%E5%8E%9F%E6%96%87/molecules/invalid%2Fcontrol',
    );
    expect(transport.mock.calls[1]?.[1]?.method).toBe('GET');
    expect(transport.mock.calls.some(([url]) => String(url).endsWith('/drawing'))).toBe(false);
    await expect(
      api.molecule(sarDataset.id, 'wrong/control', new AbortController().signal),
    ).rejects.toThrow();
  });
  it('does not fetch metadata when the read is already aborted', async () => {
    const transport = vi.fn<typeof fetch>(async () => json(session));
    const api = createSARApi(new ApiClient(transport), transport);
    const controller = new AbortController();
    controller.abort();
    await expect(
      api.molecule(sarDataset.id, sarInvalid.id, controller.signal),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(transport).toHaveBeenCalledExactlyOnceWith('/api/v1/session', expect.anything());
  });
  it('sends literal label/SMILES queries up to 200 unchanged, rejecting longer input before GET', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(
        String(url).endsWith('/session')
          ? session
          : { items: [], total: 0, page: 1, page_size: 50 },
      ),
    );
    const api = createSARApi(new ApiClient(transport), transport);
    const signal = new AbortController().signal;
    const query = '[C@H](O)Cl %_' + '原'.repeat(187);
    expect(query).toHaveLength(200);
    await api.molecules(sarDataset.id, 1, query, signal);
    expect(
      new URL(String(transport.mock.calls[1]?.[0]), 'http://localhost').searchParams.get('query'),
    ).toBe(query);
    expect(() => api.molecules(sarDataset.id, 1, query + 'x', signal)).toThrow();
    expect(transport).toHaveBeenCalledTimes(2);
  });
});
describe('SAR review: long CSV mapping cardinality', () => {
  it('accepts native single-value long CSV, but never submits multiple value columns with metric_column', () => {
    const preview = { ...csvPreview, headers: [...csvPreview.headers, 'value2'] };
    const draft = initialMapping(preview);
    expect(mappingValid(draft, preview)).toBe(true);
    const wide = { ...draft, activity_columns: ['value', 'value2'] };
    expect(mappingValid(wide, preview)).toBe(false);
    expect(mappingValid({ ...wide, metric_column: null }, preview)).toBe(true);
  });
});
