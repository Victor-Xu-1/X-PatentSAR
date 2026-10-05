import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Header } from '../src/components/Header';
import { ProjectsPage } from '../src/features/projects/ProjectsPage';
import { parseRoute, routeHash } from '../src/model/route';
import { project } from './fixtures';

const headerProps = {
  view: 'workspace' as const,
  project,
  version: '0.1.0',
  onUpload: vi.fn(),
  onRecent: vi.fn(),
  onNavigate: vi.fn(),
  onAnalysis: vi.fn(),
  disabled: false,
};

describe('minimal document shell', () => {
  it('marks PDF upload as the current page in the same direct navigation', () => {
    render(<Header {...headerProps} view="new-task" project={null} />);
    expect(screen.getByRole('button', { name: '上传 PDF' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('button', { name: '最近文件' })).not.toHaveAttribute('aria-current');
  });
  it('shows all former menu actions and the actual version directly beside the original logo and document', () => {
    render(<Header {...headerProps} />);
    const brand = screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' });
    expect(brand.querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('brand-mark.png'),
    );
    expect(screen.getByText(project.title)).toBeVisible();
    expect(document.querySelectorAll('.topbar-actions > button')).toHaveLength(6);
    for (const name of ['上传 PDF', '最近文件', '环境管理', '任务记录', '返回结果表格', '证据摘要'])
      expect(screen.getByRole('button', { name })).toBeVisible();
    expect(screen.getByText('v0.1.0')).toBeVisible();
    expect(document.querySelector('.shell-menu')).toBeNull();
    expect(screen.queryByLabelText('更多')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument();
  });
  it('uses direct navigation callbacks without a menu, popup or inert document', async () => {
    const onNavigate = vi.fn();
    render(
      <>
        <Header {...headerProps} onNavigate={onNavigate} />
        <main>原文与表格</main>
      </>,
    );
    await userEvent.click(screen.getByRole('button', { name: '环境管理' }));
    await userEvent.click(screen.getByRole('button', { name: '任务记录' }));
    expect(onNavigate.mock.calls).toEqual([['settings'], ['jobs']]);
    expect(screen.getByText('原文与表格')).not.toHaveAttribute('inert');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('exposes both existing result views directly without adding a separate ADMET workflow', async () => {
    const onAnalysis = vi.fn();
    render(<Header {...headerProps} onAnalysis={onAnalysis} />);
    expect(screen.queryByRole('button', { name: /ADMET/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '返回结果表格' }));
    await userEvent.click(screen.getByRole('button', { name: '证据摘要' }));
    expect(onAnalysis.mock.calls).toEqual([['results'], ['summary']]);
  });
  it('keeps the four general routes visible and marks the current page without project-only controls', () => {
    render(<Header {...headerProps} view="settings" project={null} />);
    expect(document.querySelectorAll('.topbar-actions > button')).toHaveLength(4);
    expect(screen.getByRole('button', { name: '环境管理' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.queryByRole('button', { name: '证据摘要' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '返回结果表格' })).not.toBeInTheDocument();
  });
  it('disables every direct control before the existing connection is ready', async () => {
    const onNavigate = vi.fn(),
      onAnalysis = vi.fn();
    render(<Header {...headerProps} disabled onNavigate={onNavigate} onAnalysis={onAnalysis} />);
    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled();
      await userEvent.click(button);
    }
    expect(onNavigate).not.toHaveBeenCalled();
    expect(onAnalysis).not.toHaveBeenCalled();
  });
  it('retains keyboard access to every persistent topbar control', async () => {
    render(<Header {...headerProps} />);
    screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' }).focus();
    for (const name of [
      '上传 PDF',
      '最近文件',
      '环境管理',
      '任务记录',
      '返回结果表格',
      '证据摘要',
    ]) {
      await userEvent.tab();
      expect(screen.getByRole('button', { name })).toHaveFocus();
    }
  });
  it('does not invent a product version before the health response arrives', () => {
    render(<Header {...headerProps} version={null} />);
    expect(screen.getByText('版本待连接')).toBeVisible();
    expect(screen.queryByText('v0.1.0')).not.toBeInTheDocument();
  });
  it('ignores retired sidebar URL keys while retaining PDF geometry and source IDs', () => {
    expect(parseRoute('#/').view).toBe('new-task');
    expect(parseRoute('#/projects/%').view).toBe('new-task');
    const route = parseRoute(
      '#/projects/p?page=79&tab=annotations&compound=I-8&navWidth=300&nav=0&pdfWidth=32&pdf=1',
    );
    expect(route.layout?.pdfWidth).toBe(32);
    expect(route.compoundId).toBe('I-8');
    expect(routeHash(route)).toBe(
      '#/projects/p?page=79&tab=annotations&compound=I-8&pdfWidth=32&pdf=1&fullscreen=0',
    );
    const settings = parseRoute('#/settings?operation=operation-123&nav=0');
    expect(settings.operationId).toBe('operation-123');
    expect(routeHash(settings)).toBe('#/settings?operation=operation-123');
  });
});

describe('recent-file list', () => {
  it('sorts by update time without mutating the resource and opens the selected ID', async () => {
    const newer = {
      ...project,
      id: 'newer',
      title: '较新专利',
      updated_at: '2026-10-03T00:00:00Z',
    };
    const items = [project, newer];
    const onOpen = vi.fn();
    render(
      <ProjectsPage
        resource={{ data: { items }, loading: false, error: null, reload: vi.fn() }}
        onOpen={onOpen}
        onUpload={vi.fn()}
      />,
    );
    expect(screen.getAllByRole('listitem')[0]).toHaveTextContent('较新专利');
    expect(items[0]?.id).toBe(project.id);
    await userEvent.click(screen.getByRole('button', { name: '打开 较新专利' }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith('newer');
    expect(document.querySelector('.project-card')).toBeNull();
  });
  it('has honest loading, empty and error recovery states', async () => {
    const resource = { data: null, loading: true, error: null, reload: vi.fn() };
    const props = { resource, onOpen: vi.fn(), onUpload: vi.fn() };
    const { rerender } = render(<ProjectsPage {...props} />);
    expect(screen.getByText('正在读取最近文件…')).toBeVisible();
    rerender(<ProjectsPage {...props} resource={{ ...resource, loading: false }} />);
    expect(screen.getByText('还没有文件')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '上传 PDF' }));
    expect(props.onUpload).toHaveBeenCalledOnce();
    rerender(
      <ProjectsPage
        {...props}
        resource={{ ...resource, loading: false, error: new Error('连接失败') }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('连接失败');
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(resource.reload).toHaveBeenCalledOnce();
  });
});
