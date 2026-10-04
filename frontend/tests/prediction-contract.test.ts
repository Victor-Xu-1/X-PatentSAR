import { describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { decodeCompound, decodeJob, decodeProject } from '../src/api/decoders';
import { decodePredictionMetric, decodePredictionSummary } from '../src/api/predictionDecoders';
import { METRIC_KEYS, METRIC_SPECS } from '../src/api/predictionTypes';
import { compound, job, project } from './fixtures';

const complete = {
  status: 'complete',
  properties: METRIC_SPECS.map((spec, index) => ({
    ...spec,
    value: [46.069, -0.1, 20.23, 1, 1, -3.2][index]!,
  })),
  source_fingerprint: '1'.repeat(64),
  smiles_sha256: '2'.repeat(64),
  engine: { name: 'ADMET-AI', version: '2.0.1', model_sha256: '3'.repeat(64) },
  generated_at: '2026-10-03T12:00:00Z',
  job_id: '4'.repeat(32),
  warnings: [],
  error: null,
  review_only: true,
};
const admetStage = {
  name: 'admet',
  status: 'running',
  count: 12,
  duration_seconds: 3,
  progress: {
    completed: 12,
    total: 100,
    cache_hits: 2,
    failures: 1,
    device: null,
    peak_rss_mb: null,
  },
  reused_checkpoint: false,
};

describe('six source-bound ADMET metrics', () => {
  it('keeps the ordered labels/units and preserves legitimate negative logarithms', () => {
    const result = decodePredictionSummary(complete);
    expect(result).toEqual(complete);
    expect(result.properties.map((metric) => metric.key)).toEqual(METRIC_KEYS);
    expect(result.properties.map((metric) => metric.label)).toEqual([
      'MW',
      'LogP',
      'TPSA',
      'HBD',
      'HBA',
      'LogS',
    ]);
    expect(result.properties.map((metric) => metric.unit)).toEqual([
      'Dalton',
      'log-ratio',
      'Å^2',
      '#',
      '#',
      'log(mol/L)',
    ]);
    expect(result.properties[5]?.value).toBe(-3.2);
  });
  it.each(['not_run', 'pending', 'running', 'failed', 'stale', 'unavailable'])(
    'shows no values for %s',
    (status) => {
      const empty = { ...complete, status, properties: [] };
      expect(decodePredictionSummary(empty).properties).toEqual([]);
      expect(() => decodePredictionSummary({ ...complete, status })).toThrow('契约');
    },
  );
  it('rejects missing, duplicated, reordered or additional observations', () => {
    for (const properties of [
      complete.properties.slice(0, 5),
      [...complete.properties, complete.properties[0]],
      [...complete.properties.slice(0, 5), complete.properties[0]],
      [...complete.properties].reverse(),
    ])
      expect(() => decodePredictionSummary({ ...complete, properties })).toThrow('契约');
  });
  it.each(['source_fingerprint', 'smiles_sha256', 'engine', 'generated_at'])(
    'requires provenance %s on completion',
    (key) => {
      expect(() => decodePredictionSummary({ ...complete, [key]: null })).toThrow('契约');
    },
  );
  it('rejects invalid fingerprints, engine identity and non-review-only output', () => {
    expect(() =>
      decodePredictionSummary({ ...complete, source_fingerprint: 'unverified' }),
    ).toThrow('契约');
    expect(() => decodePredictionSummary({ ...complete, smiles_sha256: '2'.repeat(63) })).toThrow(
      '契约',
    );
    expect(() =>
      decodePredictionSummary({ ...complete, engine: { ...complete.engine, model_sha256: 'bad' } }),
    ).toThrow('契约');
    expect(() =>
      decodePredictionSummary({ ...complete, engine: { ...complete.engine, version: '' } }),
    ).toThrow('契约');
    expect(() => decodePredictionSummary({ ...complete, review_only: false })).toThrow('契约');
  });
  it('never guesses metric units or kinds, clamps values, or accepts invalid counts', () => {
    const metric = complete.properties[0]!;
    for (const invalid of [
      { unit: 'g/mol' },
      { kind: 'prediction' },
      { label: 'Weight' },
      { value: NaN },
      { value: Infinity },
      { value: -1 },
    ])
      expect(() => decodePredictionMetric({ ...metric, ...invalid })).toThrow('契约');
    expect(() => decodePredictionMetric({ ...complete.properties[3], value: 0.5 })).toThrow('契约');
    expect(() =>
      decodePredictionMetric({ ...complete.properties[4], value: Number.MAX_SAFE_INTEGER + 1 }),
    ).toThrow('契约');
  });
  it('decodes additive correction/prediction metadata without upgrading binding evidence', () => {
    const correction = {
      revision: 2,
      stale: true,
      has_changes: true,
      updated_at: complete.generated_at,
    };
    const row = decodeCompound({ ...compound, admet: complete, correction });
    expect(row.admet?.status).toBe('complete');
    expect(row.correction).toEqual(correction);
    expect(row.confidence).toEqual(compound.confidence);
    expect(row.flags).toEqual(compound.flags);
    expect(() =>
      decodeCompound({ ...compound, correction: { ...correction, revision: 0 } }),
    ).toThrow('契约');
    expect(decodeCompound(compound)).toEqual(compound);
  });
});

describe('additive project/job contracts and automatic queue requests', () => {
  it('accepts a bounded first structure page and retains unknown as null or absent', () => {
    expect(decodeProject({ ...project, first_structure_page: 4 }).first_structure_page).toBe(4);
    expect(
      decodeProject({ ...project, first_structure_page: null }).first_structure_page,
    ).toBeNull();
    expect(decodeProject(project)).toEqual(project);
    for (const first_structure_page of [0, -1, 1.2, 13, Infinity, '4'])
      expect(() => decodeProject({ ...project, first_structure_page })).toThrow('契约');
  });
  it('keeps the actual separate ADMET stage while rejecting a ninth core stage', () => {
    const payload = { ...job, include_admet: true, admet_only: false, admet_stage: admetStage };
    expect(decodeJob(payload)).toEqual(payload);
    expect(() => decodeJob({ ...payload, stages: [...job.stages, admetStage] })).toThrow('契约');
    expect(() => decodeJob({ ...payload, admet_stage: { ...admetStage, name: 'qa' } })).toThrow(
      '契约',
    );
    expect(() => decodeJob({ ...payload, include_admet: false })).toThrow('契约');
    expect(() => decodeJob({ ...payload, admet_only: true })).toThrow('契约');
    expect(decodeJob({ ...payload, admet_only: true, stages: [] }).stages).toEqual([]);
    expect(decodeJob(job)).toEqual(job);
  });
  it('checks observed counter consistency for the separate stage', () => {
    for (const progress of [
      { ...admetStage.progress, cache_hits: 13 },
      { ...admetStage.progress, failures: 13 },
      { ...admetStage.progress, completed: 101 },
    ])
      expect(() =>
        decodeJob({ ...job, include_admet: true, admet_stage: { ...admetStage, progress } }),
      ).toThrow('契约');
  });
  it.each(['recognition', 'properties', null])(
    'preserves the optional progress phase %s',
    (phase) => {
      const payload = {
        ...job,
        include_admet: true,
        admet_only: true,
        stages: [],
        admet_stage: { ...admetStage, progress: { ...admetStage.progress, phase } },
      };
      expect(decodeJob(payload)).toEqual(payload);
      expect(
        decodeJob({ ...payload, admet_stage: admetStage }).admet_stage?.progress,
      ).not.toHaveProperty('phase');
    },
  );
  it.each(['', 'admet', 'structures', false, 1, {}, []].map((phase) => ({ phase })))(
    'rejects an unknown progress phase $phase',
    ({ phase }) => {
      expect(() =>
        decodeJob({
          ...job,
          include_admet: true,
          admet_stage: { ...admetStage, progress: { ...admetStage.progress, phase } },
        }),
      ).toThrow('admet_stage.progress.phase');
    },
  );
  it('adds automatic ADMET to new requests without weakening QA or invoking paid advice', async () => {
    const mutate = vi.spyOn(client, 'mutate').mockResolvedValue(job);
    await api.createJob(project.id);
    expect(mutate).toHaveBeenCalledWith(
      `/projects/${project.id}/jobs`,
      'POST',
      {
        include_admet: true,
        allow_partial: false,
        advisory: false,
        resume_job_id: null,
      },
      expect.any(Function),
    );
    await api.createJob(project.id, null, { admet_only: true });
    expect(mutate.mock.calls[1]?.[2]).toMatchObject({ include_admet: true, admet_only: true });
  });
  it('leaves resume flags with the original persisted job, ignoring new automatic/force options', async () => {
    const mutate = vi.spyOn(client, 'mutate').mockResolvedValue(job);
    await api.createJob(project.id, job.id, { include_admet: true, admet_only: true, force: true });
    expect(mutate.mock.calls[0]?.[2]).toEqual({
      allow_partial: false,
      advisory: false,
      resume_job_id: job.id,
    });
  });
});
