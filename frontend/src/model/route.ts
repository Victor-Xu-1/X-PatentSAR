import { normalizeLayout } from './layout';
import type { LayoutState } from './layout';
import type { ActivityFocusSelection } from '../api/types';
import { validActivityFocus } from '../api/activitySourceDecoders';
import { readTableQuery, writeTableQuery } from './tableQueryRoute';
import type { TableQuery } from './tableQueryRoute';
export type View = 'workspace' | 'projects' | 'jobs' | 'settings' | 'new-task';
export type ResultTab = 'results' | 'summary';
export type PdfTab = 'original' | 'text' | 'annotations';
export interface Route {
  view: View;
  projectId: string | null;
  page: number | null;
  tab: PdfTab;
  compoundId: string | null;
  activityFocus?: ActivityFocusSelection;
  layout?: LayoutState;
  resultTab?: ResultTab;
  operationId?: string;
  tableQuery?: TableQuery;
}
export const emptyRoute: Route = {
  view: 'workspace',
  projectId: null,
  page: null,
  tab: 'original',
  compoundId: null,
};
export function withoutActivityFocus(route: Route): Route {
  const next = { ...route };
  delete next.activityFocus;
  return next;
}
export function parseRoute(hash: string): Route {
  const [path = '', search = ''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const params = new URLSearchParams(search);
  const page = params.has('page') ? Number(params.get('page')) : null;
  const tab = params.get('tab');
  let projectId: string | null = null;
  if (parts[0] === 'projects' && parts[1]) {
    try {
      projectId = decodeURIComponent(parts[1]);
    } catch {
      return { ...emptyRoute, view: 'new-task' };
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
              : 'new-task';
  const focus = {
    compoundId: params.get('focusCompound') ?? '',
    key: params.get('focusActivity') ?? '',
  };
  const validPage = page !== null && Number.isSafeInteger(page) && page > 0 ? page : null;
  const tableQuery = view === 'workspace' && projectId ? readTableQuery(params) : undefined;
  return {
    view,
    projectId,
    page: validPage,
    tab: tab === 'text' || tab === 'annotations' ? tab : 'original',
    compoundId: params.get('compound'),
    ...(tableQuery ? { tableQuery } : {}),
    ...(view === 'workspace' && projectId && validPage !== null && validActivityFocus(focus)
      ? { activityFocus: focus }
      : {}),
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
    ...(params.get('result') === 'summary'
      ? { resultTab: 'summary' as const }
      : params.get('result') === 'admet'
        ? { resultTab: 'results' as const }
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
    writeTableQuery(params, route.tableQuery);
    if (route.page !== null) params.set('page', String(route.page));
    params.set('tab', route.tab);
    if (route.compoundId) params.set('compound', route.compoundId);
    if (
      route.page !== null &&
      Number.isSafeInteger(route.page) &&
      route.page > 0 &&
      validActivityFocus(route.activityFocus)
    ) {
      params.set('focusCompound', route.activityFocus.compoundId);
      params.set('focusActivity', route.activityFocus.key);
    }
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
