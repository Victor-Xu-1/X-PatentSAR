import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Job } from '../src/api/types';
import { JobRecord } from '../src/features/jobs/JobRecord';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { NewTaskPage } from '../src/features/tasks/NewTaskPage';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { jobRecordSummary } from '../src/model/jobPresentation';
import { job, project, projectListResource } from './fixtures';

function rejectedJob(): Job {
  return {
    ...job,
    status: 'failed',
    error: { code: 'core_not_accepted', message: 'Source stereo requires review.' },
    stages: job.stages.map((stage) => ({
      ...stage,
      status: ['smiles', 'final', 'qa'].includes(stage.name) ? 'failed' : 'ok',
      count: stage.name === 'smiles' ? 499 : null,
      progress:
        stage.name === 'smiles'
          ? {
              completed: 499,
              total: 499,
              failures: 2,
              cache_hits: 497,
              device: 'cpu',
              peak_rss_mb: 300,
            }
          : null,
    })),
  };
}

describe('Evidence Studio secondary pages', () => {
  it('keeps raw errors, dates, saved options and stages together in one closed disclosure', () => {
    const failed = { ...rejectedJob(), task_note: '<script>not executed</script>' };
    const { container } = render(<JobRecord job={failed} />);
    expect(screen.getByText('核心校验未通过，2 条结构需复核。')).toBeVisible();
    expect(screen.queryByText(/499 条结构需复核/)).not.toBeInTheDocument();
    const details = screen.getByLabelText('任务详情').parentElement!;
    expect(details.tagName).toBe('DETAILS');
    expect(container.querySelectorAll('details.job-record')).toHaveLength(1);
    expect(details).not.toHaveAttribute('open');
    expect(screen.getByText(/core_not_accepted：Source stereo/)).not.toBeVisible();
    expect(screen.getByText('创建')).not.toBeVisible();
    expect(screen.getByText('<script>not executed</script>')).not.toBeVisible();
    expect(screen.getByRole('list', { name: '任务运行链路', hidden: true })).not.toBeVisible();
    fireEvent.click(screen.getByLabelText('任务详情'));
    expect(details).toHaveAttribute('open');
    expect(screen.getByText(/core_not_accepted：Source stereo/)).toBeVisible();
    expect(screen.getByText('创建')).toBeVisible();
    expect(screen.getByText('<script>not executed</script>')).toBeVisible();
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByRole('list', { name: '任务运行链路' })).toBeVisible();
    expect(screen.getByText(`任务 ${failed.id}`)).toHaveAttribute('title', failed.id);
    expect(failed.status).toBe('failed');
    fireEvent.click(screen.getByLabelText('任务详情'));
    expect(screen.getByText(/core_not_accepted：Source stereo/)).not.toBeVisible();
  });

  it('does not borrow review counts from incomplete, inconsistent or unavailable history', () => {
    const failed = rejectedJob();
    const incomplete = {
      ...failed,
      stages: failed.stages.map((stage) =>
        stage.name === 'smiles'
          ? { ...stage, progress: { ...stage.progress!, completed: 497 } }
          : stage,
      ),
    };
    for (const value of [
      incomplete,
      { ...failed, history_available: false },
      { ...failed, stages: [] },
    ]) {
      expect(jobRecordSummary(value)).toBe('核心校验未通过，结果需复核。');
    }
  });

  it('keeps a technical failure distinct from a QA rejection and exposes its exact message', () => {
    const failed: Job = {
      ...job,
      status: 'failed',
      error: { code: 'memory_budget_exceeded', message: 'Actual measured process limit exceeded.' },
    };
    render(<JobRecord job={failed} expanded />);
    expect(screen.getByText('运行失败，原因见任务详情。')).toBeVisible();
    expect(screen.getByText(/memory_budget_exceeded：Actual measured/)).toBeVisible();
    expect(screen.queryByText(/结构需复核/)).not.toBeInTheDocument();
    expect(failed.error?.code).toBe('memory_budget_exceeded');
  });

  it('only advertises resuming an interrupted task when the server explicitly allows it', () => {
    expect(jobRecordSummary({ ...job, status: 'interrupted', can_resume: true })).toBe(
      '任务已中断，可继续提取。',
    );
    expect(jobRecordSummary({ ...job, status: 'interrupted', can_resume: false })).toBe(
      '任务已中断，恢复状态见任务详情。',
    );
  });

  it('never changes a nonfailed carrier to failed from the presence of an error record', () => {
    expect(
      jobRecordSummary({ ...job, error: { code: 'observed', message: 'Recorded observation' } }),
    ).toBe('任务报告了错误，原因见任务详情。');
    expect(jobRecordSummary({ ...job, status: 'failed', error: null })).toBe(
      '运行失败，服务端未提供原因。',
    );
  });

  it('shows measured active-stage progress without inventing percentages or unavailable history', () => {
    const observed: Job = {
      ...job,
      stages: job.stages.map((stage) => ({
        ...stage,
        progress:
          stage.name === 'classify'
            ? {
                completed: 4,
                total: 11,
                failures: 0,
                cache_hits: 0,
                device: 'cpu',
                peak_rss_mb: 200,
              }
            : null,
      })),
    };
    expect(jobRecordSummary(observed)).toBe('文档解析 · 4 / 11');
    expect(jobRecordSummary({ ...observed, history_available: false })).toBe('历史阶段不可用。');
    expect(jobRecordSummary({ ...observed, history_available: null })).toBe('阶段状态未知。');
  });

  it('retains one existing resume/run action path and one details entry per task', async () => {
    const interrupted: Job = { ...job, status: 'interrupted', can_resume: true };
    vi.spyOn(api, 'jobs').mockResolvedValue({ items: [interrupted] });
    vi.spyOn(api, 'job').mockResolvedValue(interrupted);
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    render(<JobsPage projects={projectListResource([project])} ready onOpen={vi.fn()} />);
    await screen.findByRole('button', { name: project.title });
    expect(screen.getAllByLabelText('任务详情')).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '继续提取' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '运行提取' })).toHaveLength(1);
    expect(screen.getByText('创建')).not.toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '继续提取' }));
    expect(create).toHaveBeenCalledExactlyOnceWith(project.id, interrupted.id);
  });

  it('announces the selected filename and keeps the PDF limit associated with the sole input', async () => {
    render(<NewTaskPage ready connected onCreated={vi.fn()} onOpen={vi.fn()} />);
    const input = screen.getByLabelText('原始专利 PDF 文件');
    expect(input).toHaveFocus();
    expect(input).toHaveAccessibleDescription('PDF · 最大 128 MiB');
    const file = new File(['%PDF-1.7\ncontract'], '很长的专利来源名称.pdf', {
      type: 'application/pdf',
    });
    await userEvent.upload(input, file);
    expect(screen.getByText(file.name)).toBeVisible();
    expect(document.querySelector('.upload-drop')).toHaveClass('has-file');
    expect(screen.getByRole('button', { name: '开始提取' })).toBeEnabled();
    expect(document.querySelectorAll('input')).toHaveLength(1);
    expect(screen.queryByText('高级选项')).not.toBeInTheDocument();
  });

  it('retains recent-file state, source availability, dates and keyboard opening without extra requests', async () => {
    const files = [
      { ...project, id: 'pending', title: '未验收文件', pdf: { ...project.pdf, available: false } },
      {
        ...project,
        id: 'failed',
        title: '需复核文件',
        acceptance: { state: 'failed' as const, errors: ['unchanged'] },
      },
    ];
    const onOpen = vi.fn();
    const readJobs = vi.spyOn(api, 'jobs');
    render(
      <ProjectsPage
        resource={{ data: { items: files }, loading: false, error: null, reload: vi.fn() }}
        onOpen={onOpen}
        onUpload={vi.fn()}
      />,
    );
    const missing = screen.getByRole('button', { name: '打开 未验收文件' });
    expect(missing).toHaveTextContent('原文未提供');
    const failed = screen.getByRole('button', { name: '打开 需复核文件' });
    expect(failed).toHaveTextContent('提取未通过验收');
    expect(failed.querySelector('time')).toHaveAttribute('dateTime', project.updated_at);
    failed.focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledExactlyOnceWith('failed');
    expect(readJobs).not.toHaveBeenCalled();
    expect(
      within(screen.getByRole('list', { name: '最近专利文件' })).getAllByRole('listitem'),
    ).toHaveLength(2);
  });
});
