import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
  collapsedSidebarWidth,
  defaultSidebarLayout,
  normalizeSidebarLayout,
  resizeSidebar,
  sidebarDisplayWidth,
} from '../model/sidebarLayout';
import type { SidebarLayout } from '../model/sidebarLayout';
import { ResizeHandle } from './ResizeHandle';

export function AppFrame({
  layout: input,
  narrow,
  menuOpen,
  leading,
  sidebar,
  children,
  onChange,
}: {
  layout?: SidebarLayout | undefined;
  narrow: boolean;
  menuOpen: boolean;
  leading: ReactNode;
  sidebar: (collapsed: boolean) => ReactNode;
  children: ReactNode;
  onChange: (layout: SidebarLayout) => void;
}) {
  const layout = normalizeSidebarLayout(input);
  const [dragPreview, setDragPreview] = useState<{
    width: number;
    origin: SidebarLayout | undefined;
  } | null>(null);
  const preview = !narrow && dragPreview && dragPreview.origin === input ? dragPreview.width : null;
  const displayed = preview === null ? layout : resizeSidebar(layout, preview);
  const collapsed = !narrow && displayed.collapsed;
  const width = narrow ? layout.width : sidebarDisplayWidth(displayed);
  return (
    <div
      className={`app-shell${menuOpen ? ' menu-open' : ''}${collapsed ? ' navigation-collapsed' : ''}`}
      style={{ '--sidebar-width': `${width}px` } as CSSProperties}
    >
      {leading}
      {sidebar(collapsed)}
      {!narrow && (
        <ResizeHandle
          className="sidebar-divider"
          label="调整导航栏宽度"
          controls="primary-sidebar application-content"
          value={preview ?? sidebarDisplayWidth(layout)}
          min={collapsedSidebarWidth}
          max={360}
          resetValue={defaultSidebarLayout.width}
          valueText={collapsed ? '导航栏已收起；向右拖动展开' : `导航栏 ${width} 像素`}
          onPreview={(width) => setDragPreview(width === null ? null : { width, origin: input })}
          onCommit={(next) => onChange(resizeSidebar(layout, next))}
        />
      )}
      {children}
    </div>
  );
}
