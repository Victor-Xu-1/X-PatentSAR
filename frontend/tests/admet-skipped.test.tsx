import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import type { Job } from '../src/api/types';
import { StageObservation } from '../src/features/jobs/StageObservation';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { job } from './fixtures';

const phase: NonNullable<Job['admet_stage']> = {
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
  skipped: 185,
};
const only: Job = {
  ...job,
  include_admet: true,
  admet_only: true,
  stages: [],
  admet_stage: phase,
};

describe('eligible ADMET workload and explicitly skipped records', () => {
  it('preserves skipped independently of eligible progress totals', () => {
    const decoded = decodeJob(only);
    expect(decoded.admet_stage?.skipped).toBe(185);
    expect(decoded.admet_stage?.progress).toEqual(phase.progress);
  });

  it.each([null, -1, 1.5, NaN, Infinity, true, '185', 1_000_001])(
    'rejects invalid skipped count %s in core or research stages',
    (skipped) => {
      expect(() => decodeJob({ ...only, admet_stage: { ...phase, skipped } })).toThrow('契约');
      expect(() => decodeJob({ ...job, stages: [{ ...job.stages[0]!, skipped }] })).toThrow('契约');
    },
  );

  it('does not invent skipped counts for older stages, retaining real zero when provided', () => {
    expect(decodeJob(job).stages[0]).not.toHaveProperty('skipped');
    expect(decodeJob({ ...only, admet_stage: { ...phase, skipped: 0 } }).admet_stage?.skipped).toBe(
      0,
    );
  });

  it('keeps skipped detail out of the compact workbench until explicitly expanded', () => {
    render(<StageStrip job={only} compact />);
    const detail = screen.getByText('未计算 185（缺少有效SMILES）');
    expect(detail).not.toBeVisible();
    expect(document.querySelector('.stage-current')).toHaveTextContent('12 / 100');
    expect(document.querySelector('.stage-current')).not.toHaveTextContent('185');
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    const summary = screen.getByText('ADMET').closest('summary')!;
    fireEvent.click(summary);
    expect(detail).toBeVisible();
    expect(screen.queryByText(/12 \/ 285/)).not.toBeInTheDocument();
  });

  it('supports observed empty eligible workload while preserving skipped records', () => {
    const empty = {
      ...phase,
      status: 'empty' as const,
      count: 0,
      progress: { ...phase.progress!, completed: 0, total: 0, cache_hits: 0, failures: 0 },
    };
    expect(decodeJob({ ...only, admet_stage: empty }).admet_stage).toEqual(empty);
    render(<StageObservation job={only} name="admet" stage={empty} />);
    const summary = screen.getByText('ADMET').closest('summary')!;
    fireEvent.click(summary);
    expect(screen.getByText('未计算 185（缺少有效SMILES）')).toBeVisible();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('keeps an empty ADMET attempt explicit without a 0/0 fraction in the main toolbar', () => {
    render(
      <StageStrip
        job={{
          ...only,
          status: 'complete',
          admet_stage: {
            ...phase,
            status: 'empty',
            count: 0,
            progress: { ...phase.progress!, completed: 0, total: 0, cache_hits: 0, failures: 0 },
          },
        }}
        compact
      />,
    );
    expect(document.querySelector('.stage-current')).toHaveTextContent('ADMET · 未计算');
    expect(document.querySelector('.stage-current')).not.toHaveTextContent('0 / 0');
    expect(screen.getByText('未计算 185（缺少有效SMILES）')).not.toBeVisible();
  });

  it('does not add a permanent zero or guessed skipped note when no record was skipped', () => {
    render(<StageObservation job={only} name="admet" stage={{ ...phase, skipped: 0 }} />);
    fireEvent.click(screen.getByText('ADMET').closest('summary')!);
    expect(screen.queryByText(/未计算 \d+/)).not.toBeInTheDocument();
  });

  it('does not expose untrusted stage observations when attempt history is unavailable', () => {
    render(<StageStrip job={{ ...only, history_available: false }} compact />);
    const line = screen.getByLabelText('提取阶段详情');
    expect(within(line).queryByText(/185|12 \/ 100/)).not.toBeInTheDocument();
    expect(screen.queryByText(/未计算 \d+/)).not.toBeInTheDocument();
  });
});
