import { describe, expect, it } from 'vitest';
import { decodeCompound, decodeJob } from '../src/api/decoders';
import { stageNames } from '../src/api/types';
import { compound, job } from './fixtures';
import { descriptorSummary, incompleteDescriptors } from './descriptor-fixtures';

const sourceOrder = [
  'classify',
  'locate',
  'structures',
  'bind',
  'activity',
  'smiles',
  'final',
  'qa',
];
const resourceWait = {
  reason: 'memory',
  required_mb: 2048,
  available_mb: 512.5,
  waited_seconds: 12.5,
};

describe('optional producer-owned stage order and resource observations', () => {
  it('preserves supplied source-first and other complete orders without changing the legacy default', () => {
    for (const stage_order of [sourceOrder, [...stageNames].reverse()])
      expect(decodeJob({ ...job, stage_order })).toHaveProperty('stage_order', stage_order);
    expect(decodeJob(job)).not.toHaveProperty('stage_order');
    expect(decodeJob({ ...job, stage_order: null })).toHaveProperty('stage_order', null);
    expect(stageNames[1]).toBe('activity');
  });
  it('allows an explicitly empty core order only for the existing ADMET-only carrier', () => {
    const only = { ...job, include_admet: true, admet_only: true, stages: [], stage_order: [] };
    expect(decodeJob(only)).toEqual(only);
    expect(() => decodeJob({ ...only, stage_order: sourceOrder })).toThrow('契约');
    expect(() => decodeJob({ ...job, stage_order: [] })).toThrow('契约');
  });
  it.each(
    [
      sourceOrder.slice(0, -1),
      [...sourceOrder, 'admet'],
      [...sourceOrder.slice(0, -1), 'classify'],
      [...sourceOrder.slice(0, -1), 'unknown'],
      'classify,locate',
      {},
    ].map((stage_order) => ({ stage_order })),
  )('rejects an incomplete, duplicate or invented core order %j', ({ stage_order }) => {
    expect(() => decodeJob({ ...job, stage_order })).toThrow('契约');
  });
  it('preserves actual core/research wait observations and conservative omitted/null fields', () => {
    const stages = [{ ...job.stages[0], resource_wait: resourceWait }];
    expect(decodeJob({ ...job, stages }).stages).toEqual(stages);
    const admet_stage = { ...stages[0], name: 'admet' };
    expect(decodeJob({ ...job, include_admet: true, admet_stage }).admet_stage).toEqual(
      admet_stage,
    );
    expect(decodeJob(job).stages[0]).not.toHaveProperty('resource_wait');
    const absent = [{ ...job.stages[0], resource_wait: null }];
    expect(decodeJob({ ...job, stages: absent }).stages).toEqual(absent);
  });
  it.each(['required_mb', 'available_mb', 'waited_seconds'])(
    'rejects nonfinite, negative, nonnumeric or unsafe %s measurements',
    (key) => {
      for (const value of [-1, NaN, Infinity, '2048', Number.MAX_SAFE_INTEGER + 1])
        expect(() =>
          decodeJob({
            ...job,
            stages: [{ ...job.stages[0], resource_wait: { ...resourceWait, [key]: value } }],
          }),
        ).toThrow('契约');
    },
  );
  it('rejects unknown wait reasons and missing measurements, retaining observed zeroes', () => {
    for (const resource_wait of [{ ...resourceWait, reason: 'gpu' }, { reason: 'memory' }])
      expect(() => decodeJob({ ...job, stages: [{ ...job.stages[0], resource_wait }] })).toThrow(
        '契约',
      );
    const zero = { reason: 'memory', required_mb: 0, available_mb: 0, waited_seconds: 0 };
    expect(
      decodeJob({ ...job, stages: [{ ...job.stages[0], resource_wait: zero }] }).stages[0],
    ).toHaveProperty('resource_wait', zero);
  });
});

describe('independent source-bound RDKit descriptor contract', () => {
  it('retains exactly five calculated metrics and original evidence without synthesizing ADMET', () => {
    const payload = { ...compound, descriptors: descriptorSummary };
    expect(decodeCompound(payload)).toEqual(payload);
    expect(decodeCompound(payload)).not.toHaveProperty('admet');
    expect(decodeCompound(compound)).toEqual(compound);
    expect(decodeCompound({ ...compound, descriptors: null })).toHaveProperty('descriptors', null);
  });
  it.each(['not_run', 'pending', 'running', 'failed', 'stale', 'unavailable'])(
    'retains %s without any numeric observations',
    (status) => {
      const descriptors = incompleteDescriptors(status);
      expect(decodeCompound({ ...compound, descriptors })).toHaveProperty(
        'descriptors',
        descriptors,
      );
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...descriptorSummary, status } }),
      ).toThrow('契约');
    },
  );
  it('rejects incomplete, duplicated, reordered, extra and prediction metrics', () => {
    for (const properties of [
      descriptorSummary.properties.slice(0, 4),
      [...descriptorSummary.properties].reverse(),
      [...descriptorSummary.properties.slice(0, 4), descriptorSummary.properties[0]],
      [...descriptorSummary.properties, descriptorSummary.properties[0]],
      [
        ...descriptorSummary.properties.slice(0, 4),
        {
          key: 'Solubility_AqSolDB',
          label: 'LogS',
          unit: 'log(mol/L)',
          kind: 'prediction',
          value: -3,
        },
      ],
    ])
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...descriptorSummary, properties } }),
      ).toThrow('契约');
  });
  it.each(['source_fingerprint', 'smiles_sha256', 'engine', 'generated_at', 'job_id'])(
    'requires completed producer provenance %s',
    (key) => {
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...descriptorSummary, [key]: null } }),
      ).toThrow('契约');
    },
  );
  it('rejects a completed descriptor with a retained error and incomplete producer evidence', () => {
    expect(() =>
      decodeCompound({
        ...compound,
        descriptors: {
          ...descriptorSummary,
          error: { code: 'failed', message: 'Not complete' },
        },
      }),
    ).toThrow('契约');
    for (const status of ['not_run', 'pending', 'running', 'failed', 'stale', 'unavailable']) {
      const descriptors = incompleteDescriptors(status);
      for (const extra of [
        { engine: descriptorSummary.engine },
        { generated_at: descriptorSummary.generated_at },
      ])
        expect(() =>
          decodeCompound({ ...compound, descriptors: { ...descriptors, ...extra } }),
        ).toThrow('契约');
    }
    expect(() =>
      decodeCompound({
        ...compound,
        descriptors: { ...incompleteDescriptors('failed'), error: null },
      }),
    ).toThrow('契约');
    for (const status of ['pending', 'running'])
      for (const key of ['source_fingerprint', 'smiles_sha256', 'job_id'])
        expect(() =>
          decodeCompound({
            ...compound,
            descriptors: { ...incompleteDescriptors(status), [key]: null },
          }),
        ).toThrow('契约');
  });
  it('bounds descriptor producer error text independently from legacy ADMET', () => {
    for (const error of [
      { code: 'x'.repeat(101), message: 'failure' },
      { code: 'failed', message: 'x'.repeat(2001) },
    ])
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...incompleteDescriptors('failed'), error } }),
      ).toThrow('契约');
  });
  it('rejects invented engines, malformed provenance, wrong metric metadata and invalid values', () => {
    for (const invalid of [
      { source_fingerprint: 'unverified' },
      { smiles_sha256: '2'.repeat(63) },
      { job_id: 'job' },
      { review_only: false },
      { engine: { ...descriptorSummary.engine, name: 'ADMET-AI' } },
      { engine: { ...descriptorSummary.engine, version: '' } },
      { engine: { ...descriptorSummary.engine, algorithm_sha256: 'bad' } },
    ])
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...descriptorSummary, ...invalid } }),
      ).toThrow('契约');
    for (const metric of [
      { ...descriptorSummary.properties[0]!, value: NaN },
      { ...descriptorSummary.properties[0]!, value: -1 },
      { ...descriptorSummary.properties[0]!, unit: 'g/mol' },
      { ...descriptorSummary.properties[0]!, kind: 'prediction' },
      { ...descriptorSummary.properties[3]!, value: 0.5 },
    ]) {
      const properties: unknown[] = [...descriptorSummary.properties];
      properties[metric.key === 'hydrogen_bond_donors' ? 3 : 0] = metric;
      expect(() =>
        decodeCompound({ ...compound, descriptors: { ...descriptorSummary, properties } }),
      ).toThrow('契约');
    }
  });
});
