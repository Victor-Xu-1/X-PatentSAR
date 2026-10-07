import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CoreStageName, Job } from '../src/api/types';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { workflowGroups } from '../src/model/workflowGroups';
import { job } from './fixtures';

const sourceOrder: CoreStageName[] = [
  'classify',
  'locate',
  'structures',
  'bind',
  'activity',
  'smiles',
  'final',
  'qa',
];
const sourceJob: Job = { ...job, stage_order: sourceOrder, include_admet: true };

describe('Evidence Studio groups are a view of the recorded chain', () => {
  it('groups the source-first chain without putting post-core properties before QA', () => {
    const groups = workflowGroups(sourceJob);
    expect(groups.map((group) => group.label)).toEqual([
      '解析定位',
      '结构编号',
      '活性识别',
      '校验与指标',
    ]);
    expect(groups.flatMap((group) => group.names)).toEqual([...sourceOrder, 'admet']);
    expect(groups.at(-1)?.names).toEqual(['final', 'qa', 'admet']);
  });

  it('preserves another supplied order rather than inventing a new pipeline', () => {
    const order = [...sourceOrder].reverse();
    expect(
      workflowGroups({ ...sourceJob, stage_order: order }).flatMap((group) => group.names),
    ).toEqual([...order, 'admet']);
  });

  it('keeps all unavailable history unknown and an ADMET-only task in one group', () => {
    expect(
      workflowGroups({ ...sourceJob, history_available: false }).every(
        (group) => group.state === 'unknown',
      ),
    ).toBe(true);
    const groups = workflowGroups({ ...sourceJob, admet_only: true, stages: [] });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.names).toEqual(['admet']);
    expect(groups[0]?.state).not.toBe('ok');
  });

  it('does not show a rejected complete observation collection as accepted work', () => {
    const current: Job = {
      ...sourceJob,
      status: 'failed',
      error: { code: 'core_not_accepted', message: 'Review required' },
      stages: sourceJob.stages.map((stage) => ({
        ...stage,
        status: ['smiles', 'final', 'qa'].includes(stage.name) ? 'failed' : 'ok',
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
    const groups = workflowGroups(current);
    expect(groups.map((group) => group.state)).toEqual(['ok', 'ok', 'review', 'review']);
    expect(groups.at(-1)?.description).toContain('核心校验：未通过');
    expect(current.status).toBe('failed');
    expect(current.stages.find((stage) => stage.name === 'qa')?.status).toBe('failed');
  });

  it('keeps running, stopped, missing and empty work distinct', () => {
    const allDone = sourceJob.stages.map((stage) => ({ ...stage, status: 'ok' as const }));
    expect(
      workflowGroups({ ...sourceJob, status: 'complete', stages: allDone }).at(-1)?.state,
    ).toBe('unknown');
    const running = {
      ...sourceJob,
      stages: allDone.map((stage) =>
        stage.name === 'structures' ? { ...stage, status: 'running' as const } : stage,
      ),
    };
    expect(workflowGroups(running)[1]?.state).toBe('running');
    expect(workflowGroups({ ...running, status: 'interrupted' })[1]?.state).toBe('stopped');
    const empty = {
      ...sourceJob,
      stages: allDone.map((stage) =>
        ['structures', 'bind'].includes(stage.name)
          ? { ...stage, status: 'empty' as const }
          : stage,
      ),
    };
    expect(workflowGroups(empty)[1]?.state).toBe('empty');
  });
});

describe('readable workflow disclosure', () => {
  it('opens real stage details, closes with Escape and returns keyboard focus', () => {
    render(<StageStrip job={sourceJob} compact />);
    const trigger = screen.getByLabelText('提取阶段详情');
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole('list', { name: '任务运行链路' })).toBeVisible();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByRole('list', { name: '任务运行链路', hidden: true })).not.toBeVisible();
    expect(trigger).toHaveFocus();
  });

  it('closes on an outside pointer without stealing focus or changing the task', () => {
    const { container } = render(
      <>
        <StageStrip job={sourceJob} compact />
        <button>其他操作</button>
      </>,
    );
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    const outside = screen.getByRole('button', { name: '其他操作' });
    outside.focus();
    fireEvent.pointerDown(outside);
    expect(container.querySelector('details.stage-disclosure')).not.toHaveAttribute('open');
    expect(outside).toHaveFocus();
    expect(sourceJob.status).toBe(job.status);
  });
});
