import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Job, Stage } from '../src/api/types';
import { errorText, UiError } from '../src/i18n';
import { JobRecord } from '../src/features/jobs/JobRecord';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { StageObservation } from '../src/features/jobs/StageObservation';
import { acceptanceIssueCount, acceptanceIssueGroups } from '../src/model/acceptanceIssues';
import { jobStageProgressText } from '../src/model/jobPresentation';
import { stageProgressText } from '../src/model/extraction';
import { activityText, dateText } from '../src/model/presentation';
import { job, project } from './fixtures';
import {
  deferred,
  progress,
  rejectedJob,
  setupOperationsLocale,
  switchTo,
} from './i18n-operations-fixtures';

setupOperationsLocale();

describe('operations locale: jobs', () => {
  it('updates detailed and compact job observations without relabeling raw errors, notes or IDs', () => {
    const rejected = rejectedJob();
    render(
      <>
        <JobRecord job={rejected} expanded />
        <StageStrip job={rejected} compact />
      </>,
    );
    const disclosure = screen.getByLabelText('Extraction stage details').closest('details')!;
    disclosure.open = true;
    switchTo('en');
    expect(screen.getByLabelText('Extraction stage details').closest('details')).toBe(disclosure);
    expect(disclosure.open).toBe(true);
    expect(
      screen.getByText('Core validation failed. Structures requiring review: 2.'),
    ).toBeVisible();
    expect(disclosure).toHaveTextContent('Needs review');
    expect(disclosure).toHaveTextContent('Structures: 2');
    expect(screen.getByRole('region', { name: 'Failure details' })).toHaveTextContent(
      'core_not_accepted：设置已保存。',
    );
    expect(screen.getByRole('region', { name: 'Saved task parameters' })).toHaveTextContent('保存');
    expect(screen.getByText('Task ' + rejected.id)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText('核心校验未通过，2 条结构需复核。')).toBeVisible();
    expect(disclosure.open).toBe(true);
  });

  it('localizes fresh acceptance captions and retained errors, never measurements or source messages', () => {
    const stored = new UiError('组件依赖 {id} 未在服务端目录中声明，不能确认安装。', {
      id: '依赖原文',
    });
    const raw = 'qa: Compound I-7: 设置已保存。';
    const activity = {
      name: '保存',
      value: '中文原值',
      unit: 'nM',
      target: null,
      assay: null,
      page: null,
    };
    switchTo('en');
    const groups = acceptanceIssueGroups([raw, 'smiles: Compound I-7: 设置已保存。']);
    expect(groups[0]?.subject).toBe('Compound I-7');
    expect(groups[0]?.issues[0]).toEqual({
      message: '设置已保存。',
      stages: ['Core validation', 'SMILES recognition'],
    });
    expect(acceptanceIssueCount(groups)).toBe('Structures: 1');
    expect(activityText(activity)).toBe('保存 = 中文原值 nM');
    expect(errorText(stored)).toBe(
      'Dependency 依赖原文 is absent from the server catalog. Installation cannot be confirmed.',
    );
    switchTo('zh-CN');
    expect(errorText(stored)).toBe('组件依赖 依赖原文 未在服务端目录中声明，不能确认安装。');
    expect(stored.message).toBe('组件依赖 依赖原文 未在服务端目录中声明，不能确认安装。');
  });

  it.each([
    ['recognition', 'Structure completion'],
    ['properties', 'Property calculation'],
    ['lead', 'Lead prioritization'],
  ] as const)('updates expanded %s observation and resource captions in place', (phase, label) => {
    const stage: Stage = {
      ...job.stages[0]!,
      name: 'admet',
      progress: { ...progress, phase },
      resource_wait: { reason: 'memory', required_mb: 3072, available_mb: 1024, waited_seconds: 7 },
      repair: { regions: 2, unresolved: 1 },
      skipped: 1,
    };
    const view = render(
      <StageObservation job={{ ...job, admet_only: true }} stage={stage} name="admet" />,
    );
    const detail = view.container.querySelector('details')!;
    detail.open = true;
    switchTo('en');
    expect(screen.getByText(label, { selector: 'strong' })).toBeVisible();
    expect(screen.getByText('Memory required 3072 MB · Available 1024 MB')).toBeVisible();
    expect(screen.getByText('Waited 7 seconds')).toBeVisible();
    expect(screen.getByText('Source regions 2 · Unresolved 1')).toBeVisible();
    expect(screen.getByText('Not calculated: 1 (no valid SMILES)')).toBeVisible();
    expect(detail.querySelector('summary')).toHaveAttribute(
      'title',
      expect.stringContaining('LogS is an ADMET prediction'),
    );
    switchTo('zh-CN');
    expect(screen.getByText('已等待 7 秒')).toBeVisible();
    expect(view.container.querySelector('details')).toBe(detail);
    expect(detail.open).toBe(true);
  });

  it('preserves every original Chinese progress caption and translates only its presentation', () => {
    for (const name of ['structures', 'smiles'] as const) {
      for (const status of ['running', 'failed'] as const) {
        const stage: Stage = { ...job.stages[0]!, name, status, progress };
        switchTo('zh-CN');
        expect(jobStageProgressText(stage)).toBe(stageProgressText(stage));
        switchTo('en');
        const expected =
          (status === 'failed' ? 'Processed ' : '') +
          '10 / 10' +
          (name === 'structures' ? ' pages' : '');
        expect(jobStageProgressText(stage)).toBe(expected);
        expect(stage.progress).toEqual(progress);
      }
    }
  });

  it('updates lazy task captions and Intl dates while preserving source timestamps, titles and records', async () => {
    const pending = deferred<{ items: Job[] }>();
    const read = vi.spyOn(api, 'jobs').mockReturnValue(pending.promise);
    vi.spyOn(api, 'job').mockResolvedValue(job);
    const view = render(<JobsPage projects={[project]} ready onOpen={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Tasks' })).toBeVisible();
    expect(screen.getByText('Loading task records…')).toBeVisible();
    switchTo('zh-CN');
    await act(async () => pending.resolve({ items: [job] }));
    const time = view.container.querySelector<HTMLTimeElement>('.job-timestamp')!;
    expect(time).toHaveAttribute('datetime', job.created_at);
    const expectedDate = (locale: string) =>
      new Date(job.created_at).toLocaleString(locale, { hour12: false });
    expect(time).toHaveTextContent(expectedDate('zh-CN'));
    switchTo('en');
    expect(time).toHaveTextContent(expectedDate('en'));
    expect(view.container.querySelector('.job-timestamp')).toBe(time);
    expect(screen.getByRole('button', { name: project.title })).toBeVisible();
    expect(dateText('原始日期')).toBe('原始日期');
    expect(dateText(null)).toBe('—');
    expect(read).toHaveBeenCalledTimes(1);
  });
});
