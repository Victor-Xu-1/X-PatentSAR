import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { decodeJob } from '../src/api/decoders';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { JobActions } from '../src/features/jobs/JobActions';
import { ExtractionNotice } from '../src/features/results/ExtractionNotice';
import { job, project } from './fixtures';

const observed = {
  ...job,
  history_available: true,
  stages: job.stages.map((stage) => ({
    ...stage,
    progress:
      stage.name === 'classify'
        ? {
            completed: 12,
            total: 100,
            cache_hits: 3,
            failures: 1,
            device: 'cpu' as const,
            peak_rss_mb: 256.5,
          }
        : null,
    reused_checkpoint: stage.name === 'activity',
  })),
};
const resourceWait = { reason: 'memory', required_mb: 2048, available_mb: 512, waited_seconds: 12 };
const waiting = () =>
  decodeJob({
    ...job,
    stages: job.stages.map((stage, index) =>
      index === 0 ? { ...stage, resource_wait: resourceWait } : stage,
    ),
  });
describe('actual task progress and unavailable historic stages', () => {
  it.each(['running', 'pending'] as const)(
    'shows an actual %s research wait despite rejected core work without promoting acceptance',
    (status) => {
      const current = decodeJob({
        ...job,
        include_admet: true,
        stages: job.stages.map((stage) => ({
          ...stage,
          status: stage.name === 'qa' ? 'failed' : 'ok',
        })),
        admet_stage: {
          name: 'admet',
          status,
          count: null,
          duration_seconds: null,
          progress: null,
          reused_checkpoint: null,
          resource_wait: resourceWait,
        },
      });
      render(<StageStrip job={current} compact />);
      expect(document.querySelector('.stage-current')).toHaveTextContent('ADMET / 指标 · 等待资源');
      expect(screen.queryByText(/0 \/ 0|缓存命中/)).not.toBeInTheDocument();
      expect(screen.queryByText('运行完成')).not.toBeInTheDocument();
      expect(current.stages.find((stage) => stage.name === 'qa')?.status).toBe('failed');
    },
  );
  it('shows a concise actual resource wait, discloses measurements only on demand and retains cancel', () => {
    const current = waiting();
    render(
      <>
        <StageStrip job={current} compact />
        <JobActions project={project} job={current} ready onChange={vi.fn()} compact />
      </>,
    );
    expect(document.querySelector('.stage-current')).toHaveTextContent('文档解析 · 等待资源');
    expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled();
    expect(screen.getByText('所需内存 2048 MB · 可用 512 MB')).not.toBeVisible();
    fireEvent.click(screen.getByLabelText('提取阶段详情'));
    const stage = screen.getByText('文档解析').closest('li')!;
    expect(within(stage).getByText('等待资源')).toBeVisible();
    expect(within(stage).queryByText(/0 \/ 0|缓存命中/)).not.toBeInTheDocument();
    fireEvent.click(within(stage).getByText('文档解析').closest('summary')!);
    expect(within(stage).getByText('所需内存 2048 MB · 可用 512 MB')).toBeVisible();
    expect(within(stage).getByText('已等待 12 秒')).toBeVisible();
    expect(screen.queryByText(/预计|\d+%/)).not.toBeInTheDocument();
  });
  it.each(['complete', 'failed', 'cancelled', 'interrupted'] as const)(
    'does not keep an actual wait or animation active after job %s',
    (status) => {
      const { container } = render(<StageStrip job={{ ...waiting(), status }} compact />);
      expect(container.querySelector('.spin')).toBeNull();
      expect(screen.queryByText('等待资源')).not.toBeInTheDocument();
      fireEvent.click(screen.getByLabelText('提取阶段详情'));
      expect(screen.getByText('停止时进行中')).toBeVisible();
    },
  );
  it.each([false, null] as const)(
    'does not borrow resource waits from history availability %s',
    (history_available) => {
      const { container } = render(<StageStrip job={{ ...waiting(), history_available }} />);
      expect(container.querySelector('.spin')).toBeNull();
      expect(screen.queryByText('等待资源')).not.toBeInTheDocument();
      expect(screen.queryByText(/所需内存|已等待 12/)).not.toBeInTheDocument();
    },
  );
  it.each(['ok', 'empty', 'failed', 'warnings'] as const)(
    'does not turn a terminal %s stage with a retained wait observation into an active producer',
    (status) => {
      const current = waiting();
      current.stages = current.stages.map((stage, index) =>
        index === 0 ? { ...stage, status } : stage,
      );
      const { container } = render(<StageStrip job={current} />);
      expect(screen.queryByText('等待资源')).not.toBeInTheDocument();
      expect(container.querySelector('.spin')).toBeNull();
    },
  );
  it('does not infer a wait from absent/null observations or unrelated producer progress', () => {
    const current = decodeJob({
      ...observed,
      stages: observed.stages.map((stage) => ({ ...stage, resource_wait: null })),
    });
    render(<StageStrip job={current} />);
    expect(screen.queryByText('等待资源')).not.toBeInTheDocument();
    expect(screen.queryByText(/所需内存|已等待 \d/)).not.toBeInTheDocument();
    expect(screen.getByText(/12 \/ 100/)).toBeVisible();
  });
  it('shows observed counts and resource data, not guessed percentages or ETA', () => {
    render(<StageStrip job={observed} />);
    const stage = screen.getByText('文档解析').closest('li')!;
    expect(within(stage).getByText(/12 \/ 100/)).toBeVisible();
    fireEvent.click(within(stage).getByText('文档解析').closest('summary')!);
    expect(within(stage).getByText('缓存命中 3 · 失败 1')).toBeVisible();
    expect(within(stage).getByText('CPU · 峰值 RSS 256.5 MB')).toBeVisible();
    expect(
      within(screen.getByText('活性提取').closest('li')!).getByText(/复用检查点/),
    ).toBeVisible();
    expect(screen.queryByText(/\d+%|预计|准确率\s*\d/)).not.toBeInTheDocument();
  });
  it('labels absent progress and checkpoint facts unknown', () => {
    render(<StageStrip job={{ ...job, history_available: true }} />);
    expect(screen.getAllByText('进度未提供')).toHaveLength(8);
    expect(screen.getAllByText('检查点复用未知')).toHaveLength(8);
    expect(screen.queryByText(/0 \/ 0|缓存命中 0/)).not.toBeInTheDocument();
    const stage = screen.getByText('文档解析').closest('li')!;
    fireEvent.click(within(stage).getByText('文档解析').closest('summary')!);
    expect(within(stage).getByText('进度未提供')).toBeVisible();
    expect(within(stage).getByText('检查点复用未知')).toBeVisible();
  });
  it('does not project a shared directory success into a history-unavailable attempt', () => {
    const unavailable = {
      ...observed,
      status: 'failed' as const,
      history_available: false,
      stages: observed.stages.map((stage) => ({ ...stage, status: 'ok' as const })),
    };
    const { container } = render(
      <>
        <StageStrip job={unavailable} />
        <ExtractionNotice
          project={{ ...project, acceptance: { state: 'failed', errors: [] } }}
          job={unavailable}
        />
      </>,
    );
    expect(screen.getByText(/历史阶段不可用.*无法可靠读取/)).toBeVisible();
    expect(screen.queryByText('完成')).not.toBeInTheDocument();
    expect(screen.queryByText(/12 \/ 100/)).not.toBeInTheDocument();
    expect(container.querySelector('.stage.ok')).toBeNull();
    expect(screen.queryByText(/阶段停止|尚未执行/)).not.toBeInTheDocument();
  });
  it('keeps missing history availability unknown rather than trusting stage success', () => {
    render(
      <StageStrip
        job={{
          ...job,
          history_available: null,
          stages: job.stages.map((stage) => ({ ...stage, status: 'ok' as const })),
        }}
      />,
    );
    expect(screen.getByText('历史阶段可用性未知')).toBeVisible();
    expect(screen.queryByText('完成')).not.toBeInTheDocument();
    expect(screen.getAllByText('阶段状态未知')).toHaveLength(8);
  });
  it('renders zero workload as observed zero without constructing a progress bar', () => {
    render(
      <StageStrip
        job={{
          ...observed,
          stages: [
            {
              ...observed.stages[0]!,
              progress: {
                completed: 0,
                total: 0,
                cache_hits: 0,
                failures: 0,
                device: null,
                peak_rss_mb: null,
              },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/0 \/ 0/)).toBeVisible();
    fireEvent.click(screen.getByText('文档解析').closest('summary')!);
    expect(screen.getByText('执行设备未知 · 峰值 RSS 未提供')).toBeVisible();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});
