import { preferredScrollBehavior } from '../../../model/motion';

/** Column-aware native scrolling, with no data order, focus or identity changes. */
export function matrixScrollStops(pane: HTMLElement, table: HTMLTableElement): number[] {
  const header = table.tHead?.rows[0];
  if (!header) return [0];
  const cells = [...header.cells],
    first = cells[0],
    reference = cells[1];
  if (!first || !reference) return [0];
  const style = getComputedStyle(reference);
  const frozenEdge =
    style.position === 'sticky' && style.left !== 'auto'
      ? reference.getBoundingClientRect().right
      : first.getBoundingClientRect().right;
  const maximum = Math.max(0, pane.scrollWidth - pane.clientWidth);
  return [
    ...new Set([
      0,
      maximum,
      ...cells
        .slice(2)
        .map((cell) =>
          Math.max(
            0,
            Math.min(maximum, pane.scrollLeft + cell.getBoundingClientRect().left - frozenEdge),
          ),
        ),
    ]),
  ].toSorted((a, b) => a - b);
}

export function moveMatrix(pane: HTMLElement, table: HTMLTableElement, direction: -1 | 1) {
  const stops = matrixScrollStops(pane, table);
  const target =
    direction === 1
      ? (stops.find((value) => value > pane.scrollLeft + 1) ?? stops.at(-1)!)
      : (stops.toReversed().find((value) => value < pane.scrollLeft - 1) ?? 0);
  pane.scrollTo({ left: target, behavior: preferredScrollBehavior() });
}
