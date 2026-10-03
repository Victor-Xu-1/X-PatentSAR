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
describe('real-value presentation and selection', () => {
  it('shows grade values, unknown confidence and real source, with no fake predictions', () => {
    render(<ResultsTable {...tableProps()} />);
    expect(screen.getByTitle('抑制等级 = ++')).toHaveTextContent('++');
    expect(screen.getByLabelText('MW 未计算')).toHaveTextContent('—');
    expect(screen.queryByText('无数值分数')).not.toBeInTheDocument();
    expect(screen.getByLabelText('I-7 结构来源第 4 页')).toBeVisible();
    expect(screen.queryByTitle('IC50 = 722 nM')).not.toBeInTheDocument();
  });
  it('selects authoritative IDs and positions the source row', async () => {
    const props = tableProps();
    render(<ResultsTable {...props} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText('选择化合物 I-7'));
    expect(props.onSelect).toHaveBeenCalledWith('I-7');
    await user.click(screen.getByLabelText('I-7 结构来源第 4 页'));
    expect(props.onJump).toHaveBeenCalledWith(compound);
    await user.click(screen.getByLabelText('修正 I-7'));
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
    expect(screen.getByText('未提供结构裁图')).toBeVisible();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('filters displayed metrics without inventing activities', () => {
    render(<ResultsTable {...tableProps()} metrics={['IC50']} />);
    expect(screen.getByLabelText('IC50 该指标无数据')).toHaveTextContent('—');
    expect(screen.queryByTitle('抑制等级 = ++')).not.toBeInTheDocument();
  });
  it('maps target/confidence/review filters to the contract', () => {
    const onChange = vi.fn();
    render(
      <ResultFilters
        filters={{ q: '', confidence: '', review: '', target: '', page: 3, page_size: 10 }}
        targets={results.targets}
        onChange={onChange}
        disabled={false}
      />,
    );
    fireEvent.change(screen.getByLabelText('筛选靶点'), { target: { value: '测试靶点' } });
    expect(onChange).toHaveBeenLastCalledWith({ target: '测试靶点', page: 1 });
    fireEvent.change(screen.getByLabelText('筛选绑定证据'), { target: { value: 'unknown' } });
    expect(onChange).toHaveBeenLastCalledWith({ confidence: 'unknown', page: 1 });
    fireEvent.change(screen.getByLabelText('筛选复核状态'), { target: { value: 'needs_review' } });
    expect(onChange).toHaveBeenLastCalledWith({ review: 'needs_review', page: 1 });
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
    expect(screen.getAllByText('—')).toHaveLength(6);
    expect(screen.getAllByText('等待项目数据')).toHaveLength(6);
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
    expect(screen.queryByRole('tab', { name: '分子分析 · ADMET' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出结果' })).toBeDisabled();
  });
});
