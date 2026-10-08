import { useCallback, useState } from 'react';
import { api, client } from './api';
import type { Project } from './api/types';
import type { HistoryEntry } from './api/historyTypes';
import { emptyRoute } from './model/route';
import type { View } from './model/route';
import { useRoute } from './hooks/useRoute';
import { useResource } from './hooks/useResource';
import { Header } from './components/Header';
import { ErrorNotice, Loading } from './components/Feedback';
import { Workspace } from './features/workspace/Workspace';
import { ProjectsPage } from './features/projects/ProjectsPage';
import { AttachPdfDialog } from './features/projects/AttachPdfDialog';
import { NewTaskPage } from './features/tasks/NewTaskPage';
import { useJobs } from './features/jobs/useJobs';
import { JobsPage } from './features/jobs/JobsPage';
import { EnvironmentPage } from './features/environment/EnvironmentPage';
import { useTranslation } from './i18n';

export default function App() {
  const { locale, t } = useTranslation();
  const { route, navigate } = useRoute();
  const [attachment, setAttachment] = useState<Project | null>(null);
  const [query, setQuery] = useState('');
  const loadConnection = useCallback(async (signal: AbortSignal) => {
    const [session, health] = await Promise.all([api.session(), api.health(signal)]);
    return { session, health };
  }, []);
  const connection = useResource('connection', loadConnection);
  const connected = connection.data !== null;
  const loadProjects = useCallback((signal: AbortSignal) => api.projects(signal), []);
  const projects = useResource(
    connected && (route.view === 'projects' || route.view === 'jobs') ? 'projects' : null,
    loadProjects,
  );
  const id = route.projectId;
  const loadProject = useCallback((signal: AbortSignal) => api.project(id ?? '', signal), [id]);
  const projectResource = useResource(
    connected && id && route.view === 'workspace' ? `project:${id}` : null,
    loadProject,
  );
  const project = projectResource.data;
  const jobs = useJobs(id, connected && Boolean(id) && route.view === 'workspace');
  function openProject(projectId: string) {
    setQuery('');
    navigate({ ...emptyRoute, view: 'workspace', projectId });
  }
  function navigateView(view: View) {
    navigate({ ...emptyRoute, view });
  }
  function uploaded(next: Project) {
    setAttachment(null);
    projects.reload();
    projectResource.reload();
    openProject(next.id);
  }
  function reconnect() {
    client.resetSession();
    connection.reload();
    projects.reload();
    projectResource.reload();
    jobs.reload();
  }
  function historyChanged(entry: HistoryEntry) {
    projects.reload();
    projectResource.reload();
    jobs.reload();
    if (entry.kind === 'project' && entry.deleted_at !== null) {
      if (attachment?.id === entry.id) setAttachment(null);
      if (route.projectId === entry.id) {
        setQuery('');
        navigate({ ...emptyRoute, view: 'projects' });
      }
    }
  }
  const onUpload = () => {
    navigate({ ...emptyRoute, view: 'new-task' });
  };
  return (
    <div className="app-shell" lang={locale}>
      <a
        href="#main-content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
      >
        {t('跳转到主要内容')}
      </a>
      <div className="app-main" id="application-content">
        <Header
          view={route.view}
          project={project}
          version={connection.data?.health.product.version ?? null}
          onUpload={onUpload}
          onRecent={() => navigateView('projects')}
          onNavigate={navigateView}
          onAnalysis={(resultTab) => navigate({ ...route, view: 'workspace', resultTab })}
          disabled={!connected}
        />
        <main id="main-content" tabIndex={-1}>
          {connection.loading && !connected && (
            <div className="connection-banner">
              <Loading label={t('正在建立本地安全会话…')} />
            </div>
          )}
          {connection.error && <ErrorNotice error={connection.error} onRetry={reconnect} />}
          {connected && !connection.data?.health.ready && (
            <output className="info-banner runtime-banner">
              {t('运行环境尚未就绪。已有文件仍可查看；请在顶栏“环境管理”中检测。')}
            </output>
          )}
          {projectResource.error && (
            <ErrorNotice error={projectResource.error} onRetry={projectResource.reload} />
          )}
          {(jobs.error || jobs.detailError) && (
            <ErrorNotice error={(jobs.error ?? jobs.detailError)!} onRetry={jobs.reload} />
          )}
          {projectResource.loading && !project && id && (
            <div className="connection-banner">
              <Loading label={t('正在打开专利项目…')} />
            </div>
          )}
          {route.view === 'workspace' && (
            <Workspace
              key={id}
              project={project}
              route={route}
              navigate={navigate}
              query={query}
              onQuery={setQuery}
              ready={connected && connection.data!.health.ready}
              capabilities={connection.data?.health.capabilities ?? null}
              job={jobs.job}
              onJobChange={jobs.reload}
              onProjectReload={projectResource.reload}
              onUpload={onUpload}
              onAttach={() => project && setAttachment(project)}
            />
          )}
          {route.view === 'projects' && (
            <ProjectsPage
              resource={projects}
              onOpen={openProject}
              onUpload={onUpload}
              onHistoryChanged={historyChanged}
            />
          )}
          {route.view === 'jobs' && connected && (
            <JobsPage
              projects={projects.data?.items ?? []}
              ready={connection.data!.health.ready}
              onOpen={openProject}
              onHistoryChanged={historyChanged}
            />
          )}
          {route.view === 'settings' && connected && (
            <EnvironmentPage
              operationId={route.operationId ?? null}
              onOperation={(operationId) => {
                const next = { ...route };
                if (operationId === null) delete next.operationId;
                else next.operationId = operationId;
                navigate(next);
              }}
              product={connection.data!.health.product}
            />
          )}
          {route.view === 'new-task' && (
            <NewTaskPage
              connected={connected}
              ready={Boolean(
                connection.data?.health.ready && connection.data?.health.capabilities?.admet,
              )}
              onCreated={uploaded}
              onOpen={openProject}
            />
          )}
        </main>
      </div>
      {attachment && (
        <AttachPdfDialog
          project={attachment}
          onClose={() => setAttachment(null)}
          onUploaded={uploaded}
        />
      )}
    </div>
  );
}
