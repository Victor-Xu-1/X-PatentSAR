import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { StudyRegionMap } from '../src/features/sar/study/StudyRegionMap';
import { setLocale } from '../src/i18n';
import { catalogBody } from './sar-catalog-fixtures';
import { sarDrawing } from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarStudyApi, 'drawing').mockRejectedValue(new Error('No second drawing read allowed'));
});

it('magnifies the same qualified reference without replacing its atomic overlay or making another read', async () => {
  const report = catalogBody().report,
    select = vi.fn();
  const before = JSON.stringify(report);
  const view = render(<StudyRegionMap report={report} active onSelect={select} />);
  const label = report.regions[0]!.reference_label;
  const image = await screen.findByRole('img', { name: label });
  fireEvent.load(image);
  const opener = screen.getByRole('button', { name: 'Enlarge structure ' + label });
  await userEvent.click(opener);
  const dialog = screen.getByRole('dialog', { name: 'Molecular preview · ' + label });
  expect(within(dialog).getByRole('img', { name: label })).toHaveAttribute(
    'src',
    image.getAttribute('src'),
  );
  await userEvent.click(within(dialog).getByRole('button', { name: 'Zoom in structure' }));
  expect(within(dialog).getByLabelText('Magnification relative to fit')).toHaveTextContent('125%');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('dialog', { name: '结构预览 · ' + label })).toBe(dialog);
  fireEvent(dialog, new Event('cancel', { cancelable: true }));
  expect(opener).toHaveFocus();
  expect(view.container.querySelectorAll('.sar-region-hotspots > button')).toHaveLength(1);
  expect(sarApi.drawing).toHaveBeenCalledOnce();
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
  expect(JSON.stringify(report)).toBe(before);
});

it('does not open before the image loads and closes when the reference becomes inactive', async () => {
  const report = catalogBody().report;
  const view = render(<StudyRegionMap report={report} active onSelect={vi.fn()} />);
  const label = report.regions[0]!.reference_label;
  const image = await screen.findByRole('img', { name: label });
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  fireEvent.load(image);
  await userEvent.click(screen.getByRole('button', { name: 'Enlarge structure ' + label }));
  view.rerender(<StudyRegionMap report={report} active={false} onSelect={vi.fn()} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
});

it('binds atomic overlays to the loaded image and removes them after an image failure', async () => {
  const report = catalogBody().report;
  const select = vi.fn();
  const view = render(<StudyRegionMap report={report} active onSelect={select} />);
  const image = await screen.findByRole('img', { name: report.regions[0]!.reference_label });
  expect(view.container.querySelector('.sar-region-map')).toBeNull();
  expect(view.container.querySelector('.sar-region-hotspots')).toBeNull();
  fireEvent.load(image);
  const atom = sarDrawing.atoms.find((item) =>
    report.regions[0]!.region.atom_indices.includes(item.index),
  )!;
  const marker = view.container.querySelector('.sar-region-map circle');
  expect(marker).toHaveAttribute('cx', String(atom.x * 1000));
  expect(marker).toHaveAttribute('cy', String(atom.y * 800));
  expect(view.container.querySelector('.sar-region-hotspots')).not.toBeNull();
  await userEvent.click(screen.getByRole('button', { name: /Enlarge structure/ }));
  fireEvent.error(image);
  expect(screen.getByRole('alert')).toHaveTextContent('RDKit drawing could not be loaded.');
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(view.container.querySelector('.sar-region-map')).toBeNull();
  expect(view.container.querySelector('.sar-region-hotspots')).toBeNull();
  expect(select).not.toHaveBeenCalled();
});

it('disposes an overlapping-region chooser when its source image fails', async () => {
  const source = catalogBody().report;
  const first = source.regions[0]!;
  const report = {
    ...source,
    regions: [
      first,
      { ...first, region: { ...first.region, id: 'other-region', name: 'Other original region' } },
    ],
  };
  const select = vi.fn();
  const view = render(<StudyRegionMap report={report} active onSelect={select} />);
  const image = await screen.findByRole('img', { name: first.reference_label });
  fireEvent.load(image);
  await userEvent.click(
    view.container.querySelector<HTMLButtonElement>('.sar-region-hotspots button')!,
  );
  expect(screen.getByRole('dialog')).toBeVisible();
  fireEvent.error(image);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(view.container.querySelector('.sar-region-hotspots')).toBeNull();
  expect(select).not.toHaveBeenCalled();
});

it.each(['graph', 'markup', 'image'])(
  'withholds reference magnification after %s failure',
  async (failure) => {
    if (failure === 'graph')
      vi.mocked(sarApi.drawing).mockResolvedValue({
        ...sarDrawing,
        molecule: { ...sarDrawing.molecule, graph_sha256: 'f'.repeat(64) },
      });
    if (failure === 'markup')
      vi.mocked(sarApi.drawing).mockResolvedValue({
        ...sarDrawing,
        svg: '<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>',
      });
    const report = catalogBody().report;
    render(<StudyRegionMap report={report} active onSelect={vi.fn()} />);
    if (failure === 'image') fireEvent.error(await screen.findByRole('img'));
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: /Enlarge structure/ })).not.toBeInTheDocument();
  },
);
