export type View = 'workspace' | 'projects' | 'jobs' | 'settings';
export type PdfTab = 'original' | 'text' | 'annotations';
export interface Route {
  view: View;
  projectId: string | null;
  page: number;
  tab: PdfTab;
  compoundId: string | null;
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
  const view: View = projectId
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
  if (route.projectId && route.view === 'workspace') {
    params.set('page', String(route.page));
    params.set('tab', route.tab);
    if (route.compoundId) params.set('compound', route.compoundId);
  }
  return `#${path}${params.size ? `?${params}` : ''}`;
}
