import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { RegionLegend, RegionMap } from '../src/features/sar/study/RegionMap';
import { namedRegion } from './sar-fixtures';

const atoms = [
  { index: 0, element: 'C', x: 0.2, y: 0.3 },
  { index: 1, element: 'N', x: 0.4, y: 0.5 },
  { index: 2, element: 'F', x: 0.7, y: 0.8 },
];
const regions = [
  { ...namedRegion, atom_indices: [0, 1] },
  { ...namedRegion, id: 'second-region', name: 'R2 source label', atom_indices: [2] },
];

it('does not add an empty overlay to a reference without recorded regions or atom coordinates', () => {
  const { container, rerender } = render(<RegionMap atoms={atoms} regions={[]} />);
  expect(container).toBeEmptyDOMElement();
  rerender(<RegionMap atoms={[]} regions={regions} />);
  expect(container).toBeEmptyDOMElement();
});

it('emphasizes only the selected recorded region without moving or rewriting atoms', () => {
  const original = JSON.stringify({ atoms, regions });
  const { container, rerender } = render(
    <RegionMap atoms={atoms} regions={regions} selected={regions[0]!.id} />,
  );
  const groups = container.querySelectorAll('g[data-region-id]');
  expect(groups).toHaveLength(2);
  expect(groups[0]).toHaveAttribute('data-selected', 'true');
  expect(groups[0]!.querySelector('circle')).toHaveAttribute('stroke-width', '3');
  expect(groups[1]).not.toHaveAttribute('data-selected');
  expect(groups[1]).toHaveAttribute('opacity', '0.7');
  const points = () =>
    [...container.querySelectorAll('circle')].map((circle) => [
      circle.getAttribute('cx'),
      circle.getAttribute('cy'),
    ]);
  const coordinates = points();
  rerender(<RegionMap atoms={atoms} regions={regions} selected={regions[1]!.id} />);
  expect(container.querySelector('g[data-selected]')).toHaveAttribute(
    'data-region-id',
    regions[1]!.id,
  );
  expect(points()).toEqual(coordinates);
  expect(JSON.stringify({ atoms, regions })).toBe(original);
  rerender(<RegionMap atoms={atoms} regions={regions} selected="another-reference-region" />);
  expect(container.querySelectorAll('g[data-selected]')).toHaveLength(0);
  expect(
    [...container.querySelectorAll('g[data-region-id]')].every(
      (group) => group.getAttribute('opacity') === '1',
    ),
  ).toBe(true);
});

it('keeps every atom clickable while keyboard navigation uses one named control per region', async () => {
  const onSelect = vi.fn();
  const { container } = render(
    <>
      <RegionMap atoms={atoms} regions={regions} selected={regions[0]!.id} onSelect={onSelect} />
      <RegionLegend regions={regions} selected={regions[0]!.id} onSelect={onSelect} />
    </>,
  );
  const hotspots = [
    ...container.querySelectorAll<HTMLButtonElement>('.sar-region-hotspots button'),
  ];
  expect(hotspots).toHaveLength(3);
  expect(hotspots.every((button) => button.tabIndex === -1)).toBe(true);
  await userEvent.tab();
  expect(screen.getByRole('button', { name: regions[0]!.name! })).toHaveFocus();
  await userEvent.tab();
  const second = screen.getByRole('button', { name: regions[1]!.name! });
  expect(second).toHaveFocus();
  await userEvent.keyboard(' ');
  expect(onSelect).toHaveBeenLastCalledWith(regions[1]!.id);
  await userEvent.click(hotspots[1]!);
  expect(onSelect).toHaveBeenLastCalledWith(regions[0]!.id);
});
