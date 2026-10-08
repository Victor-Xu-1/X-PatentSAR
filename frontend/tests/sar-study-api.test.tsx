import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { createSARStudyApi } from '../src/api/sarStudyApi';
import { decodeStudyProfile, decodeStudyReport } from '../src/api/sarStudyDecoders';
import { decodeMolecule, decodeRegion } from '../src/api/sarDecoders';
import { decodeSARJob, decodePair } from '../src/api/sarJobDecoders';
import { policyFromDraft, emptyPolicy } from '../src/features/sar/study/policyDraft';
import { initialMapping, mappingValid } from '../src/features/sar/csvMapping';
import { json, session } from './fixtures';
import {
  coreRegion,
  csvPreview,
  sarDataset,
  sarDrawing,
  sarMolecule,
  sarPair,
  studyContext,
  studyJob,
  studyProfile,
  studyReport,
  studyRow,
} from './sar-fixtures';
const body = {
  title: 'Raw 用户 draft',
  request_id: 'f'.repeat(32),
  expected_dataset_revision: 2,
  policies: studyReport.policies,
  region_ids: [],
  core_ids: [coreRegion.id],
  candidate_count: 8,
  confirm_context: false,
};
const filter = {
  query: '',
  scope: 'all' as const,
  scaffold_id: '',
  region_id: '',
  fragment_id: '',
};
describe('study DTOs and exact policies', () => {
  it('decodes full source-owned report facts, core role, old reference fixtures and additive evidence', () => {
    expect(decodeStudyProfile(studyProfile)).toEqual(studyProfile);
    expect(decodeStudyReport(studyReport)).toEqual(studyReport);
    expect(decodeSARJob(studyJob).kind).toBe('study');
    expect(decodeRegion(coreRegion)).toEqual(coreRegion);
    expect(
      decodeMolecule({
        ...sarMolecule,
        properties: studyRow.properties,
        predictions: studyRow.predictions,
      }).properties,
    ).toEqual(studyRow.properties);
    expect(
      decodePair({
        ...sarPair,
        region_id: coreRegion.id,
        fragment_id: 'frag',
        variable_atom_indices: [1],
        attachment_mapping: [[0, 1]],
      }).attachment_mapping,
    ).toEqual([[0, 1]]);
  });
  it('refuses invented scientific success, ambiguous identity and impossible counts', () => {
    expect(() =>
      decodeStudyReport({ ...studyReport, article_algorithm_reproduced: true }),
    ).toThrow();
    expect(() => decodeStudyReport({ ...studyReport, research_only: false })).toThrow();
    expect(() =>
      decodeStudyReport({
        ...studyReport,
        scaffolds: [{ ...studyReport.scaffolds[0], strong_count: 90 }],
      }),
    ).toThrow();
    expect(() =>
      decodeStudyProfile({ ...studyProfile, contexts: [studyContext, studyContext] }),
    ).toThrow();
    expect(() => decodeRegion({ ...coreRegion, kind: 'advantage' })).toThrow();
  });
  it('never infers grades, thresholds or direction and forbids mixed numeric/grade conventions', () => {
    expect(policyFromDraft(studyContext.id, emptyPolicy())).toBeNull();
    expect(
      policyFromDraft(studyContext.id, { ...emptyPolicy(), direction: 'lower' }),
    ).toMatchObject({ grade_order: [], strong_threshold: null });
    for (const threshold of ['<10', 'NaN', 'Infinity', '1e999'])
      expect(
        policyFromDraft(studyContext.id, { ...emptyPolicy(), direction: 'lower', threshold }),
      ).toBeNull();
    expect(
      policyFromDraft(studyContext.id, { ...emptyPolicy(), direction: 'higher', grades: 'A\nA' }),
    ).toBeNull();
    expect(
      policyFromDraft(studyContext.id, {
        ...emptyPolicy(),
        direction: 'higher',
        grades: 'strong\nweak',
        threshold: '10',
      }),
    ).toBeNull();
  });
  it('maps declared research/source-page columns only, rejects duplicate roles and preserves native long defaults', () => {
    const preview = { ...csvPreview, headers: [...csvPreview.headers, 'mw', 'risk', 'page'] };
    const draft = initialMapping(preview);
    expect(draft.property_columns).toBeUndefined();
    expect(draft.prediction_columns).toBeUndefined();
    expect(
      mappingValid(
        {
          ...draft,
          property_columns: { molecular_weight: 'mw' },
          prediction_columns: { hERG: 'risk' },
          source_page_column: 'page',
        },
        preview,
      ),
    ).toBe(true);
    expect(
      mappingValid({ ...draft, property_columns: { molecular_weight: 'value' } }, preview),
    ).toBe(false);
    expect(
      mappingValid(
        {
          ...draft,
          property_columns: { molecular_weight: 'mw' },
          prediction_columns: { hERG: 'mw' },
        },
        preview,
      ),
    ).toBe(false);
  });
});
describe('authenticated, bounded study API adapter', () => {
  it('uses exact GET profiles/overview, whole-pool row filters and drawing identifiers', async () => {
    const transport = vi.fn<typeof fetch>(async (url) => {
      const path = String(url);
      if (path.endsWith('/session')) return json(session);
      if (path.endsWith('/profile')) return json(studyProfile);
      if (path.includes('/rows?'))
        return json({ items: [studyRow], total: 100, page: 2, page_size: 50, job: studyJob });
      if (path.includes('/drawing?')) return json({ id: 'fragment / 原文', svg: sarDrawing.svg });
      return json({ job: studyJob, report: studyReport });
    });
    const api = createSARStudyApi(new ApiClient(transport), transport),
      signal = new AbortController().signal;
    await api.profile(sarDataset.id, 2, signal);
    await api.overview(studyJob.id, sarDataset.id, signal);
    await api.rows(
      studyJob.id,
      sarDataset.id,
      2,
      { ...filter, query: '原文 %_[C@H]', region_id: 'region', fragment_id: 'fragment' },
      signal,
    );
    await api.drawing(studyJob.id, 'fragment', 'fragment / 原文', signal, 'region');
    expect(transport.mock.calls.every(([, r]) => r?.method === 'GET')).toBe(true);
    const drawing = new URL(String(transport.mock.calls.at(-1)?.[0]), 'http://localhost');
    expect(Object.fromEntries(drawing.searchParams)).toEqual({
      kind: 'fragment',
      identifier: 'fragment / 原文',
      region_id: 'region',
    });
    await expect(api.profile(sarDataset.id, 4, signal)).rejects.toThrow();
  });
  it('binds explicit study writes to the exact nested body, retaining same-policy 5xx nonce but not different policies', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ error: { code: 'sar_unknown', message: 'Unknown' } }, 503),
    );
    const api = createSARStudyApi(new ApiClient(transport), transport);
    await expect(api.start(sarDataset.id, body)).rejects.toMatchObject({
      uncertain: true,
      requestId: body.request_id,
    });
    expect(transport).toHaveBeenCalledTimes(2);
    await expect(
      api.start(sarDataset.id, { ...body, request_id: 'a'.repeat(32) }),
    ).rejects.toMatchObject({ requestId: body.request_id });
    const changed = {
      ...body,
      request_id: 'b'.repeat(32),
      policies: [{ ...body.policies[0]!, direction: 'higher' as const }],
    };
    await expect(api.start(sarDataset.id, changed)).rejects.toMatchObject({
      requestId: changed.request_id,
    });
    expect(JSON.parse(String(transport.mock.calls.at(-1)?.[1]?.body))).toEqual(changed);
    expect(new Headers(transport.mock.calls.at(-1)?.[1]?.headers).get('X-CSRF-Token')).toBe(
      session.csrf_token,
    );
  });
  it.each([
    ['csv', 'text/csv'],
    ['json', 'application/json'],
    ['sdf', 'chemical/x-mdl-sdfile'],
    ['html', 'text/html'],
  ] as const)(
    'exports unmodified %s bytes as a download, never a JSON write',
    async (format, mime) => {
      const bytes =
        format === 'html' ? '<html>Original fixture only</html>' : 'Original raw fixture\n';
      const transport = vi.fn<typeof fetch>(async (url) =>
        String(url).endsWith('/session')
          ? json(session)
          : new Response(bytes, { headers: { 'Content-Type': mime } }),
      );
      const api = createSARStudyApi(new ApiClient(transport), transport);
      expect(
        await (await api.export(studyJob.id, format, new AbortController().signal)).text(),
      ).toBe(bytes);
      expect(transport.mock.calls[1]?.[1]?.method).toBe('GET');
      expect(String(transport.mock.calls[1]?.[0])).toContain('/study/export?format=' + format);
    },
  );
  it('rejects wrong job/report identity, overlong search and wrong download MIME', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ job: { ...studyJob, id: 'foreign' }, report: studyReport }),
    );
    const api = createSARStudyApi(new ApiClient(transport), transport);
    await expect(
      api.overview(studyJob.id, sarDataset.id, new AbortController().signal),
    ).rejects.toThrow();
    expect(() =>
      api.rows(
        studyJob.id,
        sarDataset.id,
        1,
        { ...filter, query: 'x'.repeat(201) },
        new AbortController().signal,
      ),
    ).toThrow();
    transport.mockImplementation(
      async () => new Response('untrusted', { headers: { 'Content-Type': 'text/plain' } }),
    );
    await expect(
      api.export(studyJob.id, 'html', new AbortController().signal),
    ).rejects.toMatchObject({ code: 'invalid_download' });
  });
  it('accepts a complete study report over the shared 8 MiB cap without truncation, bounded by the native 32 MiB limit', async () => {
    const report = { ...studyReport, warnings: ['x'.repeat(8 * 1024 * 1024 + 10)] };
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session') ? json(session) : json({ job: studyJob, report }),
    );
    const api = createSARStudyApi(new ApiClient(transport), transport);
    expect(
      (await api.overview(studyJob.id, sarDataset.id, new AbortController().signal)).report
        .warnings[0],
    ).toHaveLength(8 * 1024 * 1024 + 10);
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('rejects an over-budget report before parsing or pretending that a partial report succeeded', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('{}', {
            headers: {
              'Content-Type': 'application/json',
              'Content-Length': String(32 * 1024 * 1024 + 1),
            },
          }),
    );
    const api = createSARStudyApi(new ApiClient(transport), transport);
    await expect(
      api.overview(studyJob.id, sarDataset.id, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'response_limit', uncertain: false });
    expect(transport).toHaveBeenCalledTimes(2);
  });
});
