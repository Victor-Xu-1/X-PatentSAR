import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { observedStages } from '../src/model/extraction';
import { stageNames } from '../src/api/types';
import type { Job } from '../src/api/types';
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
};
const withAdmet: Job = {
  ...job,
  include_admet: true,
  admet_only: false,
  stages: job.stages.map((stage) => ({ ...stage, status: 'ok' })),
  admet_stage: phase,
};
describe('one slim observed job state with disclosed detail', () => {
  it('renders only the current state/progress until the user opens stage detail', () => {
    render(<StageStrip job={withAdmet} compact />);
    expect(screen.getByText(/ADMET · 进行中/)).toBeVisible();
    expect(document.querySelector('.stage-current')).toHaveTextContent('12 / 100');
    const list = screen.getByRole('list', { name: '真实提取流水线阶段', hidden: true });
    expect(list).not.toBeVisible();
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    expect(list).toBeVisible();
    expect(screen.getAllByRole('listitem')).toHaveLength(9);
    expect(screen.queryByText(/预计|\d+%|准确率\s*\d/)).not.toBeInTheDocument();
  });
  it('keeps eight core stages, appending only a real ADMET observation', () => {
    expect(stageNames).toHaveLength(8);
    expect(observedStages({ ...job, include_admet: true, admet_stage: null })).toHaveLength(8);
    expect(observedStages(withAdmet).map((stage) => stage.name)).toEqual([...stageNames, 'admet']);
    expect(observedStages({ ...withAdmet, include_admet: false })).toHaveLength(8);
  });
  it('does not borrow a stage or progress from unavailable/unknown history', () => {
    expect(observedStages({ ...withAdmet, history_available: false })).toEqual([]);
    expect(observedStages({ ...withAdmet, history_available: null })).toEqual([]);
    render(<StageStrip job={{ ...withAdmet, history_available: false }} compact />);
    expect(document.querySelector('.stage-current')).toBeVisible();
    expect(document.querySelector('.stage-current')).toHaveTextContent('历史阶段不可用');
    expect(screen.queryByText(/12 \/ 100/)).not.toBeInTheDocument();
  });
  it('shows an ADMET-only correction task without inventing core execution', () => {
    const only = { ...withAdmet, admet_only: true, stages: [] };
    expect(observedStages(only)).toEqual([phase]);
    render(<StageStrip job={only} compact />);
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.queryByText('文档分类')).not.toBeInTheDocument();
  });
  it('keeps stopped progress factual and does not continue its running animation', () => {
    const { container } = render(
      <StageStrip job={{ ...withAdmet, status: 'interrupted' }} compact />,
    );
    expect(screen.getByText(/ADMET · 停止时进行中/)).toBeVisible();
    expect(container.querySelector('.spin')).toBeNull();
    expect(document.querySelector('.stage-current')).toHaveTextContent('12 / 100');
  });
});
