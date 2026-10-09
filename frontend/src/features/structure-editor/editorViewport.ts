import type { Ketcher } from 'ketcher-core';

/** Fit the view only. Never move atoms, relayout, export, or canonicalize a graph. */
export function fitEditorViewport(instance: Ketcher) {
  const editor = instance.editor,
    render = editor.render,
    structure = editor.struct();
  if (!structure.atoms.size) return false;
  const area = render.clientArea.getBoundingClientRect();
  const bounds = structure.getCoordBoundingBox();
  const spanX = bounds.max.x - bounds.min.x,
    spanY = bounds.max.y - bounds.min.y;
  const scale = render.options.microModeScale;
  if (
    ![area.width, area.height, scale, bounds.min.x, bounds.min.y, spanX, spanY].every(
      Number.isFinite,
    ) ||
    area.width <= 64 ||
    area.height <= 64 ||
    scale <= 0 ||
    spanX < 0 ||
    spanY < 0
  )
    return false;
  const zoom = Math.max(
    0.1,
    Math.min(
      1,
      spanX > 0 ? (area.width - 64) / (spanX * scale) : 1,
      spanY > 0 ? (area.height - 64) / (spanY * scale) : 1,
    ),
  );
  editor.zoom(zoom);
  // The pinned renderer's canvas coordinates use microModeScale; zoom changes
  // the viewBox, not molecule coordinates. No SDK graph mutator is involved.
  const centerX = (bounds.min.x + spanX / 2) * scale;
  const centerY = (bounds.min.y + spanY / 2) * scale;
  render.setViewBox((view) => ({
    ...view,
    minX: centerX - view.width / 2,
    minY: centerY - view.height / 2,
  }));
  return true;
}

/** One frame per actual size change; drawing, panning and zooming do not refit. */
export function observeEditorViewport(instance: Ketcher) {
  let pending = 0,
    disposed = false;
  const schedule = () => {
    if (disposed) return;
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => {
      if (!disposed) fitEditorViewport(instance);
    });
  };
  const observer = new ResizeObserver(schedule);
  observer.observe(instance.editor.render.clientArea);
  schedule();
  return () => {
    disposed = true;
    observer.disconnect();
    cancelAnimationFrame(pending);
  };
}
