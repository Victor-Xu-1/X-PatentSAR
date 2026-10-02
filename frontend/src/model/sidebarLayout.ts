export interface SidebarLayout {
  width: number;
  collapsed: boolean;
}

export const collapsedSidebarWidth = 56;
export const sidebarCollapseThreshold = 128;
export const defaultSidebarLayout: SidebarLayout = { width: 232, collapsed: false };

export function normalizeSidebarLayout(value: Partial<SidebarLayout> = {}): SidebarLayout {
  return {
    width:
      typeof value.width === 'number' && Number.isFinite(value.width)
        ? Math.min(360, Math.max(184, Math.round(value.width)))
        : defaultSidebarLayout.width,
    collapsed: typeof value.collapsed === 'boolean' ? value.collapsed : false,
  };
}

export function resizeSidebar(layout: SidebarLayout, width: number): SidebarLayout {
  if (!Number.isFinite(width)) return normalizeSidebarLayout(layout);
  return width <= sidebarCollapseThreshold
    ? { ...normalizeSidebarLayout(layout), collapsed: true }
    : normalizeSidebarLayout({ width, collapsed: false });
}

export function sidebarDisplayWidth(layout: SidebarLayout): number {
  return layout.collapsed ? collapsedSidebarWidth : layout.width;
}
