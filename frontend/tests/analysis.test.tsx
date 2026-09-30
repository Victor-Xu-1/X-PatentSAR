import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { AdmetPanel } from '../src/features/analysis/AdmetPanel';
import { EvidencePanel } from '../src/features/analysis/EvidencePanel';
import { CropDialog } from '../src/features/results/CropDialog';
import { parseSmiles } from '../src/model/analysis';
import { compound, project } from './fixtures';
import { admet, evidence, recognized } from './analysis-fixtures';

describe('bounded molecule inputs and real analysis request presentation', () => {
  it('does not replay uncertain analysis and requires the bounded wait plus explicit acknowledgement', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    const user = userEvent.setup();
    const run = vi
      .spyOn(api, 'admet')
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '连接中断，结果未知', true))
      .mockResolvedValueOnce(admet);
    render(<AdmetPanel initialSmiles="CCO" available />);
    await user.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    expect(screen.getByRole('alert')).toHaveTextContent('结果未知');
    expect(screen.getByRole('button', { name: '运行本地 ADMET' })).toBeDisabled();
    const confirm = screen.getByRole('button', { name: '已等待边界，重新允许手动分析' });
    expect(confirm).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(190_000));
    expect(run).toHaveBeenCalledOnce();
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await user.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    expect(run).toHaveBeenCalledTimes(2);
    expect(screen.getByText('46.069')).toBeVisible();
  });
  it('accepts line-separated molecules, keeps SMILES punctuation and rejects bounds', () => {
    expect(parseSmiles(' CCO\n\nC[C@H](N)C(=O)O\r\n')).toEqual(['CCO', 'C[C@H](N)C(=O)O']);
    expect(() => parseSmiles('')).toThrow('输入');
    expect(() => parseSmiles(Array(51).fill('CCO').join('\n'))).toThrow('50');
    expect(() => parseSmiles('CCO name')).toThrow('空白');
  });
  it('submits actual typed SMILES, displays engine/units and never mutates core data', async () => {
    const run = vi.spyOn(api, 'admet').mockResolvedValue(admet);
    const review = vi.spyOn(api, 'review');
    render(<AdmetPanel available />);
    await userEvent.type(screen.getByLabelText('SMILES（每行一个，最多 50 个）'), 'CCO\nCCN');
    await userEvent.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    await waitFor(() => expect(run).toHaveBeenCalledWith(['CCO', 'CCN'], expect.any(AbortSignal)));
    expect(await screen.findByText('46.069')).toBeVisible();
    expect(screen.getByText('g/mol')).toBeVisible();
    expect(screen.getByText('RDKit 描述符')).toBeVisible();
    expect(screen.getByText(/ADMET-AI · 2/)).toBeVisible();
    expect(screen.getByText(/不改变正式提取/)).toBeVisible();
    expect(review).not.toHaveBeenCalled();
  });
  it('shows loading, prevents double submission and clears stale success on failure', async () => {
    let resolve!: (value: typeof admet) => void;
    const run = vi
      .spyOn(api, 'admet')
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      )
      .mockRejectedValueOnce(new ApiError(503, 'analysis_unavailable', '模型环境不可用'));
    render(<AdmetPanel available initialSmiles="CCO" />);
    await userEvent.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    expect(screen.getByLabelText('SMILES（每行一个，最多 50 个）')).toBeDisabled();
    await screen.findByText('正在执行本地分子分析…');
    resolve(admet);
    await screen.findByText('46.069');
    await userEvent.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('模型环境不可用');
    expect(screen.queryByText('46.069')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '检查环境管理' })).toHaveAttribute(
      'href',
      '#/settings',
    );
    expect(run).toHaveBeenCalledTimes(2);
  });
  it('keeps input available even if ADMET capability is absent and exposes an actual error path', async () => {
    vi.spyOn(api, 'admet').mockRejectedValue(new ApiError(503, 'unavailable', 'ADMET 环境未配置'));
    render(<AdmetPanel available={false} />);
    expect(screen.getByLabelText('SMILES（每行一个，最多 50 个）')).toBeEnabled();
    await userEvent.type(screen.getByLabelText('SMILES（每行一个，最多 50 个）'), 'CCO');
    await userEvent.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('ADMET 环境未配置');
  });
});

describe('actual crop recognition and isolated downstream analysis', () => {
  it('locks modal close during actual pending recognition and explains its bounded wait', async () => {
    let finish!: (value: typeof recognized) => void;
    vi.spyOn(api, 'recognize').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const close = vi.fn();
    render(<CropDialog projectId={project.id} compound={compound} onClose={close} />);
    await userEvent.click(screen.getByRole('button', { name: '识别真实裁图（DECIMER + QC）' }));
    expect(screen.getByLabelText('关闭对话框')).toBeDisabled();
    expect(screen.getByText(/本地推理与 QC 最长 180 秒/)).toBeVisible();
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(close).not.toHaveBeenCalled();
    await act(async () => {
      finish(recognized);
    });
    expect(screen.getByLabelText('关闭对话框')).toBeEnabled();
    await userEvent.click(screen.getByLabelText('关闭对话框'));
    expect(close).toHaveBeenCalledOnce();
  });
  it('recognizes a real crop before ADMET even when extracted SMILES are absent', async () => {
    const recognize = vi.spyOn(api, 'recognize').mockResolvedValue(recognized);
    const run = vi.spyOn(api, 'admet').mockResolvedValue(admet);
    render(<CropDialog projectId={project.id} compound={compound} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '识别真实裁图（DECIMER + QC）' }));
    await waitFor(() =>
      expect(recognize).toHaveBeenCalledWith(project.id, compound.id, expect.any(AbortSignal)),
    );
    expect(screen.getByLabelText('SMILES（每行一个，最多 50 个）')).toHaveValue('CCO');
    expect(run).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '运行本地 ADMET' }));
    await screen.findByText('46.069');
    expect(compound.smiles).toBeNull();
  });
  it('surfaces QC rejection, preserves manual entry and restores dialog opener focus', async () => {
    vi.spyOn(api, 'recognize').mockResolvedValue({
      ...recognized,
      status: 'rejected',
      smiles: null,
      warnings: ['QC 拒绝识别分子'],
    });
    function Parent() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>裁图</button>
          {open && (
            <CropDialog projectId={project.id} compound={compound} onClose={() => setOpen(false)} />
          )}
        </>
      );
    }
    render(<Parent />);
    await userEvent.click(screen.getByText('裁图'));
    await userEvent.click(screen.getByRole('button', { name: '识别真实裁图（DECIMER + QC）' }));
    expect(await screen.findByText(/QC 拒绝识别分子/)).toBeVisible();
    expect(screen.getByLabelText('SMILES（每行一个，最多 50 个）')).toHaveValue('');
    const dialog = screen.getByRole('dialog');
    fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
    expect(screen.getByText('裁图')).toHaveFocus();
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
