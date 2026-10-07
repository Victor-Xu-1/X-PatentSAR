import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Job } from '../src/api/types';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { ExtractionNotice } from '../src/features/results/ExtractionNotice';
import { job, project } from './fixtures';

function reviewJob(total = 37, failures = 3): Job {
  return {
    ...job,
    status: 'failed',
    history_available: true,
    error: { code: 'core_not_accepted', message: 'Formal QA requires review.' },
    include_admet: true,
    stages: job.stages.map((stage) => ({
      ...stage,
      status: ['smiles', 'final', 'qa'].includes(stage.name) ? 'failed' : 'ok',
      count: stage.name === 'smiles' ? total : null,
      progress:
        stage.name === 'smiles'
          ? {
              completed: total,
              total,
              failures,
              cache_hits: total,
              device: null,
              peak_rss_mb: null,
            }
          : null,
    })),
    admet_stage: {
      name: 'admet',
      status: 'ok',
      count: total - failures,
      duration_seconds: 1,
      progress: null,
      reused_checkpoint: false,
    },
  };
}

describe('processed work is not a failure count', () => {
  it.each([
    [37, 3],
    [499, 2],
    [7, 7],
  ])(
    'shows only the observed review count for %i processed records and %i findings',
    (total, failures) => {
      const current = reviewJob(total, failures);
      render(<StageStrip job={current} compact />);
      const summary = document.querySelector('.stage-current')!;
      expect(summary).toHaveTextContent(`需复核 · ${failures} 条结构`);
      expect(summary).not.toHaveTextContent(`${total} / ${total}`);
      fireEvent.click(screen.getByLabelText('提取阶段详情'));
      const smiles = screen.getByText('SMILES 识别').closest('li')!;
      expect(smiles).toHaveClass('failed', 'needs-review');
      expect(smiles).not.toHaveClass('ok');
      expect(smiles.querySelector('summary')).toHaveTextContent(
        `需复核 · 已处理 ${total} / ${total}`,
      );
      expect(smiles.querySelector('summary')).not.toHaveTextContent(`失败 · ${total}`);
      fireEvent.click(within(smiles).getByText('SMILES 识别').closest('summary')!);
      expect(within(smiles).getByText(`缓存命中 ${total} · 待复核 ${failures}`)).toBeVisible();
      expect(current.status).toBe('failed');
      expect(current.stages.find((stage) => stage.name === 'smiles')?.status).toBe('failed');
      expect(screen.queryByText('核心 QA 通过')).not.toBeInTheDocument();
    },
  );

  it('does not say extraction stopped when the rejected core and research both ran', () => {
    const current = reviewJob();
    render(
      <>
        <StageStrip job={current} />
        <ExtractionNotice
          project={{ ...project, acceptance: { state: 'failed', errors: [] } }}
          job={current}
        />
      </>,
    );
    expect(screen.getByLabelText('提取验收与阻塞状态')).toHaveTextContent(
      '运行已结束，核心验收未通过。',
    );
    expect(screen.getByLabelText('提取验收与阻塞状态')).not.toHaveTextContent('阶段停止');
    expect(screen.getByText('生成结果').closest('li')).toHaveTextContent('未通过验收');
    expect(screen.getByText('核心校验').closest('li')).toHaveTextContent('未通过');
    expect(screen.getByText('ADMET / 指标').closest('li')).toHaveClass('ok');
  });

  it('keeps technical failure separate and labels its processed counter explicitly', () => {
    const current = reviewJob(37, 3);
    current.error = { code: 'extraction_failed', message: 'Model transport disconnected.' };
    current.stages = current.stages.map((stage) =>
      stage.name === 'smiles'
        ? { ...stage, count: 12, progress: { ...stage.progress!, completed: 12 } }
        : ['final', 'qa'].includes(stage.name)
          ? { ...stage, status: 'pending' }
          : stage,
    );
    render(<StageStrip job={current} compact />);
    expect(document.querySelector('.stage-current')).toHaveTextContent(
      'SMILES 识别 · 失败 · 已处理 12 / 37',
    );
    expect(document.querySelector('.stage-current')).not.toHaveTextContent('需复核');
    expect(screen.getByText('SMILES 识别').closest('li')).toHaveClass('failed');
    expect(screen.getByText('SMILES 识别').closest('li')).not.toHaveClass('needs-review');
  });

  it.each(['missing', 'incomplete', 'zero', 'unavailable'])(
    'does not invent a review count from %s recognition evidence',
    (kind) => {
      const current = reviewJob();
      if (kind === 'unavailable') current.history_available = false;
      current.stages = current.stages.map((stage) =>
        stage.name !== 'smiles'
          ? stage
          : {
              ...stage,
              progress:
                kind === 'missing'
                  ? null
                  : {
                      ...stage.progress!,
                      completed: kind === 'incomplete' ? 12 : 37,
                      failures: kind === 'zero' ? 0 : 3,
                    },
            },
      );
      render(<StageStrip job={current} compact />);
      expect(document.querySelector('.stage-current')).not.toHaveTextContent(/\d+ 条结构/);
      expect(document.querySelector('.stage-current')).not.toHaveTextContent('运行完成');
    },
  );
});

describe('repeat reports preserve one finding group per explicit identifier', () => {
  it('groups repeated stage messages without removing raw acceptance or contradictory findings', () => {
    const errors = [
      'smiles: Compound 17A: Source stereochemistry unresolved.',
      'final: Compound 17A: Source stereochemistry unresolved.',
      'qa: Compound 17A: Molecular graph also needs inspection.',
      'Compound 92B: Missing atom correspondence.',
      'qa: Final molecular count differs from confirmed bindings.',
      'Final molecular count differs from confirmed bindings.',
    ];
    const original = [...errors];
    render(
      <ExtractionNotice
        project={{ ...project, acceptance: { state: 'failed', errors } }}
        job={reviewJob()}
      />,
    );
    expect(screen.getByText('查看核心验收问题（2 条结构、1 项其他检查）')).toBeVisible();
    const first = screen.getByText('Compound 17A').closest('details')!;
    expect(within(first).getByText('Source stereochemistry unresolved.')).not.toBeVisible();
    fireEvent.click(within(first).getByText('Compound 17A').closest('summary')!);
    expect(within(first).getAllByText('Source stereochemistry unresolved.')).toHaveLength(1);
    expect(within(first).getByText('Molecular graph also needs inspection.')).toBeVisible();
    expect(within(first).getByText('SMILES 识别、生成结果')).toBeVisible();
    expect(
      screen.getAllByText('Final molecular count differs from confirmed bindings.'),
    ).toHaveLength(1);
    expect(errors).toEqual(original);
  });

  it('does not discard generic, unfamiliar-prefix or malicious error text', () => {
    const errors = [
      'transport: connection lost',
      '<script>untrusted</script>',
      'qa: Crop unavailable.',
    ];
    const { container } = render(
      <ExtractionNotice
        project={{ ...project, acceptance: { state: 'failed', errors } }}
        job={null}
      />,
    );
    for (const text of [
      'transport: connection lost',
      '<script>untrusted</script>',
      'Crop unavailable.',
    ])
      expect(screen.getByText(text)).toBeVisible();
    expect(container.querySelector('script')).toBeNull();
    expect(screen.queryByText(/条结构/)).not.toBeInTheDocument();
  });
});
