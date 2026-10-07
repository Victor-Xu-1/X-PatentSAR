export interface LayoutState {
  pdfWidth: number;
  pdfVisible: boolean;
  fullscreen: boolean;
}
export const defaultLayout: LayoutState = { pdfWidth: 34, pdfVisible: true, fullscreen: false };
export function normalizeLayout(value: Partial<LayoutState> = {}): LayoutState {
  const width = value.pdfWidth;
  return {
    pdfWidth:
      typeof width === 'number' && Number.isFinite(width)
        ? Math.min(55, Math.max(20, Math.round(width)))
        : defaultLayout.pdfWidth,
    pdfVisible: typeof value.pdfVisible === 'boolean' ? value.pdfVisible : true,
    fullscreen: typeof value.fullscreen === 'boolean' ? value.fullscreen : false,
  };
}
