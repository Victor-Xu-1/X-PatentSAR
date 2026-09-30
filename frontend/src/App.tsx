import { useCallback, useEffect, useState } from 'react';
import { api, client } from './api';
import type { Project } from './api/types';
import { emptyRoute } from './model/route';
import type { View } from './model/route';
import { useRoute } from './hooks/useRoute';
import { useResource } from './hooks/useResource';
import { useMediaQuery } from './hooks/useMediaQuery';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { ErrorNotice, Loading } from './components/Feedback';
import { Workspace } from './features/workspace/Workspace';
import { ProjectsPage } from './features/projects/ProjectsPage';
import { UploadDialog } from './features/projects/UploadDialog';
import { useJobs } from './features/jobs/useJobs';
import { JobsPage } from './features/jobs/JobsPage';
import { SettingsPage } from './features/settings/SettingsPage';

export default function App() {
  const { route, navigate } = useRoute();
  const [menuOpen, setMenuOpen] = useState(false);
  const narrow = useMediaQuery('(max-width: 760px)');
  useEffect(() => {
    if (!narrow || !menuOpen) return;
    const opener = document.querySelector<HTMLElement>('.menu-toggle');
    document.querySelector<HTMLElement>('#primary-sidebar .nav-item:not(:disabled)')?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMenuOpen(false);
      }
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      opener?.focus();
    };
  }, [narrow, menuOpen]);
  const [upload, setUpload] = useState<{ project: Project | null } | null>(null);
  const [query, setQuery] = useState('');
  const loadConnection = useCallback(async (signal: AbortSignal) => {
    const [session, health] = await Promise.all([api.session(), api.health(signal)]);
    return { session, health };
  }, []);
  const connection = useResource('connection', loadConnection);
  const connected = connection.data !== null;
  const loadProjects = useCallback((signal: AbortSignal) => api.projects(signal), []);
  const projects = useResource(connected ? 'projects' : null, loadProjects);
  const id = route.projectId;
  const loadProject = useCallback((signal: AbortSignal) => api.project(id ?? '', signal), [id]);
  const projectResource = useResource(connected && id ? `project:${id}` : null, loadProject);
  const project = projectResource.data;
  const jobs = useJobs(id, connected && Boolean(id));
  function openProject(projectId: string) {
    setQuery('');
    setMenuOpen(false);
    navigate({ ...emptyRoute, projectId });
  }
  function navigateView(view: View) {
    setMenuOpen(false);
    navigate({ ...route, view });
  }
  function uploaded(next: Project) {
    setUpload(null);
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
  const onUpload = () => setUpload({ project: null });
  return (
    <div className={`app-shell${menuOpen ? ' menu-open' : ''}`}>
      <a
        href="#main-content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
      >
        跳转到主要内容
      </a>
      {menuOpen && (
        <button
          className="nav-scrim"
          type="button"
          aria-label="关闭导航"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <Sidebar
        route={route}
        navigate={navigateView}
        project={project}
        job={jobs.job}
        health={connection.data?.health ?? null}
        onUpload={onUpload}
        disabled={!connected}
        inert={narrow && !menuOpen}
      />
      <div className="app-main" inert={narrow && menuOpen}>
        <Header
          view={route.view}
          project={project}
          user={connection.data?.session.user.name ?? null}
          query={query}
          onQuery={setQuery}
          onUpload={onUpload}
          onMenu={() => setMenuOpen((open) => !open)}
          disabled={!connected}
          menuOpen={menuOpen}
        />
        <main id="main-content" tabIndex={-1}>
          {connection.loading && !connected && (
            <div className="connection-banner">
              <Loading label="正在建立本地安全会话…" />
            </div>
          )}
          {connection.error && <ErrorNotice error={connection.error} onRetry={reconnect} />}
          {connected && !connection.data?.health.ready && (
            <output className="info-banner runtime-banner">
              API 已连接，本地服务尚未就绪。已有项目可查看，运行按钮保持禁用；详情请查看运行环境。
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
              <Loading label="正在打开专利项目…" />
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
              job={jobs.job}
              onJobChange={jobs.reload}
              onProjectReload={projectResource.reload}
              onUpload={onUpload}
              onAttach={() => project && setUpload({ project })}
            />
          )}
          {route.view === 'projects' && (
            <ProjectsPage resource={projects} onOpen={openProject} onUpload={onUpload} />
          )}
          {route.view === 'jobs' && connected && (
            <JobsPage
              projects={projects.data?.items ?? []}
              ready={connection.data!.health.ready}
              onOpen={openProject}
            />
          )}
          {route.view === 'settings' && connected && <SettingsPage />}
        </main>
      </div>
      {upload && (
        <UploadDialog
          project={upload.project}
          onClose={() => setUpload(null)}
          onUploaded={uploaded}
        />
      )}
    </div>
  );
}
