import { describe, expect, it } from 'vitest';
import { decodeCompound, decodeJob, decodeProject } from '../src/api/decoders';
import { safeAssetUrl } from '../src/api';
import { compound, job, project } from './fixtures';

const recognition = {
  status: 'valid',
  quality_flag: null,
  model_fingerprint: 'test-only-model-fingerprint',
  token_confidence: { minimum: 0.41, mean: 0.76 },
};
const progress = {
  completed: 12,
  total: 100,
  cache_hits: 3,
  failures: 1,
  device: 'cpu',
  peak_rss_mb: 256.5,
};

describe('additive result and job contracts, without inferred approval', () => {
  it('retains independent recognition and redraw evidence', () => {
    const redraw = '/api/v1/projects/project-contract/structures/I-7/redraw';
    expect(decodeCompound({ ...compound, recognition, redraw_image_url: redraw })).toMatchObject({
      recognition,
      redraw_image_url: redraw,
      review: null,
      smiles: null,
    });
  });
  it('keeps missing additive result fields explicitly unknown', () => {
    const {
      recognition: _recognition,
      redraw_image_url: _redraw,
      ...old
    } = {
      ...compound,
      recognition,
      redraw_image_url: null,
    };
    expect(decodeCompound(old)).toMatchObject({ recognition: null, redraw_image_url: null });
  });
  it('separates genuine manual statistics from binding needs_review', () => {
    expect(
      decodeProject({
        ...project,
        summary: {
          ...project.summary,
          needs_review: 0,
          manually_reviewed: 2,
          manual_review_pending: 98,
        },
      }),
    ).toMatchObject({
      summary: { needs_review: 0, manually_reviewed: 2, manual_review_pending: 98 },
    });
    expect(decodeProject(project)).toMatchObject({
      summary: { manually_reviewed: null, manual_review_pending: null },
    });
  });
  it.each(['not_run', 'valid', 'invalid', 'unavailable'])(
    'accepts the explicit recognition status %s',
    (status) =>
      expect(
        decodeCompound({ ...compound, recognition: { ...recognition, status } }),
      ).toMatchObject({ recognition: { status } }),
  );
  it.each([
    { ...recognition, status: 'approved' },
    { ...recognition, token_confidence: { minimum: -0.1, mean: 0.5 } },
    { ...recognition, token_confidence: { minimum: 0.2, mean: 1.1 } },
    { ...recognition, token_confidence: { minimum: 0.8, mean: 0.2 } },
    { ...recognition, token_confidence: { minimum: 0.2, mean: NaN } },
  ])('rejects malformed recognition rather than claiming quality', (value) => {
    expect(() => decodeCompound({ ...compound, recognition: value })).toThrow('契约');
  });
  it('retains actual progress, checkpoint reuse and history availability', () => {
    expect(
      decodeJob({
        ...job,
        history_available: true,
        stages: [{ ...job.stages[0], progress, reused_checkpoint: true }],
      }),
    ).toMatchObject({ history_available: true, stages: [{ progress, reused_checkpoint: true }] });
    expect(decodeJob({ ...job, history_available: false })).toMatchObject({
      history_available: false,
    });
    expect(decodeJob({ ...job, history_available: undefined })).toMatchObject({
      history_available: null,
      stages: job.stages.map(() => ({ progress: null, reused_checkpoint: null })),
    });
  });
  it.each(['manually_reviewed', 'manual_review_pending'])(
    'rejects invalid manual counter %s without defaulting to zero',
    (field) => {
      for (const value of [-1, 0.5, '0']) {
        expect(() =>
          decodeProject({ ...project, summary: { ...project.summary, [field]: value } }),
        ).toThrow('契约');
      }
    },
  );
  it.each([
    { ...progress, completed: 101 },
    { ...progress, completed: -1 },
    { ...progress, total: 1.5 },
    { ...progress, cache_hits: -1 },
    { ...progress, failures: 0.5 },
    { ...progress, peak_rss_mb: -1 },
    { ...progress, device: 'auto' },
  ])('rejects malformed stage progress', (value) => {
    expect(() => decodeJob({ ...job, stages: [{ ...job.stages[0], progress: value }] })).toThrow(
      '契约',
    );
  });
  it('permits only contract-shaped same-origin redraw assets', () => {
    expect(safeAssetUrl('/api/v1/projects/project-contract/structures/I-7/redraw')).toBe(
      '/api/v1/projects/project-contract/structures/I-7/redraw',
    );
    expect(
      safeAssetUrl(
        '/api/v1/projects/project-contract/structures/I-7/redraw?digest=run-two-content',
      ),
    ).toBe('/api/v1/projects/project-contract/structures/I-7/redraw?digest=run-two-content');
    for (const value of [
      'https://outside.invalid/api/v1/projects/p/structures/I-7/redraw',
      '/api/v1/runtime/redraw',
      'data:image/png;base64,test',
      '/api/v1/projects/p/structures/I-7/redraw/../../runtime',
    ]) {
      expect(safeAssetUrl(value)).toBeNull();
    }
  });
});
