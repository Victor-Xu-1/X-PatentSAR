export interface LayoutState {
  pdfWidth: number;
  pdfVisible: boolean;
  fullscreen: boolean;
}
export const defaultLayout: LayoutState = { pdfWidth: 28, pdfVisible: true, fullscreen: false };
export function normalizeLayout(value: Partial<LayoutState> = {}): LayoutState {
  const width = value.pdfWidth;
  return {
    pdfWidth:
      typeof width === 'number' && Number.isFinite(width)
        ? Math.min(55, Math.max(20, Math.round(width)))
        : 28,
    pdfVisible: typeof value.pdfVisible === 'boolean' ? value.pdfVisible : true,
    fullscreen: typeof value.fullscreen === 'boolean' ? value.fullscreen : false,
  };
}
export function resizeFromPointer(x: number, rect: { left: number; width: number }): number | null {
  if (!Number.isFinite(x) || !Number.isFinite(rect.width) || rect.width <= 0) return null;
  return normalizeLayout({ pdfWidth: ((x - rect.left) / rect.width) * 100 }).pdfWidth;
}
