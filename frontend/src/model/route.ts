import { normalizeLayout } from './layout';
import type { LayoutState } from './layout';
export type View = 'workspace' | 'projects' | 'jobs' | 'settings' | 'new-task';
export type ResultTab = 'results' | 'admet' | 'summary';
export type PdfTab = 'original' | 'text' | 'annotations';
export interface Route {
  view: View;
  projectId: string | null;
  page: number;
  tab: PdfTab;
  compoundId: string | null;
  layout?: LayoutState;
  resultTab?: ResultTab;
  operationId?: string;
}
export const emptyRoute: Route = {
  view: 'workspace',
  projectId: null,
  page: 1,
  tab: 'original',
  compoundId: null,
};
export function parseRoute(hash: string): Route {
  const [path = '', search = ''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const params = new URLSearchParams(search);
  const page = Number(params.get('page') ?? 1);
  const tab = params.get('tab');
  let projectId: string | null = null;
  if (parts[0] === 'projects' && parts[1]) {
    try {
      projectId = decodeURIComponent(parts[1]);
    } catch {
      return emptyRoute;
    }
  }
  const view: View =
    parts[0] === 'new-task'
      ? 'new-task'
      : projectId
        ? 'workspace'
        : parts[0] === 'projects'
          ? 'projects'
          : parts[0] === 'jobs'
            ? 'jobs'
            : parts[0] === 'settings'
              ? 'settings'
              : 'workspace';
  return {
    view,
    projectId,
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    tab: tab === 'text' || tab === 'annotations' ? tab : 'original',
    compoundId: params.get('compound'),
    ...(view === 'settings' && /^[A-Za-z0-9_-]{1,200}$/.test(params.get('operation') ?? '')
      ? { operationId: params.get('operation')! }
      : {}),
    ...(['pdfWidth', 'pdf', 'fullscreen'].some((key) => params.has(key))
      ? {
          layout: normalizeLayout({
            pdfWidth: params.has('pdfWidth') ? Number(params.get('pdfWidth')) : 28,
            pdfVisible: params.get('pdf') !== '0',
            fullscreen: params.get('fullscreen') === '1',
          }),
        }
      : {}),
    ...(params.get('result') === 'admet' || params.get('result') === 'summary'
      ? { resultTab: params.get('result') as ResultTab }
      : {}),
  };
}
export function routeHash(route: Route): string {
  const path =
    route.projectId && route.view === 'workspace'
      ? `/projects/${encodeURIComponent(route.projectId)}`
      : route.view === 'workspace'
        ? '/'
        : `/${route.view}`;
  const params = new URLSearchParams();
  if (route.view === 'settings' && route.operationId) params.set('operation', route.operationId);
  if (route.projectId && route.view === 'workspace') {
    params.set('page', String(route.page));
    params.set('tab', route.tab);
    if (route.compoundId) params.set('compound', route.compoundId);
  }
  if (route.view === 'workspace') {
    if (route.layout) {
      const layout = normalizeLayout(route.layout);
      params.set('pdfWidth', String(layout.pdfWidth));
      params.set('pdf', layout.pdfVisible ? '1' : '0');
      params.set('fullscreen', layout.fullscreen ? '1' : '0');
    }
    if (route.resultTab && route.resultTab !== 'results') params.set('result', route.resultTab);
  }
  return `#${path}${params.size ? `?${params}` : ''}`;
}
