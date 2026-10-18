import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import type { BindingSourcePhase, Job } from '../src/api/types';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { setLocale } from '../src/i18n';
import { bindingProgressText } from '../src/model/bindingProgress';
import { stageProgressText } from '../src/model/extraction';
import { jobStageProgressText } from '../src/model/jobPresentation';
import { job } from './fixtures';

function current(phase: BindingSourcePhase = 'caption_sources', completed = 2): Job {
  return decodeJob({
    ...job,
    status: 'running',
    history_available: true,
    stages: job.stages.map((stage) => ({
      ...stage,
      status:
        stage.name === 'bind'
          ? 'running'
          : ['classify', 'locate', 'structures'].includes(stage.name)
            ? 'ok'
            : 'pending',
      progress:
        stage.name === 'bind'
          ? {
              phase: null,
              source_phase: phase,
              completed,
              total: 7,
              cache_hits: 0,
              failures: 0,
              device: null,
              peak_rss_mb: null,
            }
          : null,
    })),
  });
}

describe('recorded binding source work without acceptance or extra requests', () => {
  it('uses one bilingual source caption in both existing task presentations', () => {
    const task = current();
    const stage = task.stages.find((stage) => stage.name === 'bind')!;
    const before = structuredClone(task);
    setLocale('en');
    expect(bindingProgressText(stage)).toBe('Checking captions · 2 / 7 pages');
    expect(stageProgressText(stage)).toBe(bindingProgressText(stage));
    expect(jobStageProgressText(stage)).toBe(bindingProgressText(stage));
    setLocale('zh-CN');
    expect(bindingProgressText(stage)).toBe('核对图注 · 2 / 7 页');
    expect(task).toEqual(before);
  });

  it('keeps finished source work distinct from complete extraction and molecules', () => {
    setLocale('en');
    const task = current('heading_bindings', 7);
    const stage = task.stages.find((stage) => stage.name === 'bind')!;
    expect(bindingProgressText(stage)).toBe('Checking identifier ownership · 7 / 7 items');
    const { container } = render(<StageStrip job={task} compact />);
    expect(container.querySelector('.stage-current')).toHaveClass('is-running');
    expect(container.querySelector('.stage-current')).not.toHaveClass('is-complete');
    expect(container.querySelector('.stage-current')).toHaveTextContent('7 / 7 items');
    expect(container.querySelector('.stage-current')).not.toHaveTextContent('Identifier binding');
    expect(container.querySelector('.stage-current')).toHaveAttribute(
      'title',
      expect.stringContaining('Identifier binding'),
    );
    expect(task.status).toBe('running');
    expect(stage.status).toBe('running');
    expect(stage.count).toBeNull();
  });

  it('preserves old telemetry without extending its existing phase enum', () => {
    const task = current();
    const stage = task.stages.find((stage) => stage.name === 'bind')!;
    expect(bindingProgressText({ ...stage, progress: null })).toBeNull();
    expect(
      bindingProgressText({ ...stage, progress: { ...stage.progress!, source_phase: null } }),
    ).toBeNull();
    expect(bindingProgressText({ ...stage, name: 'smiles' })).toBeNull();
    expect(() => decodeJob(job)).not.toThrow();
  });

  it.each([
    { source_phase: 'lead' },
    { source_phase: true },
    { source_phase: 'heading_sources', phase: 'recognition' },
    { completed: true },
    { completed: 8 },
  ])('rejects malformed or mixed source observations %j', (changes) => {
    const task = current();
    expect(() =>
      decodeJob({
        ...task,
        stages: task.stages.map((stage) =>
          stage.name === 'bind' ? { ...stage, progress: { ...stage.progress, ...changes } } : stage,
        ),
      }),
    ).toThrow();
  });

  it('rejects a binding source phase attached to another stage', () => {
    const task = current();
    expect(() =>
      decodeJob({
        ...task,
        stages: task.stages.map((stage) =>
          stage.name === 'bind' ? { ...stage, name: 'smiles' } : stage,
        ),
      }),
    ).toThrow();
  });
});
