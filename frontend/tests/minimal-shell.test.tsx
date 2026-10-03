import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  it('keeps only the document and two file actions visible, with the original logo', () => {
    render(<Header {...headerProps} />);
    const brand = screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' });
    expect(brand.querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('brand-mark.png'),
    );
    expect(screen.getByText(project.title)).toBeVisible();
    expect(document.querySelectorAll('.topbar-actions > button')).toHaveLength(2);
    for (const control of document.querySelectorAll('.shell-menu-content button'))
      expect(control).not.toBeVisible();
    expect(screen.getByLabelText('更多')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('navigation', { name: '主导航' })).not.toBeInTheDocument();
  });
  it('supports Escape and outside-pointer close without inerting the document', async () => {
    render(
      <>
        <Header {...headerProps} />
        <main>原文与表格</main>
      </>,
    );
    const trigger = screen.getByLabelText('更多');
    await userEvent.click(trigger);
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'true'));
    expect(screen.getByRole('button', { name: '环境管理' })).toBeVisible();
    expect(screen.getByText('原文与表格')).not.toHaveAttribute('inert');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
    expect(trigger).toHaveFocus();
    await userEvent.click(trigger);
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'true'));
    fireEvent.pointerDown(screen.getByText('原文与表格'));
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
  });
  it('keeps research navigation secondary and never adds a separate ADMET control', async () => {
    const onAnalysis = vi.fn();
    render(<Header {...headerProps} onAnalysis={onAnalysis} />);
    expect(screen.queryByRole('button', { name: /ADMET/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('更多'));
    await userEvent.click(screen.getByRole('button', { name: '返回结果表格' }));
    expect(onAnalysis).toHaveBeenCalledExactlyOnceWith('results');
    expect(document.querySelector('.shell-menu')).not.toHaveAttribute('open');
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
