/** Physical hit-test after native scrolling, not merely DOM visibility. */
export function matrixReading(table: HTMLTableElement) {
  const viewport = table.closest('.sar-matrix-viewport')!;
  const pane = viewport.getBoundingClientRect();
  const cells = [...table.querySelectorAll<HTMLTableCellElement>('thead th')];
  const reference = cells[1]!;
  const style = getComputedStyle(reference);
  const frozen =
    style.position === 'sticky' && style.left !== 'auto'
      ? reference.getBoundingClientRect().right
      : cells[0]!.getBoundingClientRect().right;
  const candidates = cells.slice(2);
  const atBoundary =
    Math.abs(viewport.scrollLeft - (viewport.scrollWidth - viewport.clientWidth)) <= 1 ||
    candidates.some((cell) => Math.abs(cell.getBoundingClientRect().left - frozen) <= 1);
  const visible = candidates.flatMap((cell) => {
    const box = cell.getBoundingClientRect();
    const width = Math.max(0, Math.min(box.right, pane.right) - Math.max(box.left, frozen));
    if (width < box.width / 2) return [];
    const label = cell.querySelector('strong')!;
    const rect = label.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    return [{ id: label.textContent, readable: !!hit && label.closest('button')!.contains(hit) }];
  });
  return {
    scrollLeft: viewport.scrollLeft,
    atBoundary,
    visible,
    readable: visible.length > 0 && visible.every((item) => item.readable),
  };
}
