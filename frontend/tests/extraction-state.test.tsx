import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AssetImage } from '../src/components/AssetImage';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { Metrics } from '../src/features/results/Metrics';
import { ExtractionNotice } from '../src/features/results/ExtractionNotice';
import { compound, job, project, results } from './fixtures';

const failedJob = {
  ...job,
  status: 'failed' as const,
  stages: job.stages.map((stage) => ({
    ...stage,
    status:
      stage.name === 'classify'
        ? ('ok' as const)
        : stage.name === 'activity'
          ? ('failed' as const)
          : ('pending' as const),
  })),
};
const failedProject = {
  ...project,
  summary: { ...project.summary, structures: 0, confirmed: 0 },
  acceptance: {
    state: 'failed' as const,
    errors: ['Activity rows require review before binding.'],
  },
};

function tableProps() {
  return {
    offset: 0,
    selected: new Set<string>(),
    focusedId: null,
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onActivitySource: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
  };
}

describe('current extraction failure presentation', () => {
  it('shows each assay source from the Activity DTO rather than the compound first page', () => {
    render(
      <ResultsTable
        {...tableProps()}
        rows={[
          {
            ...compound,
            activities: [
              {
                name: 'Cereblon HTRF grade',
                value: '+++',
                unit: null,
                target: 'Cereblon',
                assay: 'HTRF',
                page: 344,
              },
              {
                name: 'KP4 HuR degradation grade',
                value: 'A',
                unit: null,
                target: 'HuR',
                assay: 'Western blot',
                page: 345,
              },
              {
                name: 'Anti-proliferation activity grade',
                value: '+++',
                unit: null,
                target: null,
                assay: 'Anti-proliferation',
                page: 352,
              },
            ],
          },
        ]}
      />,
    );
    for (const page of [344, 345, 352])
      expect(screen.getByTitle(`活性来源第 ${page} 页`)).toBeVisible();
    for (const label of [
      'Cereblon',
      'HTRF',
      'HuR',
      'Western blot',
      'Anti-proliferation',
      '靶点未提供',
    ])
      expect(screen.getByText(label)).toBeVisible();
    expect(screen.queryByTitle('活性来源第 4 页')).not.toBeInTheDocument();
    expect(screen.getByTitle('Cereblon HTRF grade = +++')).toHaveTextContent('+++');
    expect(screen.getByTitle('Anti-proliferation activity grade = +++')).toHaveTextContent('+++');
  });
  it('exposes the actual blocking stage and raw-candidate warning without a historical claim', () => {
    render(
      <ResultsPane
        {...tableProps()}
        project={failedProject}
        job={failedJob}
        resource={{ data: results, loading: false, error: null, reload: vi.fn() }}
        filters={{ q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 }}
        onFilters={vi.fn()}
        onExport={vi.fn()}
        onUpload={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '提取验收详情' }));
    const notice = screen.getByRole('alert', { name: '提取验收与阻塞状态' });
    expect(within(notice).getByText('提取在活性提取阶段停止。')).toBeVisible();
    expect(
      within(notice).getByText(
        /尚未执行：来源定位、结构分割、结构绑定、SMILES 识别、产物导出、确定性 QA/,
      ),
    ).toBeVisible();
    expect(within(notice).getByText(/待复核候选记录，不是完整结构–活性结果/)).toBeVisible();
    expect(within(notice).getByText(failedProject.acceptance.errors[0]!)).toBeVisible();
    expect(screen.queryByText(/历史结果|历史运行导入/)).not.toBeInTheDocument();
    expect(screen.queryByText('核心 QA 通过')).not.toBeInTheDocument();
  });

  it('labels downstream pending stages unexecuted when the job has stopped', () => {
    const { rerender } = render(<StageStrip job={failedJob} />);
    expect(screen.getAllByText('未执行')).toHaveLength(6);
    expect(screen.queryByText('等待')).not.toBeInTheDocument();
    rerender(<StageStrip job={job} />);
    expect(screen.getAllByText('等待')).toHaveLength(7);
    expect(screen.queryByText('未执行')).not.toBeInTheDocument();
  });

  it('labels unaccepted activity counts as candidates without changing actual numbers', () => {
    render(<Metrics project={failedProject} />);
    expect(screen.getByText('候选活性记录')).toBeVisible();
    expect(screen.queryByText('已提取活性')).not.toBeInTheDocument();
  });

  it.each([
    ['structure_not_generated', '尚未生成结构裁图'],
    ['structure_generation_failed', '结构分割失败，未生成裁图'],
    ['image_unavailable', '裁图文件缺失或不可访问'],
    ['structure_unmatched', '尚未绑定结构裁图'],
  ])('distinguishes missing crop reason %s without a fabricated image', (flag, message) => {
    render(
      <ResultsTable
        {...tableProps()}
        rows={[{ ...compound, structure_image_url: null, flags: [flag] }]}
      />,
    );
    expect(screen.getByText(message)).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByLabelText('放大 I-7 结构裁图')).toBeDisabled();
  });

  it('distinguishes actual image loading failure and recovers on a different safe URL', () => {
    const { rerender } = render(<AssetImage url={compound.structure_image_url} alt="原始裁图" />);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('裁图加载失败')).toBeVisible();
    rerender(
      <AssetImage url="/api/v1/projects/project-contract/structures/I-8/image" alt="下一张裁图" />,
    );
    expect(screen.getByRole('img', { name: '下一张裁图' })).toBeVisible();
    expect(screen.queryByText('裁图加载失败')).not.toBeInTheDocument();
  });

  it('does not classify an unsafe image URL as an unexecuted extraction', () => {
    render(<AssetImage url="https://untrusted.invalid/crop.png" alt="结构裁图" />);
    expect(screen.getByText('裁图地址无效')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('keeps true historical identities distinct from a current incomplete run', () => {
    const { rerender } = render(
      <ExtractionNotice
        project={{
          ...project,
          is_historical: true,
          acceptance: { state: 'historical', errors: [] },
        }}
        job={null}
      />,
    );
    expect(screen.getByText('历史结果 · 仅供复核')).toBeVisible();
    rerender(<ExtractionNotice project={project} job={job} />);
    expect(screen.queryByText(/历史结果|历史身份产物/)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/尚未执行/)).not.toBeInTheDocument();
  });

  it('does not show a running animation after interruption or execute injected error text', () => {
    const interrupted = { ...job, status: 'interrupted' as const };
    const { container } = render(
      <>
        <StageStrip job={interrupted} />
        <ExtractionNotice
          project={{
            ...failedProject,
            acceptance: { state: 'failed', errors: ['<script>alert("untrusted")</script>'] },
          }}
          job={interrupted}
        />
      </>,
    );
    expect(screen.getByText('停止时进行中')).toBeVisible();
    expect(container.querySelector('.spin')).toBeNull();
    expect(screen.getByText('<script>alert("untrusted")</script>')).toBeVisible();
    expect(container.querySelector('script')).toBeNull();
  });
});
