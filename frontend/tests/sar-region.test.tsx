import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { setLocale } from '../src/i18n';
import { RegionSelector } from '../src/features/sar/RegionSelector';
import { AnalysisForm } from '../src/features/sar/AnalysisForm';
import { sarDataset, sarDrawing, sarJob, sarMolecule, sarRegion } from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
});
describe('server-owned graph atom selection', () => {
  it('uses the actual passive SVG canvas and exact atom positions/indices, with visible persistent selection', async () => {
    const save = vi.spyOn(sarApi, 'saveRegion').mockResolvedValue(sarRegion);
    const selected = vi.fn();
    const { container } = render(
      <RegionSelector active dataset={sarDataset} reference={sarMolecule} onRegion={selected} />,
    );
    const image = await screen.findByRole('img', { name: 'RDKit reference drawing' });
    expect(image).toHaveAttribute('src', expect.stringContaining('data:image/svg+xml'));
    expect(container.querySelector('.sar-drawing svg')).toBeNull();
    expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeDisabled();
    fireEvent.load(image);
    const atom = screen.getByRole('button', { name: 'Atom 1 (O)' });
    expect(atom).toHaveStyle({ left: '50%', top: '50%' });
    await userEvent.click(atom);
    expect(atom).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Selected atoms: 1')).toBeVisible();
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('button', { name: '原子 1（O）' })).toBe(atom);
    expect(atom).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: '保存区域' }));
    await waitFor(() => expect(selected).toHaveBeenLastCalledWith(sarRegion));
    expect(save).toHaveBeenCalledExactlyOnceWith(sarDataset.id, {
      molecule_id: sarMolecule.id,
      expected_dataset_revision: 2,
      expected_graph_sha256: sarMolecule.graph_sha256,
      atom_indices: [1],
    });
    expect(screen.getByText('区域已保存 · 1 个连接点')).toBeVisible();
    expect(screen.getByRole('link', { name: '原文第 8 页' })).toHaveAttribute(
      'href',
      expect.stringContaining('page=8'),
    );
  });
  it('invalidates the saved region when selection changes, without an automatic region POST', async () => {
    const save = vi.spyOn(sarApi, 'saveRegion').mockResolvedValue(sarRegion);
    const selected = vi.fn();
    render(
      <RegionSelector active dataset={sarDataset} reference={sarMolecule} onRegion={selected} />,
    );
    fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
    await userEvent.click(screen.getByRole('button', { name: 'Atom 1 (O)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
    await screen.findByText('Region saved · 1 attachment points');
    await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C)' }));
    expect(selected).toHaveBeenLastCalledWith(null);
    expect(save).toHaveBeenCalledOnce();
  });
  it('fails closed for stale snapshots, foreign graph identity and image load failure', async () => {
    vi.spyOn(sarApi, 'drawing').mockResolvedValue({
      ...sarDrawing,
      molecule: { ...sarMolecule, graph_sha256: '0'.repeat(64) },
    });
    render(
      <RegionSelector active dataset={sarDataset} reference={sarMolecule} onRegion={vi.fn()} />,
    );
    const image = await screen.findByRole('img', { name: 'RDKit reference drawing' });
    fireEvent.load(image);
    expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeDisabled();
    expect(screen.getByText(/The graph or revision changed/)).toBeVisible();
    fireEvent.error(image);
    expect(screen.getByText('The RDKit drawing could not be loaded.')).toBeVisible();
  });
  it('blocks malicious SVG even from an otherwise valid DTO', async () => {
    vi.spyOn(sarApi, 'drawing').mockResolvedValue({
      ...sarDrawing,
      svg: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><foreignObject/></svg>',
    });
    render(
      <RegionSelector active dataset={sarDataset} reference={sarMolecule} onRegion={vi.fn()} />,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsafe or invalid SVG');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save region' })).toBeDisabled();
  });
});
describe('explicit reference-comparison submission', () => {
  it('requires saved region, metric and direction; sends no guessed grades or default confirmation', async () => {
    const analyse = vi.spyOn(sarApi, 'analyse').mockResolvedValue(sarJob);
    const onJob = vi.fn();
    const { rerender } = render(
      <AnalysisForm dataset={sarDataset} region={null} busy={false} onJob={onJob} />,
    );
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    rerender(<AnalysisForm dataset={sarDataset} region={sarRegion} busy={false} onJob={onJob} />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
    await userEvent.click(screen.getByRole('button', { name: 'Start reference comparison' }));
    await waitFor(() => expect(onJob).toHaveBeenCalledWith(sarJob));
    expect(analyse.mock.calls[0]?.[1]).toEqual({
      request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
      expected_dataset_revision: 2,
      region_id: sarRegion.id,
      metric_id: 'metric-control',
      direction: 'lower',
      grade_order: [],
      confirm_context: false,
    });
  });
  it('preserves explicit strongest-first grade drafts and limits confirmation to missing conditions', async () => {
    const analyse = vi.spyOn(sarApi, 'analyse').mockResolvedValue(sarJob);
    render(<AnalysisForm dataset={sarDataset} region={sarRegion} busy={false} onJob={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'higher');
    const grades = screen.getByRole('textbox', { name: /Grade order/ });
    await userEvent.type(grades, 'strongest\nweaker');
    await userEvent.click(
      screen.getByRole('checkbox', { name: /Known differences still prevent/ }),
    );
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('textbox', { name: /等级顺序/ })).toBe(grades);
    expect(grades).toHaveValue('strongest\nweaker');
    await userEvent.click(screen.getByRole('button', { name: '开始参考比较' }));
    await waitFor(() => expect(analyse).toHaveBeenCalledOnce());
    expect(analyse.mock.calls[0]?.[1]).toMatchObject({
      direction: 'higher',
      grade_order: ['strongest', 'weaker'],
      confirm_context: true,
    });
  });
  it('blocks stale/mismatched region revisions and duplicate grades', async () => {
    const { rerender } = render(
      <AnalysisForm
        dataset={{ ...sarDataset, stale: true }}
        region={sarRegion}
        busy={false}
        onJob={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('Activity direction')).toBeDisabled();
    rerender(
      <AnalysisForm
        dataset={sarDataset}
        region={{ ...sarRegion, dataset_revision: 1 }}
        busy={false}
        onJob={vi.fn()}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
    await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    await userEvent.type(screen.getByRole('textbox', { name: /Grade order/ }), 'A\nA');
    expect(screen.getByRole('alert')).toHaveTextContent('32 distinct grades');
  });
});
