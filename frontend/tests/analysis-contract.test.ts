import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { decodeAdmet, decodeEvidenceSummary, decodeRecognition } from '../src/api/analysisDecoders';
import { decodeJob } from '../src/api/decoders';
import { normalizePatentId } from '../src/model/tasks';
import { admet, evidence, recognized } from './analysis-fixtures';
import { job, json, project, session } from './fixtures';

beforeEach(() => client.resetSession());
describe('additive contract validation and scientific boundary', () => {
  it('waits beyond 30 seconds but bounds actual analysis transport at 190 seconds, without replay', async () => {
    vi.useFakeTimers();
    const transport = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input).endsWith('/session')) return json(session);
      return new Promise((_resolve, reject) =>
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true }),
      );
    });
    vi.stubGlobal('fetch', transport);
    const request = api.admet(['CCO'], new AbortController().signal);
    let settled = false;
    void request.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );
    const assertion = expect(request).rejects.toMatchObject({ code: 'timeout', uncertain: true });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(160_000);
    await assertion;
    expect(
      transport.mock.calls.filter(([input]) => String(input).endsWith('/analysis/admet')),
    ).toHaveLength(1);
  });
  it('defaults old jobs without inventing options and rejects malformed additive fields', () => {
    const { include_intermediates: _include, force: _force, task_note: _note, ...old } = job;
    expect(decodeJob(old)).toEqual(job);
    expect(() => decodeJob({ ...old, force: null })).toThrow('契约');
    expect(() => decodeJob({ ...old, include_intermediates: 'true' })).toThrow('契约');
  });
  it.each(['US-2026.156070_A', ' wo2026/156070 '])('normalizes bounded identifier %s', (id) => {
    expect(normalizePatentId(id)).toBe(id.trim().toUpperCase().replace('/', ''));
  });
  it.each(['../patent', 'US/2026', '1PATENT', '专利', 'A'.repeat(65), 'WO123;cmd'])(
    'rejects path/command/unbounded metadata %s',
    (id) => {
      expect(() => normalizePatentId(id)).toThrow('标识');
    },
  );
  it('requires review-only actual finite predictions and real model provenance', () => {
    expect(decodeAdmet(admet)).toEqual(admet);
    expect(() => decodeAdmet({ ...admet, review_only: false })).toThrow('契约');
    expect(() =>
      decodeAdmet({ ...admet, engine: { ...admet.engine, model_sha256: 'unknown' } }),
    ).toThrow('契约');
    expect(() =>
      decodeAdmet({
        ...admet,
        predictions: [
          {
            smiles: 'CCO',
            properties: [{ ...admet.predictions[0]!.properties[0], value: Infinity }],
          },
        ],
      }),
    ).toThrow('契约');
    expect(() => decodeRecognition({ ...recognized, smiles: null })).toThrow('契约');
    expect(() =>
      decodeEvidenceSummary({
        ...evidence,
        activities: [{ ...evidence.activities[0], min: 20, max: 1 }],
      }),
    ).toThrow('契约');
  });
  it('sends exact additive upload and job contracts; resume never overrides original options', async () => {
    const transport = vi.fn<typeof fetch>(async (input) =>
      String(input).endsWith('/session')
        ? json(session)
        : String(input).includes('/jobs')
          ? json(job, 202)
          : json(project, 201),
    );
    vi.stubGlobal('fetch', transport);
    await api.upload(new File(['%PDF-1.7'], 'p.pdf'), 'title', 'WO2026156070');
    expect(String(transport.mock.calls[1]![0])).toContain('patent_id=WO2026156070');
    await api.createJob(project.id, null, {
      include_intermediates: true,
      force: true,
      task_note: '运营记录',
    });
    expect(JSON.parse(String(transport.mock.calls[2]![1]?.body))).toEqual({
      allow_partial: false,
      advisory: false,
      resume_job_id: null,
      include_intermediates: true,
      force: true,
      task_note: '运营记录',
    });
    await api.createJob(project.id, job.id, { force: true, task_note: '不应覆盖' });
    expect(JSON.parse(String(transport.mock.calls[3]![1]?.body))).toEqual({
      allow_partial: false,
      advisory: false,
      resume_job_id: job.id,
    });
  });
  it('encodes actual scoped analysis paths and rejects cross-project or wrong-compound responses', async () => {
    const transport = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith('/session')) return json(session);
      if (url.endsWith('/analysis/admet')) return json(admet);
      if (url.endsWith('/recognize')) return json({ ...recognized, compound_id: 'wrong' });
      return json({ ...evidence, project_id: 'wrong' });
    });
    vi.stubGlobal('fetch', transport);
    const signal = new AbortController().signal;
    await expect(api.admet(['CCO'], signal)).resolves.toEqual(admet);
    await expect(api.recognize('p/1', 'I/7', signal)).rejects.toThrow('契约');
    await expect(api.evidenceSummary(project.id, signal)).rejects.toThrow('契约');
    expect(String(transport.mock.calls[2]![0])).toBe(
      '/api/v1/projects/p%2F1/compounds/I%2F7/recognize',
    );
  });
});
