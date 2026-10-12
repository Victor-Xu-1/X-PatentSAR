import { expect, it, vi } from 'vitest';
import { matrixScrollStops, moveMatrix } from '../src/features/sar/study/matrixScrolling';

function geometry(frozen: number, lefts: number[], maximum: number) {
  const pane = document.createElement('div'),
    table = document.createElement('table');
  const row = table.createTHead().insertRow();
  for (let index = 0; index < lefts.length + 2; index++) row.insertCell();
  const cells = [...row.cells];
  cells[1]!.className = 'sar-matrix-baseline';
  Object.defineProperties(pane, {
    scrollWidth: { value: maximum + 400 },
    clientWidth: { value: 400 },
  });
  pane.scrollLeft = 0;
  cells[0]!.getBoundingClientRect = () => ({ right: frozen }) as DOMRect;
  cells[1]!.getBoundingClientRect = () => ({ right: frozen }) as DOMRect;
  cells[1]!.style.position = 'static';
  lefts.forEach((left, index) => {
    cells[index + 2]!.getBoundingClientRect = () => ({ left }) as DOMRect;
  });
  pane.scrollTo = vi.fn();
  return { pane, table };
}

it('aligns each next candidate with the actual frozen edge instead of a viewport fraction', () => {
  const { pane, table } = geometry(110, [330, 550, 770], 700);
  expect(matrixScrollStops(pane, table)).toEqual([0, 220, 440, 660, 700]);
  moveMatrix(pane, table, 1);
  expect(pane.scrollTo).toHaveBeenCalledWith({ left: 220, behavior: expect.any(String) });
});

it('handles duplicate/clamped end positions and does not move past the end', () => {
  const { pane, table } = geometry(110, [110, 150, 950], 70);
  expect(matrixScrollStops(pane, table)).toEqual([0, 40, 70]);
  pane.scrollLeft = 70;
  for (const cell of [...table.tHead!.rows[0]!.cells].slice(2)) {
    const left = cell.getBoundingClientRect().left;
    cell.getBoundingClientRect = () => ({ left: left - 70 }) as DOMRect;
  }
  moveMatrix(pane, table, 1);
  expect(pane.scrollTo).toHaveBeenCalledWith({ left: 70, behavior: expect.any(String) });
  moveMatrix(pane, table, -1);
  expect(pane.scrollTo).toHaveBeenLastCalledWith({ left: 40, behavior: expect.any(String) });
});
