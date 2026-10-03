import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { EvidencePanel } from '../src/features/analysis/EvidencePanel';
import { CropDialog } from '../src/features/results/CropDialog';
import { compound, project } from './fixtures';
import { evidence } from './analysis-fixtures';

describe('automatic analysis has no competing manual workspace', () => {
  it('presents original and computed evidence without starting models just by opening details', () => {
    const recognize = vi.spyOn(api, 'recognize');
    const admet = vi.spyOn(api, 'admet');
    render(<CropDialog projectId={project.id} compound={compound} onClose={vi.fn()} />);
    expect(screen.queryByRole('button', { name: '运行本地 ADMET' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '识别真实裁图（DECIMER + QC）' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('六项指标 · 未计算')).toBeVisible();
    expect(recognize).not.toHaveBeenCalled();
    expect(admet).not.toHaveBeenCalled();
  });
});
describe('source-grounded same-project deterministic evidence', () => {
  it('retains incomparable units/targets, source pages and historical acceptance', async () => {
    const historical = { ...project, acceptance: { state: 'historical' as const, errors: [] } };
    const get = vi
      .spyOn(api, 'evidenceSummary')
      .mockResolvedValue({ ...evidence, acceptance: historical.acceptance });
    const source = vi.fn();
    render(<EvidencePanel project={historical} available onSource={source} />);
    await screen.findByText('µM');
    expect(get).toHaveBeenCalledWith(project.id, expect.any(AbortSignal));
    expect(screen.getByText('nM')).toBeVisible();
    expect(screen.getByText(/确定性证据统计/)).toBeVisible();
    expect(screen.getByText(/不是 LLM/)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '查看来源第 4 页' }));
    expect(source).toHaveBeenCalledWith(4);
    expect(project.acceptance.state).toBe('not_run');
  });
  it('has explicit empty-project and capability failures, with no fabricated summary', async () => {
    const { rerender } = render(<EvidencePanel project={null} available onSource={vi.fn()} />);
    expect(screen.getByText('请选择项目以读取证据摘要')).toBeVisible();
    vi.spyOn(api, 'evidenceSummary').mockRejectedValue(
      new ApiError(503, 'unavailable', '摘要服务不可用'),
    );
    rerender(<EvidencePanel project={project} available={false} onSource={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('摘要服务不可用');
    expect(screen.queryByText('µM')).not.toBeInTheDocument();
  });
});
