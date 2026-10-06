import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { JobActions } from '../src/features/jobs/JobActions';
import { ExtractionNotice } from '../src/features/results/ExtractionNotice';
import type { Job } from '../src/api/types';
import { stageNames } from '../src/api/types';
import { job, project } from './fixtures';

const labels = [
  '文档解析',
  '活性提取',
  '结构定位',
  '结构分割',
  '编号绑定',
  'SMILES 识别',
  '生成结果',
  '核心校验',
  'ADMET / 指标',
];
const full: Job = { ...job, history_available: true, include_admet: true, admet_stage: null };
function openStages(current: Job) {
  render(<StageStrip job={current} compact />);
  fireEvent.click(screen.getByLabelText('提取阶段详情'));
  return screen.getAllByRole('listitem');
}

describe('actual core then source-completion/six-property task chain', () => {
  it('uses the supplied source-first order, then the existing configured research slot', () => {
    const stage_order = [
      'classify',
      'locate',
      'structures',
      'bind',
      'activity',
      'smiles',
      'final',
      'qa',
    ];
    const current = decodeJob({ ...full, stage_order });
    const stages = openStages(current);
    expect(stages.map((stage) => stage.querySelector('strong')?.textContent)).toEqual([
      '文档解析',
      '结构定位',
      '结构分割',
      '编号绑定',
      '活性提取',
      'SMILES 识别',
      '生成结果',
      '核心校验',
      'ADMET / 指标',
    ]);
    expect(current.admet_stage).toBeNull();
    expect(screen.queryByText(/0 \/ 0|缓存命中/)).not.toBeInTheDocument();
  });
  it('chooses the next supplied slot for the compact caption without creating producer facts', () => {
    const stage_order = [
      'classify',
      'locate',
      'structures',
      'bind',
      'activity',
      'smiles',
      'final',
      'qa',
    ];
    const current = decodeJob({
      ...full,
      stage_order,
      stages: full.stages.map((stage) => ({
        ...stage,
        status: stage.name === 'classify' ? 'ok' : 'pending',
      })),
    });
    openStages(current);
    expect(document.querySelector('.stage-current')).toHaveTextContent('结构定位 · 等待');
    expect(screen.queryByText(/0 \/ 0|缓存命中/)).not.toBeInTheDocument();
  });
  it('honors another actual supplied order rather than hardcoding a new frontend pipeline', () => {
    const current = decodeJob({
      ...full,
      stage_order: [...stageNames].reverse(),
      include_admet: false,
    });
    const stages = openStages(current);
    expect(stages.map((stage) => stage.querySelector('strong')?.textContent)).toEqual(
      labels.slice(0, 8).reverse(),
    );
  });
  it('keeps rejected core acceptance failed when independent research has completed', () => {
    const current: Job = {
      ...full,
      status: 'failed',
      error: { code: 'core_not_accepted', message: 'Core not accepted' },
      stages: full.stages.map((stage) => ({
        ...stage,
        status: stage.name === 'qa' ? 'warnings' : 'ok',
      })),
      admet_stage: {
        name: 'admet',
        status: 'ok',
        count: 5,
        duration_seconds: 1,
        progress: null,
        reused_checkpoint: false,
      },
    };
    render(
      <>
        <StageStrip job={current} compact />
        <JobActions project={project} job={current} ready onChange={vi.fn()} compact />
        <ExtractionNotice
          project={{ ...project, acceptance: { state: 'failed', errors: [] } }}
          job={current}
        />
      </>,
    );
    expect(document.querySelector('.stage-current')).toHaveTextContent('需复核');
    expect(document.querySelector('.job-actions .badge')).toHaveTextContent('需复核');
    expect(screen.getByLabelText('提取验收与阻塞状态')).toHaveTextContent('提取未通过验收');
    expect(screen.queryByText('运行完成')).not.toBeInTheDocument();
    expect(screen.queryByText('核心 QA 通过')).not.toBeInTheDocument();
    expect(current.status).toBe('failed');
  });
  it('shows the complete declared default path before ADMET starts without inventing observations', () => {
    const stages = openStages(full);
    expect(stages.map((stage) => stage.querySelector('strong')?.textContent)).toEqual(labels);
    const last = stages.at(-1)!;
    expect(last).toHaveClass('pending');
    expect(within(last).getByText('等待')).toBeVisible();
    expect(within(last).queryByText(/缓存命中|本次执行|0 \/ 0/)).not.toBeInTheDocument();
    expect(document.querySelector('.stage-current')).toHaveTextContent('文档解析 · 进行中');
    expect(stageNames).toHaveLength(8); // Research is not a ninth formal CLI stage.
  });
  it('keeps an unrequested legacy/core-only job at eight stages', () => {
    const stages = openStages({ ...full, include_admet: false });
    expect(stages.map((stage) => stage.querySelector('strong')?.textContent)).toEqual(
      labels.slice(0, 8),
    );
  });
  it.each(['failed', 'interrupted', 'cancelled'] as const)(
    'marks the planned model phase unexecuted after upstream %s',
    (status) => {
      const stages = openStages({
        ...full,
        status,
        admet_stage: {
          name: 'admet',
          status: 'failed',
          count: null,
          duration_seconds: null,
          progress: null,
          reused_checkpoint: null,
        },
      });
      const last = stages.at(-1)!;
      expect(last).toHaveClass('pending');
      expect(within(last).getByText('未执行')).toBeVisible();
      expect(document.querySelector('.stage-current')).toHaveTextContent('文档解析 · 停止时进行中');
      expect(last).not.toHaveClass('failed');
    },
  );
  it('does not present unaccepted QA warnings as a model failure', () => {
    const stages = openStages({
      ...full,
      status: 'failed',
      error: { code: 'core_not_accepted', message: 'Core not accepted' },
      stages: full.stages.map((stage) => ({
        ...stage,
        status: stage.name === 'qa' ? 'warnings' : 'ok',
      })),
      admet_stage: {
        name: 'admet',
        status: 'failed',
        count: null,
        duration_seconds: null,
        progress: null,
        reused_checkpoint: null,
      },
    });
    expect(stages.at(-1)).not.toHaveClass('failed');
    expect(within(stages.at(-1)!).getByText('未执行')).toBeVisible();
  });
  it('uses the declared phase at the verified core-to-research handoff, without fake counters', () => {
    openStages({ ...full, stages: full.stages.map((stage) => ({ ...stage, status: 'ok' })) });
    expect(document.querySelector('.stage-current')).toHaveTextContent('ADMET / 指标 · 等待');
    expect(screen.queryByText(/\d+ \/ \d+|缓存命中/)).not.toBeInTheDocument();
  });
  it('does not claim completed research when its final phase record is missing', () => {
    const stages = openStages({
      ...full,
      status: 'complete',
      stages: full.stages.map((stage) => ({ ...stage, status: 'ok' })),
    });
    expect(stages.at(-1)).toHaveClass('unknown');
    expect(document.querySelector('.stage-current')).toHaveTextContent('ADMET / 指标 · 状态未提供');
  });
  it.each([false, null] as const)(
    'keeps unavailable history %s unknown for the entire configured chain',
    (history_available) => {
      const stages = openStages({ ...full, history_available });
      expect(stages).toHaveLength(9);
      expect(stages.every((stage) => stage.classList.contains('unknown'))).toBe(true);
      expect(screen.queryByText(/缓存命中|0 \/ 0/)).not.toBeInTheDocument();
    },
  );
  it('does not invent a completed core from an incomplete observed stage set', () => {
    const stages = openStages({ ...full, stages: full.stages.slice(0, 1) });
    expect(stages.at(-1)).toHaveClass('unknown');
    expect(within(stages.at(-1)!).getByText('状态未提供')).toBeVisible();
  });
  it.each(['recognition', 'properties'] as const)(
    'shows only the actual %s phase for existing-source completion',
    (phase) => {
      const stages = openStages({
        ...full,
        admet_only: true,
        stages: [],
        admet_stage: {
          name: 'admet',
          status: 'running',
          count: 2,
          duration_seconds: 1,
          reused_checkpoint: false,
          progress: {
            phase,
            completed: 2,
            total: 5,
            cache_hits: 1,
            failures: 0,
            device: null,
            peak_rss_mb: null,
          },
        },
      });
      expect(stages).toHaveLength(1);
      expect(stages[0]).toHaveTextContent(phase === 'recognition' ? '结构补齐' : '指标计算');
      expect(stages[0]!.querySelector('summary')).toHaveAttribute(
        'title',
        expect.stringContaining('补齐已证实来源的结构与指标'),
      );
      expect(stages[0]!.querySelector('summary')?.title).not.toContain('核心校验后执行');
      expect(document.querySelector('.stage-current')).toHaveTextContent('2 / 5');
      expect(screen.queryByText('文档解析')).not.toBeInTheDocument();
    },
  );
});
