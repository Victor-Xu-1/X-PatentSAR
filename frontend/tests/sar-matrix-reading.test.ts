import { afterEach, expect, it, vi } from 'vitest';
import { matrixReading } from '../e2e/matrix-reading';

const hit = vi.fn();
Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: hit });
afterEach(() => {
  document.body.replaceChildren();
  hit.mockReset();
});

function geometry(scrollLeft: number, candidateLeft: number) {
  const viewport = document.createElement('div');
  viewport.className = 'sar-matrix-viewport';
  const table = document.createElement('table');
  viewport.append(table);
  document.body.append(viewport);
  const header = table.createTHead().insertRow();
  for (let i = 0; i < 3; i++) header.append(document.createElement('th'));
  const cells = [...header.cells];
  cells[1]!.style.position = 'sticky';
  cells[1]!.style.left = '110px';
  cells[2]!.innerHTML = '<button><strong>Original 8A</strong></button>';
  viewport.scrollLeft = scrollLeft;
  Object.defineProperties(viewport, {
    clientWidth: { value: 690 },
    scrollWidth: { value: 1090 },
  });
  viewport.getBoundingClientRect = () => ({ left: 0, right: 690 }) as DOMRect;
  cells[0]!.getBoundingClientRect = () => ({ right: 110 }) as DOMRect;
  cells[1]!.getBoundingClientRect = () => ({ right: 350 }) as DOMRect;
  cells[2]!.getBoundingClientRect = () =>
    ({ left: candidateLeft, right: candidateLeft + 220, width: 220 }) as DOMRect;
  const label = cells[2]!.querySelector('strong')!;
  label.getBoundingClientRect = () =>
    ({ x: candidateLeft + 80, y: 50, width: 60, height: 20 }) as DOMRect;
  hit.mockReturnValue(label);
  return table;
}

it('does not accept a readable header while smooth movement is still between columns', () => {
  const state = matrixReading(geometry(10, 500));
  expect(state.scrollLeft).toBeGreaterThan(0);
  expect(state.readable).toBe(true);
  expect(state.atBoundary).toBe(false);
});

it('accepts physical original IDs after alignment or the bounded end stop', () => {
  for (const [left, candidate] of [
    [220, 350],
    [400, 330],
  ]) {
    const state = matrixReading(geometry(left!, candidate!));
    expect(state.atBoundary).toBe(true);
    expect(state.visible).toEqual([{ id: 'Original 8A', readable: true }]);
    expect(state.readable).toBe(true);
  }
});

it('still refuses an aligned ID covered by another painted element', () => {
  const table = geometry(220, 350);
  hit.mockReturnValue(document.createElement('aside'));
  const state = matrixReading(table);
  expect(state.atBoundary).toBe(true);
  expect(state.readable).toBe(false);
});
