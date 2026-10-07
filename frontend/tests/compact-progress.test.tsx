import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { observedStages } from '../src/model/extraction';
import { stageLabels } from '../src/model/presentation';
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
  it.each(stageNames)(
    'keeps an interrupted upstream %s visible instead of an unstarted terminal ADMET failure',
    (name) => {
      const currentIndex = stageNames.indexOf(name);
      const interrupted: Job = {
        ...withAdmet,
        status: 'interrupted',
        stages: job.stages.map((stage, index) => ({
          ...stage,
          status: index < currentIndex ? 'ok' : index === currentIndex ? 'running' : 'pending',
        })),
        admet_stage: {
          name: 'admet',
          status: 'failed',
          count: null,
          duration_seconds: null,
          progress: null,
          reused_checkpoint: null,
        },
      };
      const { container, rerender } = render(<StageStrip job={interrupted} compact />);
      expect(document.querySelector('.stage-current')).toHaveTextContent(
        `${stageLabels[name]} · 停止时进行中`,
      );
      expect(observedStages(interrupted)).toHaveLength(8);
      expect(container.querySelector('.stage:last-child')).toHaveTextContent('ADMET / 指标未执行');
      expect(container.querySelector('.stage:last-child')).not.toHaveClass('failed');
      expect(container.querySelector('.spin')).toBeNull();
      fireEvent.click(screen.getByLabelText('提取阶段详情'));
      expect(screen.getAllByRole('listitem')).toHaveLength(9);

      const failed: Job = {
        ...interrupted,
        status: 'failed',
        stages: interrupted.stages.map((stage) =>
          stage.name === name ? { ...stage, status: 'failed' } : stage,
        ),
      };
      rerender(<StageStrip job={failed} compact />);
      expect(document.querySelector('.stage-current')).toHaveTextContent(
        `${stageLabels[name]} · 失败`,
      );
      expect(container.querySelector('.stage:last-child')).not.toHaveClass('failed');
    },
  );
  it.each(['pending', 'failed'] as const)(
    'does not expose unstarted ADMET %s while upstream work is incomplete',
    (status) => {
      const current: Job = {
        ...withAdmet,
        stages: job.stages,
        admet_stage: { ...phase, status, count: null, duration_seconds: null, progress: null },
      };
      expect(observedStages(current)).toEqual(job.stages);
      render(<StageStrip job={current} compact />);
      expect(document.querySelector('.stage-current')).toHaveTextContent('文档解析 · 进行中');
      expect(document.querySelector('.stage:last-child')).toHaveTextContent('ADMET / 指标等待');
      expect(document.querySelector('.stage:last-child')).not.toHaveClass('failed');
    },
  );
  it.each(['pending', 'failed'] as const)(
    'shows ADMET %s after all core stages complete even without model progress',
    (status) => {
      const current: Job = {
        ...withAdmet,
        status: status === 'failed' ? 'failed' : 'running',
        admet_stage: { ...phase, status, count: null, duration_seconds: null, progress: null },
      };
      expect(observedStages(current)).toHaveLength(9);
      render(<StageStrip job={current} compact />);
      expect(document.querySelector('.stage-current')).toHaveTextContent(
        status === 'failed' ? 'ADMET / 指标 · 失败' : 'ADMET / 指标 · 等待',
      );
    },
  );
  it.each([
    { count: 0 },
    { duration_seconds: 0 },
    { progress: { ...phase.progress!, completed: 0 } },
  ])('retains an actually started failed ADMET observation: %j', (observation) => {
    const current: Job = {
      ...withAdmet,
      status: 'interrupted',
      stages: [],
      admet_stage: {
        ...phase,
        status: 'failed',
        count: null,
        duration_seconds: null,
        progress: null,
        ...observation,
      },
    };
    expect(observedStages(current)).toEqual([current.admet_stage]);
    render(<StageStrip job={current} compact />);
    expect(document.querySelector('.stage-current')).toHaveTextContent('ADMET / 指标 · 失败');
  });
  it('does not infer completed core work from a partial successful stage list', () => {
    const current: Job = {
      ...withAdmet,
      stages: withAdmet.stages.slice(0, -1),
      admet_stage: {
        ...phase,
        status: 'failed',
        count: null,
        duration_seconds: null,
        progress: null,
      },
    };
    expect(observedStages(current)).toEqual(current.stages);
  });
  it('renders only the current state/progress until the user opens stage detail', () => {
    render(<StageStrip job={withAdmet} compact />);
    expect(screen.getByText(/ADMET \/ 指标 · 进行中/)).toBeVisible();
    expect(document.querySelector('.stage-current')).toHaveTextContent('12 / 100');
    const list = screen.getByRole('list', { name: '任务运行链路', hidden: true });
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
    expect(screen.queryByText('文档解析')).not.toBeInTheDocument();
  });
  it('keeps stopped progress factual and does not continue its running animation', () => {
    const { container } = render(
      <StageStrip job={{ ...withAdmet, status: 'interrupted' }} compact />,
    );
    expect(screen.getByText(/ADMET \/ 指标 · 停止时进行中/)).toBeVisible();
    expect(container.querySelector('.spin')).toBeNull();
    expect(document.querySelector('.stage-current')).toHaveTextContent('12 / 100');
  });
  it('labels the same ADMET stage by phase and uses the new observed workload after transition', () => {
    const recognition: Job = {
      ...withAdmet,
      admet_only: true,
      stages: [],
      admet_stage: {
        ...phase,
        progress: { ...phase.progress!, phase: 'recognition' },
      },
    };
    const { rerender } = render(<StageStrip job={recognition} compact />);
    expect(document.querySelector('.stage-current')).toHaveTextContent(
      '结构补齐 · 进行中 · 12 / 100',
    );
    expect(screen.getByText('缓存命中 2 · 失败 1')).not.toBeVisible();
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    fireEvent.click(screen.getByText('结构补齐').closest('summary')!);
    expect(screen.getByText('缓存命中 2 · 失败 1')).toBeVisible();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);

    const properties: Job = {
      ...recognition,
      admet_stage: {
        ...phase,
        progress: {
          ...phase.progress!,
          phase: 'properties',
          completed: 0,
          total: 7,
          cache_hits: 0,
          failures: 0,
        },
      },
    };
    rerender(<StageStrip job={properties} compact />);
    expect(document.querySelector('.stage-current')).toHaveTextContent('指标计算 · 进行中 · 0 / 7');
    expect(screen.getByText('缓存命中 0 · 失败 0')).toBeVisible();
    expect(screen.queryByText('结构补齐')).not.toBeInTheDocument();
    expect(screen.queryByText(/12 \/ 100/)).not.toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });
  it.each([null, undefined])('keeps the legacy ADMET label when phase is %s', (value) => {
    render(
      <StageStrip
        job={{
          ...withAdmet,
          admet_stage: {
            ...phase,
            progress: { ...phase.progress!, ...(value === null ? { phase: null } : {}) },
          },
        }}
        compact
      />,
    );
    expect(document.querySelector('.stage-current')).toHaveTextContent(
      'ADMET / 指标 · 进行中 · 12 / 100',
    );
  });
  it('keeps a failed recognition phase explicit without a running animation', () => {
    const { container } = render(
      <StageStrip
        job={{
          ...withAdmet,
          status: 'failed',
          admet_stage: {
            ...phase,
            status: 'failed',
            progress: { ...phase.progress!, phase: 'recognition' },
          },
        }}
        compact
      />,
    );
    expect(document.querySelector('.stage-current')).toHaveTextContent(
      '结构补齐 · 失败 · 已处理 12 / 100',
    );
    expect(container.querySelector('.spin')).toBeNull();
  });
});
