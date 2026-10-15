import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { RegionMap } from '../src/features/sar/study/RegionMap';
import { setLocale } from '../src/i18n';
import { namedRegion } from './sar-fixtures';

const atoms = Array.from({ length: 10 }, (_, index) => ({
  index,
  element: index === 1 ? 'N' : 'C',
  x: (index + 1) / 12,
  y: 0.5,
}));
const dense = atoms.map((atom) => ({
  ...namedRegion,
  id: 'site-' + atom.index,
  name: 'R' + (atom.index + 1),
  atom_indices: [atom.index],
  hydrogen_anchor: null,
}));
const overlapping = [
  { ...namedRegion, id: 'left', name: 'R27 original', atom_indices: [0, 1] },
  { ...namedRegion, id: 'right', name: 'Linker 原文', atom_indices: [0, 2] },
];

beforeEach(() => setLocale('en'));

it('keeps every recorded atom reachable in a dense map without painting all labels', async () => {
  const onSelect = vi.fn(),
    original = JSON.stringify({ atoms, dense });
  const { container } = render(<RegionMap atoms={atoms} regions={dense} onSelect={onSelect} />);
  expect(container.querySelectorAll('.sar-region-label')).toHaveLength(1);
  expect(container.querySelectorAll('.sar-region-hotspots > button')).toHaveLength(10);
  const last = screen.getByRole('button', { name: 'R10 · C 9' });
  await userEvent.click(last);
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(dense[9]!.id);
  expect(JSON.stringify({ atoms, dense })).toBe(original);
});

it('has one hit target per original atom and asks which overlapping region to inspect', async () => {
  const onSelect = vi.fn();
  const { container } = render(
    <RegionMap atoms={atoms} regions={overlapping} onSelect={onSelect} />,
  );
  expect(container.querySelectorAll('.sar-region-hotspots > button')).toHaveLength(3);
  const shared = screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' });
  expect(shared).toHaveAttribute('aria-haspopup', 'dialog');
  await userEvent.click(shared);
  expect(onSelect).not.toHaveBeenCalled();
  const chooser = screen.getByRole('dialog', { name: 'Variable regions · Atom 0 (C)' });
  await userEvent.click(within(chooser).getByRole('button', { name: 'Linker 原文' }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('right');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(shared).toHaveFocus();
});

it('does not substitute a currently selected region for an explicit overlap choice', async () => {
  const onSelect = vi.fn();
  render(<RegionMap atoms={atoms} regions={overlapping} selected="left" onSelect={onSelect} />);
  await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' }));
  const chooser = screen.getByRole('dialog');
  expect(within(chooser).getByRole('button', { name: 'R27 original' })).toHaveFocus();
  expect(onSelect).not.toHaveBeenCalled();
  await userEvent.click(within(chooser).getByRole('button', { name: 'Linker 原文' }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('right');
});

it('retains both original H-anchor and atom-region choices at their shared atom', async () => {
  const hydrogen = {
    ...namedRegion,
    id: 'source-H',
    name: 'R100-H original',
    atom_indices: [],
    hydrogen_anchor: 0,
  };
  const onSelect = vi.fn(),
    regions = [overlapping[0]!, hydrogen];
  const original = JSON.stringify({ atoms, regions });
  render(<RegionMap atoms={atoms} regions={regions} onSelect={onSelect} />);
  await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' }));
  const chooser = screen.getByRole('dialog');
  await userEvent.click(within(chooser).getByRole('button', { name: 'R100-H original · H' }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('source-H');
  expect(JSON.stringify({ atoms, regions })).toBe(original);
});

it('dismisses an overlap chooser without making a selection and restores its exact opener', async () => {
  const onSelect = vi.fn();
  render(<RegionMap atoms={atoms} regions={overlapping} onSelect={onSelect} />);
  const opener = screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' });
  await userEvent.click(opener);
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
  expect(opener).toHaveFocus();
});

it('closes stale choices on original graph change and never resurrects them on return', async () => {
  const onSelect = vi.fn();
  const { rerender } = render(
    <RegionMap atoms={atoms} regions={overlapping} onSelect={onSelect} />,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' }));
  const changed = overlapping.map((region) => ({
    ...region,
    graph_sha256: 'different-original-graph',
  }));
  rerender(<RegionMap atoms={atoms} regions={changed} onSelect={onSelect} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  rerender(<RegionMap atoms={atoms} regions={overlapping} onSelect={onSelect} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
});

it('switches interface language inside an open chooser without rewriting region names or IDs', async () => {
  const onSelect = vi.fn(),
    original = JSON.stringify({ atoms, overlapping });
  render(<RegionMap atoms={atoms} regions={overlapping} onSelect={onSelect} />);
  await userEvent.click(screen.getByRole('button', { name: 'Atom 0 (C) · 2 variable regions' }));
  await act(() => setLocale('zh-CN'));
  const chooser = screen.getByRole('dialog', { name: '变化区域 · 原子 0（C）' });
  await userEvent.click(within(chooser).getByRole('button', { name: 'Linker 原文' }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('right');
  expect(JSON.stringify({ atoms, overlapping })).toBe(original);
});

it('keeps pointer targets out of the repeated keyboard route and read-only maps without controls', () => {
  const { container, rerender } = render(
    <RegionMap atoms={atoms} regions={overlapping} onSelect={vi.fn()} />,
  );
  const targets = [
    ...container.querySelectorAll<HTMLButtonElement>('.sar-region-hotspots > button'),
  ];
  expect(targets).toHaveLength(3);
  expect(targets.every((button) => button.tabIndex === -1)).toBe(true);
  rerender(<RegionMap atoms={atoms} regions={overlapping} />);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('routes a real pointer by the closest original coordinate when adjacent atom hit boxes overlap', () => {
  const closeAtoms = [
    { index: 0, element: 'C', x: 0.5, y: 0.5 },
    { index: 1, element: 'N', x: 0.51, y: 0.5 },
  ];
  const regions = dense.slice(0, 2),
    onSelect = vi.fn();
  const { container } = render(
    <RegionMap atoms={closeAtoms} regions={regions} onSelect={onSelect} />,
  );
  vi.spyOn(
    container.querySelector('.sar-region-hotspots')!,
    'getBoundingClientRect',
  ).mockReturnValue(new DOMRect(0, 0, 100, 80));
  const topmost = screen.getByRole('button', { name: 'R2 · N 1' });
  fireEvent.click(topmost, { clientX: 50, clientY: 40, detail: 1 });
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(regions[0]!.id);
});

it('keeps pixel-indistinguishable original points explicit rather than choosing the last button', async () => {
  const colocated = atoms.slice(0, 2).map((atom) => ({ ...atom, x: 0.5, y: 0.5 }));
  const regions = dense.slice(0, 2),
    onSelect = vi.fn();
  const { container } = render(
    <RegionMap atoms={colocated} regions={regions} onSelect={onSelect} />,
  );
  vi.spyOn(
    container.querySelector('.sar-region-hotspots')!,
    'getBoundingClientRect',
  ).mockReturnValue(new DOMRect(0, 0, 100, 80));
  fireEvent.click(screen.getByRole('button', { name: 'R2 · N 1' }), {
    clientX: 50,
    clientY: 40,
    detail: 1,
  });
  expect(onSelect).not.toHaveBeenCalled();
  const chooser = screen.getByRole('dialog', { name: 'Variable regions · 2 atoms' });
  await userEvent.click(within(chooser).getByRole('button', { name: /^R1$/ }));
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(regions[0]!.id);
});
