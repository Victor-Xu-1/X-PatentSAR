import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StageStrip } from '../src/features/jobs/StageStrip';
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
describe('actual task progress and unavailable historic stages', () => {
  it('shows observed counts and resource data, not guessed percentages or ETA', () => {
    render(<StageStrip job={observed} />);
    const stage = screen.getByText('文档分类').closest('li')!;
    expect(within(stage).getByText(/12 \/ 100/)).toBeVisible();
    fireEvent.click(within(stage).getByText('文档分类').closest('summary')!);
    expect(within(stage).getByText('缓存命中 3 · 失败 1')).toBeVisible();
    expect(within(stage).getByText('CPU · 峰值 RSS 256.5 MB')).toBeVisible();
    expect(within(screen.getByText('活性提取').closest('li')!).getByText(/复用检查点/)).toBeVisible();
    expect(screen.queryByText(/\d+%|预计|准确率\s*\d/)).not.toBeInTheDocument();
  });
  it('labels absent progress and checkpoint facts unknown', () => {
    render(<StageStrip job={{ ...job, history_available: true }} />);
    expect(screen.getAllByText('进度未提供')).toHaveLength(8);
    expect(screen.getAllByText('检查点复用未知')).toHaveLength(8);
    expect(screen.queryByText(/0 \/ 0|缓存命中 0/)).not.toBeInTheDocument();
    const stage = screen.getByText('文档分类').closest('li')!;
    fireEvent.click(within(stage).getByText('文档分类').closest('summary')!);
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
    expect(screen.getByText(/历史阶段不可用.*共享目录/)).toBeVisible();
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
    fireEvent.click(screen.getByText('文档分类').closest('summary')!);
    expect(screen.getByText('执行设备未知 · 峰值 RSS 未提供')).toBeVisible();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});
