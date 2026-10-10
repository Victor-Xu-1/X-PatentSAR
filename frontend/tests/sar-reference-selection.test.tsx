import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { setLocale } from '../src/i18n';
import { MoleculeBrowser } from '../src/features/sar/MoleculeBrowser';
import { RegionSelector } from '../src/features/sar/RegionSelector';
import { StudyRegionEditor } from '../src/features/sar/study/StudyRegionEditor';
import { DatasetWorkbench } from '../src/features/sar/DatasetWorkbench';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { namedRegion, sarDataset, sarDrawing, sarMolecule, studyProfile } from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'molecules').mockResolvedValue({
    items: [sarMolecule],
    total: 1,
    page: 1,
    page_size: 50,
  });
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
  vi.spyOn(sarApi, 'jobs').mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
});

async function chooseReference() {
  await userEvent.click(screen.getByText('Add a named selection', { exact: true }));
  await userEvent.click(await screen.findByRole('button', { name: 'Reference' }));
  const panel = screen.getByRole('region', { name: 'Select variable region' });
  fireEvent.load(await within(panel).findByRole('img', { name: 'RDKit reference drawing' }));
  return panel;
}

describe('reference selection work area', () => {
  it('keeps raw source details on demand, without changing the original row header', async () => {
    render(
      <MoleculeBrowser active dataset={sarDataset} referenceId={null} onReference={vi.fn()} />,
    );
    await screen.findByRole('rowheader', { name: sarMolecule.label });
    expect(screen.getByText(sarMolecule.smiles!)).not.toBeVisible();
    await userEvent.click(screen.getByText('Source details', { selector: 'summary', exact: true }));
    expect(screen.getByText(sarMolecule.smiles!)).toBeVisible();
    expect(screen.getByRole('rowheader', { name: sarMolecule.label })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Original page 8' })).toHaveAttribute(
      'href',
      expect.stringContaining('page=8'),
    );
  });
  it('reveals the selected work area rather than leaving it below the full source list', async () => {
    const save = vi.spyOn(sarApi, 'saveRegion');
    render(
      <StudyRegionEditor
        active
        disabled={false}
        scope="selection"
        dataset={sarDataset}
        regions={[]}
        onSaved={vi.fn()}
      />,
    );
    const panel = await chooseReference();
    expect(screen.queryByRole('region', { name: 'Choose reference molecule' })).toBeNull();
    expect(panel).toHaveFocus();
    expect(within(panel).getByRole('button', { name: 'Atom 1 (O)' })).toBeEnabled();
    expect(save).not.toHaveBeenCalled();
  });
  it('preserves unsaved atoms, name and search when changing reference is cancelled or the locale changes', async () => {
    render(
      <StudyRegionEditor
        active
        disabled={false}
        scope="selection"
        dataset={sarDataset}
        regions={[]}
        onSaved={vi.fn()}
      />,
    );
    const panel = await chooseReference();
    await userEvent.clear(within(panel).getByLabelText('Selection name'));
    await userEvent.type(within(panel).getByLabelText('Selection name'), '用户 draft');
    await userEvent.click(within(panel).getByRole('button', { name: 'Atom 1 (O)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Change reference' }));
    const browser = screen.getByRole('region', { name: 'Choose reference molecule' });
    await userEvent.type(within(browser).getByLabelText('Search identifiers or SMILES'), '007B');
    await waitFor(() =>
      expect(sarApi.molecules).toHaveBeenLastCalledWith(
        sarDataset.id,
        1,
        '007B',
        expect.any(AbortSignal),
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Return to selection' }));
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('区域名称')).toHaveValue('用户 draft');
    expect(screen.getByRole('button', { name: '原子 1（O）' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', { name: '更换参考' }));
    expect(screen.getByLabelText('搜索编号或 SMILES')).toHaveValue('007B');
    expect(screen.getByRole('rowheader', { name: sarMolecule.label })).toBeVisible();
  });
  it('does not paint saved overlays by default and keeps their original atoms available on demand', async () => {
    const { container } = render(
      <RegionSelector
        active
        dataset={sarDataset}
        reference={sarMolecule}
        highlights={[namedRegion]}
        onRegion={vi.fn()}
      />,
    );
    fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
    expect(container.querySelector('.sar-region-map')).toBeNull();
    const original = screen.getByRole('button', { name: 'Atom 1 (O)' });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show saved selections' }));
    expect(container.querySelector('.sar-region-map [data-region-id]')).toHaveAttribute(
      'data-region-id',
      namedRegion.id,
    );
    expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBe(original);
    expect(original).toHaveStyle({ left: '50%', top: '50%' });
    await userEvent.click(original);
    expect(original).toHaveAttribute('aria-pressed', 'true');
  });
  it('uses the same explicit reference workspace for the advanced consumer', async () => {
    render(
      <DatasetWorkbench
        active
        datasetId={sarDataset.id}
        jobId={null}
        onJob={vi.fn()}
        onRemoved={vi.fn()}
      />,
    );
    await screen.findByText('Single-reference comparison (advanced)');
    await userEvent.click(screen.getByText('Single-reference comparison (advanced)'));
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    await userEvent.click(await screen.findByRole('button', { name: 'Reference' }));
    const panel = screen.getByRole('region', { name: 'Select variable region' });
    fireEvent.load(await within(panel).findByRole('img', { name: 'RDKit reference drawing' }));
    expect(panel).toHaveFocus();
    expect(screen.queryByRole('region', { name: 'Choose reference molecule' })).toBeNull();
  });
  it('settles the explicit canvas once and does not replay navigation on refresh, inactivity or locale', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockClear();
    const props = {
      dataset: sarDataset,
      reference: sarMolecule,
      onRegion: vi.fn(),
      revealRequest: 1,
    };
    const { rerender, container } = render(<RegionSelector active {...props} />);
    const panel = screen.getByRole('region', { name: 'Select variable region' });
    expect(panel).toHaveFocus();
    fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
    expect(scroll.mock.contexts).toEqual([panel, container.querySelector('.sar-drawing')]);
    rerender(<RegionSelector active={false} {...props} />);
    rerender(<RegionSelector active {...props} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeEnabled());
    await act(() => setLocale('zh-CN'));
    expect(scroll).toHaveBeenCalledTimes(2);
  });
  it('does not steal focus or scroll when an asynchronous canvas loads after the user moves on', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockClear();
    render(
      <>
        <RegionSelector
          active
          dataset={sarDataset}
          reference={sarMolecule}
          revealRequest={1}
          onRegion={vi.fn()}
        />
        <button type="button">Other task</button>
      </>,
    );
    const other = screen.getByRole('button', { name: 'Other task' });
    other.focus();
    fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
    expect(other).toHaveFocus();
    expect(scroll).toHaveBeenCalledOnce();
  });
});
