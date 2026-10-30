import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import type { Job, PageSourcePhase } from '../src/api/types';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { StageObservation } from '../src/features/jobs/StageObservation';
import { setLocale } from '../src/i18n';
import { sourceProgressText } from '../src/model/sourceProgress';
import { stageProgressText } from '../src/model/extraction';
import { jobStageProgressText } from '../src/model/jobPresentation';
import { job } from './fixtures';

function current(phase: PageSourcePhase = 'page_ocr', completed = 7): Job {
  return decodeJob({
    ...job,
    status: 'running',
    history_available: true,
    stages: job.stages.map((stage) => ({
      ...stage,
      status: stage.name === 'classify' ? 'running' : 'pending',
      count: null,
      progress:
        stage.name === 'classify'
          ? {
              phase: null,
              source_phase: phase,
              completed,
              total: 13,
              cache_hits: phase === 'page_ocr' ? 2 : 0,
              failures: 0,
              device: null,
              peak_rss_mb: null,
            }
          : null,
    })),
  });
}

describe('observed classification work on the shared source channel', () => {
  it('uses the same bilingual source caption without changing scientific records', () => {
    const task = current();
    const stage = task.stages.find((stage) => stage.name === 'classify')!;
    const before = structuredClone(task);
    setLocale('en');
    expect(sourceProgressText(stage)).toBe('Reading original pages · 7 / 13 pages');
    expect(stageProgressText(stage)).toBe(sourceProgressText(stage));
    expect(jobStageProgressText(stage)).toBe(sourceProgressText(stage));
    setLocale('zh-CN');
    expect(sourceProgressText(stage)).toBe('读取原始页面 · 7 / 13 页');
    expect(task).toEqual(before);
  });

  it.each([
    ['page_ocr', 'Reading original pages'],
    ['empty_text_retry', 'Re-reading empty text observations'],
    ['page_classification', 'Classifying pages'],
  ] as const)('shows %s without converting complete work into acceptance', (phase, label) => {
    setLocale('en');
    const task = current(phase, 13);
    const stage = task.stages.find((stage) => stage.name === 'classify')!;
    const { container } = render(<StageStrip job={task} compact />);
    expect(container.querySelector('.stage-current')).toHaveTextContent(`${label} · 13 / 13 pages`);
    expect(container.querySelector('.stage-current')).toHaveClass('is-running');
    expect(task.status).toBe('running');
    expect(stage.count).toBeNull();
    expect(stage.status).toBe('running');
  });

  it('separates validated reused observations from checkpoint or chemistry acceptance', () => {
    setLocale('en');
    const task = current();
    const stage = task.stages.find((stage) => stage.name === 'classify')!;
    const { container } = render(<StageObservation job={task} stage={stage} name="classify" />);
    expect(container).toHaveTextContent('Reused 2 original page observations');
    expect(container).toHaveTextContent('does not certify complete extraction');
    expect(container).not.toHaveTextContent('chemical accuracy');
  });

  it.each([
    { source_phase: 'heading_sources' },
    { source_phase: 'page_ocr_custom' },
    { source_phase: true },
    { completed: '7' },
    { completed: 14 },
    { cache_hits: 8 },
    { phase: 'recognition' },
  ])('refuses malformed or foreign page work %j', (change) => {
    const task = current();
    expect(() =>
      decodeJob({
        ...task,
        stages: task.stages.map((stage) =>
          stage.name === 'classify'
            ? { ...stage, progress: { ...stage.progress, ...change } }
            : stage,
        ),
      }),
    ).toThrow();
  });

  it('does not let a page phase move to binding or another stage', () => {
    const task = current();
    for (const name of ['bind', 'smiles'] as const) {
      expect(() =>
        decodeJob({
          ...task,
          stages: task.stages.map((stage) =>
            stage.name === 'classify' ? { ...stage, name } : stage,
          ),
        }),
      ).toThrow();
    }
  });
});
