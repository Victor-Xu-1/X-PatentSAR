import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { CropDialog } from '../src/features/results/CropDialog';
import { Metrics } from '../src/features/results/Metrics';
import { Workspace } from '../src/features/workspace/Workspace';
import { api } from '../src/api';
import { emptyRoute } from '../src/model/route';
import { compound, page, project, results } from './fixtures';

const row = {
  ...compound,
  smiles: 'CCO',
  recognition: {
    status: 'valid' as const,
    quality_flag: null,
    model_fingerprint: 'test-only-model',
    token_confidence: { minimum: 0.4, mean: 0.8 },
  },
  redraw_image_url: '/api/v1/projects/project-contract/structures/I-7/redraw',
  activities: [
    { name: 'IC50', value: '<10', unit: 'nM', target: '靶点甲', assay: '酶活实验', page: 5 },
    {
      name: 'DC50',
      value: '10 - 100 nM',
      unit: 'nM',
      target: '靶点甲',
      assay: '酶活实验',
      page: 6,
    },
    { name: '抑制等级', value: '++', unit: null, target: null, assay: '细胞实验', page: 7 },
    { name: 'IC50', value: '30', unit: 'nM', target: '靶点乙', assay: '细胞实验', page: 8 },
  ],
};
const data = { ...results, items: [row], metrics: ['IC50', 'DC50', '抑制等级'] };
function props() {
  return {
    project,
    resource: { data, loading: false, error: null, reload: vi.fn() },
    filters: { q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 },
    selected: new Set<string>(),
    focusedId: null,
    onFilters: vi.fn(),
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onActivitySource: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
    onExport: vi.fn(),
    onUpload: vi.fn(),
  };
}

describe('dense evidence-led result workspace', () => {
  it('keeps statistics and explanations off the primary table and opens them on demand', async () => {
    render(<ResultsPane {...props()} />);
    expect(screen.queryByLabelText('项目真实统计')).not.toBeInTheDocument();
    expect(
      screen.queryByText('点击编号对照原图与重绘 · 活性页码返回独立来源'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('实验上下文去重 · 每个值保留独立来源')).not.toBeInTheDocument();
    expect(screen.getAllByRole('textbox', { name: '搜索结果' })).toHaveLength(1);
    await userEvent.setup().click(screen.getByRole('button', { name: '结果信息' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('项目真实统计')).toBeVisible();
    expect(within(dialog).getByLabelText('提取验收与阻塞状态')).toBeVisible();
  });
  it('uses compact columns, deduplicates assay context and preserves every activity source', () => {
    render(<ResultsPane {...props()} />);
    expect(screen.getByRole('table')).toHaveAttribute('data-density', 'compact');
    for (const metric of data.metrics)
      expect(screen.getByRole('columnheader', { name: metric })).toBeVisible();
    expect(screen.getAllByText('靶点甲')).toHaveLength(1);
    expect(screen.getAllByText('酶活实验')).toHaveLength(1);
    for (const text of ['IC50 = <10 nM', 'DC50 = 10 - 100 nM', '抑制等级 = ++', 'IC50 = 30 nM']) {
      expect(screen.getByTitle(text)).toBeVisible();
    }
    for (const activity of row.activities) {
      expect(
        screen.getByRole('button', {
          name: `${row.display_id} ${activity.name} 活性来源第 ${activity.page} 页`,
        }),
      ).toBeEnabled();
    }
  });
  it('switches density and metric columns without filtering rows, losing selection or changing export', async () => {
    const original = props();
    render(<ResultsPane {...original} selected={new Set([row.id])} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '显示选项' }));
    await user.click(screen.getByRole('button', { name: '舒适视图' }));
    expect(screen.getByRole('table')).toHaveAttribute('data-density', 'comfortable');
    await user.click(screen.getByLabelText('显示指标 DC50'));
    expect(screen.queryByRole('columnheader', { name: 'DC50' })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'IC50' })).toBeVisible();
    expect(screen.getByLabelText('选择化合物 I-7')).toBeChecked();
    expect(screen.getByText('已选 1')).toBeVisible();
    expect(original.onFilters).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '显示全部指标' }));
    expect(screen.getByRole('columnheader', { name: 'DC50' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: '关闭对话框' }));
    await user.click(screen.getByRole('button', { name: '导出所选 (1)' }));
    expect(original.onExport).toHaveBeenCalledOnce();
  });
  it('keeps binding, RDKit recognition and manual decisions independently visible', () => {
    render(<ResultsPane {...props()} />);
    for (const name of ['绑定证据', '识别校验', '人工复核']) {
      expect(screen.getByRole('columnheader', { name })).toBeVisible();
    }
    expect(screen.getByText('RDKit 可解析')).toBeVisible();
    expect(screen.getByText('未复核')).toBeVisible();
    expect(within(screen.getByRole('table')).queryByText('复核通过')).not.toBeInTheDocument();
  });
  it('uses explicit unknown recognition even when a legacy row has SMILES', () => {
    render(
      <ResultsPane
        {...props()}
        resource={{
          ...props().resource,
          data: { ...results, items: [{ ...compound, smiles: 'CCO' }] },
        }}
      />,
    );
    expect(screen.getByText('识别状态未知')).toBeVisible();
    expect(screen.queryByText('RDKit 可解析')).not.toBeInTheDocument();
  });
  it('does not conflate binding pending zero with genuine manual pending counts', () => {
    render(
      <Metrics
        project={{
          ...project,
          summary: {
            ...project.summary,
            needs_review: 0,
            manually_reviewed: 2,
            manual_review_pending: 98,
          },
        }}
      />,
    );
    const cards = screen.getByLabelText('项目真实统计');
    expect(
      within(screen.getByText('绑定待核验').closest('.metric-card')!).getByText('0'),
    ).toBeVisible();
    expect(
      within(screen.getByText('人工已复核').closest('.metric-card')!).getByText('2'),
    ).toBeVisible();
    expect(
      within(screen.getByText('人工待复核').closest('.metric-card')!).getByText('98'),
    ).toBeVisible();
    expect(cards).not.toHaveTextContent('待人工复核');
  });
  it('shows missing manual counts as unknown, never zero', () => {
    render(<Metrics project={project} />);
    expect(
      within(screen.getByText('人工已复核').closest('.metric-card')!).getByText('未知'),
    ).toBeVisible();
    expect(
      within(screen.getByText('人工待复核').closest('.metric-card')!).getByText('未知'),
    ).toBeVisible();
  });
  it('keeps a needs_review annotation pending despite a valid recognition result', () => {
    const pending = {
      ...row,
      review: {
        decision: 'needs_review' as const,
        note: '已看过，仍需核验',
        revision: 1,
        updated_at: project.updated_at,
      },
    };
    render(
      <ResultsPane
        {...props()}
        project={{
          ...project,
          summary: { ...project.summary, manually_reviewed: 0, manual_review_pending: 1 },
        }}
        resource={{ ...props().resource, data: { ...data, items: [pending] } }}
      />,
    );
    const table = screen.getByRole('table');
    expect(within(table).getByText('RDKit 可解析')).toBeVisible();
    expect(within(table).getByText('待复核')).toBeVisible();
    expect(within(table).queryByText('复核通过')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '结果信息' }));
    expect(
      within(screen.getByText('人工已复核').closest('.metric-card')!).getByText('0'),
    ).toBeVisible();
    expect(
      within(screen.getByText('人工待复核').closest('.metric-card')!).getByText('1'),
    ).toBeVisible();
  });
  it('navigates each metric to its own activity page without a false structure highlight', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(data);
    vi.spyOn(api, 'page').mockResolvedValue(page);
    const navigate = vi.fn();
    render(
      <Workspace
        project={project}
        route={{ ...emptyRoute, projectId: project.id }}
        navigate={navigate}
        query=""
        onQuery={vi.fn()}
        ready
        job={null}
        onJobChange={vi.fn()}
        onProjectReload={vi.fn()}
        onUpload={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'I-7 DC50 活性来源第 6 页' }));
    expect(navigate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 6,
        tab: 'original',
        compoundId: null,
        layout: expect.objectContaining({ pdfVisible: true }),
      }),
    );
  });
  it('keeps absent metric source explicitly unavailable rather than borrowing the structure page', () => {
    render(
      <ResultsPane
        {...props()}
        resource={{
          ...props().resource,
          data: {
            ...data,
            items: [{ ...row, activities: [{ ...row.activities[0]!, page: null }] }],
          },
        }}
      />,
    );
    expect(screen.getByRole('button', { name: 'I-7 IC50 活性来源页码未知' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /IC50 活性来源第 4 页/ })).not.toBeInTheDocument();
  });
});

describe('source crop and derived SMILES are separate facts', () => {
  it('shows original crop and server redraw side by side and labels uncalibrated token confidence', () => {
    render(<CropDialog compound={row} projectId={project.id} onClose={vi.fn()} />);
    const comparison = screen.getByLabelText('原始裁图与 SMILES 重绘对照');
    expect(within(comparison).getByRole('img', { name: 'I-7 的原始结构裁图' })).toHaveAttribute(
      'src',
      row.structure_image_url,
    );
    expect(
      within(comparison).getByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' }),
    ).toHaveAttribute('src', row.redraw_image_url);
    expect(screen.getByText(/模型 token confidence（未校准）/)).toBeVisible();
    expect(screen.getByText(/不是结构正确率/)).toBeVisible();
    expect(screen.getByLabelText('规范化 SMILES（服务端）')).toHaveValue('CCO');
  });
  it('shows no-SMILES and missing-crop reasons without fake pictures or disabled details access', () => {
    const missing = { ...compound, structure_image_url: null, flags: ['structure_not_generated'] };
    const { rerender } = render(
      <CropDialog compound={missing} projectId={project.id} onClose={vi.fn()} />,
    );
    expect(screen.getByText('尚未生成结构裁图')).toBeVisible();
    expect(screen.getByText('未提供 SMILES，无法重绘')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('识别状态未知')).toBeVisible();
    rerender(
      <ResultsPane
        {...props()}
        resource={{ ...props().resource, data: { ...results, items: [missing] } }}
      />,
    );
    expect(screen.getByRole('button', { name: '查看 I-7 结构详情' })).toBeEnabled();
  });
  it('keeps redraw load failure separate from the usable source crop', () => {
    render(<CropDialog compound={row} projectId={project.id} onClose={vi.fn()} />);
    fireEvent.error(screen.getByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' }));
    expect(screen.getByText('重绘加载失败')).toBeVisible();
    expect(screen.getByRole('img', { name: 'I-7 的原始结构裁图' })).toBeVisible();
  });
  it('refuses a redraw for missing or explicitly invalid SMILES even when a URL is supplied', () => {
    const { rerender } = render(
      <CropDialog compound={{ ...row, smiles: null }} projectId={project.id} onClose={vi.fn()} />,
    );
    expect(
      screen.queryByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('未提供 SMILES，无法重绘')).toBeVisible();
    rerender(
      <CropDialog
        compound={{ ...row, recognition: { ...row.recognition, status: 'invalid' } }}
        projectId={project.id}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('SMILES 未通过 RDKit 校验，无法重绘')).toBeVisible();
  });
  it('recovers a failed redraw on a new server content digest, without replacing the source crop', () => {
    const { rerender } = render(
      <CropDialog compound={row} projectId={project.id} onClose={vi.fn()} />,
    );
    fireEvent.error(screen.getByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' }));
    const fresh = { ...row, redraw_image_url: `${row.redraw_image_url}?digest=new-run` };
    rerender(<CropDialog compound={fresh} projectId={project.id} onClose={vi.fn()} />);
    expect(screen.getByRole('img', { name: 'I-7 的 SMILES 重绘（非原图）' })).toHaveAttribute(
      'src',
      fresh.redraw_image_url,
    );
    expect(screen.getByRole('img', { name: 'I-7 的原始结构裁图' })).toHaveAttribute(
      'src',
      row.structure_image_url,
    );
  });
});
