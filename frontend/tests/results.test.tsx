import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { ResultFilters } from '../src/features/results/ResultFilters';
import { Metrics } from '../src/features/results/Metrics';
import { Pagination } from '../src/features/results/Pagination';
import { compound, results } from './fixtures';
import { emptyRoute } from '../src/model/route';
import { Workspace } from '../src/features/workspace/Workspace';

function tableProps() {
  return {
    rows: [compound],
    offset: 0,
    metric: '',
    selected: new Set<string>(),
    focusedId: null,
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
  };
}
describe('real-value presentation and selection', () => {
  it('shows grade values, unknown confidence and real source, with no fake predictions', () => {
    render(<ResultsTable {...tableProps()} />);
    expect(screen.getByText('抑制等级 = ++')).toBeVisible();
    expect(screen.getByText('未知')).toBeVisible();
    expect(screen.getByText('无数值分数')).toBeVisible();
    expect(screen.getByText('第 4 页')).toBeVisible();
    expect(screen.queryByText(/IC50|LogP|ADMET/)).not.toBeInTheDocument();
  });
  it('selects authoritative IDs and positions the source row', async () => {
    const props = tableProps();
    render(<ResultsTable {...props} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText('选择化合物 I-7'));
    expect(props.onSelect).toHaveBeenCalledWith('I-7');
    await user.click(screen.getByText('来源定位'));
    expect(props.onJump).toHaveBeenCalledWith(compound);
    await user.click(screen.getByLabelText('复核 I-7'));
    expect(props.onReview).toHaveBeenCalledWith(compound);
  });
  it('marks partial page selection and allows crop enlargement', async () => {
    const props = tableProps();
    render(
      <ResultsTable
        {...props}
        rows={[compound, { ...compound, id: 'I-8', display_id: 'I-8' }]}
        selected={new Set(['I-7'])}
      />,
    );
    expect((screen.getByLabelText('选择当前页全部化合物') as HTMLInputElement).indeterminate).toBe(
      true,
    );
    await userEvent.click(screen.getByLabelText('放大 I-7 结构裁图'));
    expect(props.onCrop).toHaveBeenCalledWith(compound);
  });
  it('never exposes a made-up crop for missing assets', () => {
    render(<ResultsTable {...tableProps()} rows={[{ ...compound, structure_image_url: null }]} />);
    expect(screen.getByLabelText('放大 I-7 结构裁图')).toBeDisabled();
    expect(screen.getByText('裁图不可用')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('filters displayed metrics without inventing activities', () => {
    render(<ResultsTable {...tableProps()} metric="IC50" />);
    expect(screen.getByText('该指标无数据')).toBeVisible();
    expect(screen.queryByText('抑制等级 = ++')).not.toBeInTheDocument();
  });
  it('maps target/confidence/review filters to the contract', () => {
    const onChange = vi.fn();
    const onMetric = vi.fn();
    render(
      <ResultFilters
        filters={{ q: '', confidence: '', review: '', target: '', page: 3, page_size: 10 }}
        metrics={results.metrics}
        targets={results.targets}
        metric=""
        onMetric={onMetric}
        onChange={onChange}
        total={1}
        disabled={false}
      />,
    );
    fireEvent.change(screen.getByLabelText('筛选靶点'), { target: { value: '测试靶点' } });
    expect(onChange).toHaveBeenLastCalledWith({ target: '测试靶点', page: 1 });
    fireEvent.change(screen.getByLabelText('筛选置信度'), { target: { value: 'unknown' } });
    expect(onChange).toHaveBeenLastCalledWith({ confidence: 'unknown', page: 1 });
    fireEvent.change(screen.getByLabelText('筛选复核状态'), { target: { value: 'needs_review' } });
    expect(onChange).toHaveBeenLastCalledWith({ review: 'needs_review', page: 1 });
    fireEvent.change(screen.getByLabelText('显示活性指标'), { target: { value: '抑制等级' } });
    expect(onMetric).toHaveBeenCalledWith('抑制等级');
  });
  it('disables pagination boundaries and resets size changes to page one', () => {
    const onChange = vi.fn();
    render(<Pagination page={1} pageSize={10} total={31} disabled={false} onChange={onChange} />);
    expect(screen.getByLabelText('上一页结果')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('下一页结果'));
    expect(onChange).toHaveBeenLastCalledWith(2, 10);
    fireEvent.change(screen.getByLabelText('每页化合物数量'), { target: { value: '25' } });
    expect(onChange).toHaveBeenLastCalledWith(1, 25);
  });
  it('empty metrics contain no invented counts', () => {
    render(<Metrics project={null} />);
    expect(screen.getAllByText('—')).toHaveLength(4);
    expect(screen.getAllByText('等待项目数据')).toHaveLength(4);
  });
  it('first empty workspace is complete and extraction is disabled', () => {
    render(
      <Workspace
        project={null}
        route={emptyRoute}
        navigate={vi.fn()}
        query=""
        onQuery={vi.fn()}
        ready={false}
        job={null}
        onJobChange={vi.fn()}
        onProjectReload={vi.fn()}
        onUpload={vi.fn()}
        onAttach={vi.fn()}
      />,
    );
    expect(screen.getByText('原始专利文档')).toBeVisible();
    expect(screen.getByText('开始探索专利中的结构与活性')).toBeVisible();
    expect(screen.getByRole('button', { name: '运行提取' })).toBeDisabled();
    expect(screen.getByRole('tab', { name: '分子分析 · ADMET' })).toBeEnabled();
  });
});
