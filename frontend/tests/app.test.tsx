import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { client } from '../src/api';
import { health, json, page, project, results, session } from './fixtures';

beforeEach(() => client.resetSession());
function contractTransport() {
  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url.endsWith('/session')) return json(session);
    if (url.endsWith('/health'))
      return json({
        ...health,
        product: { ...health.product, version: '9.8.7-test' },
        capabilities: { admet: true, summary: true },
      });
    if (url.endsWith('/projects')) return json({ items: [project] });
    if (url.endsWith(`/projects/${project.id}`)) return json(project);
    if (url.includes('/results?')) return json(results);
    if (url.includes('/pages/')) return json(page);
    if (url.includes('/jobs')) return json({ items: [] });
    throw new Error(`Unexpected isolated contract request: ${url}`);
  });
}
async function connected() {
  await waitFor(() => expect(screen.getByRole('button', { name: '上传 PDF' })).toBeEnabled());
}

describe('minimal application shell, routes and failure states', () => {
  it('opens the upload page by default without sidebar, avatar or fabricated results', async () => {
    const transport = contractTransport();
    vi.stubGlobal('fetch', transport);
    render(<App />);
    await connected();
    expect(screen.getByRole('heading', { name: '上传专利 PDF' })).toBeVisible();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toHaveFocus();
    expect(document.querySelector('.sidebar')).toBeNull();
    expect(document.querySelector('.user-avatar')).toBeNull();
    expect(document.querySelector('.breadcrumb')).toBeNull();
    expect(screen.queryByRole('button', { name: /ADMET/ })).not.toBeInTheDocument();
    expect(screen.queryByText('抑制等级 = ++')).not.toBeInTheDocument();
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/projects'))).toHaveLength(
      0,
    );
    expect(await screen.findByText('v9.8.7-test')).toBeVisible();
  });

  it('keeps upload and recent-file controls named when their text is hidden on mobile', async () => {
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    await connected();
    document.querySelectorAll<HTMLElement>('.topbar-actions > button > span').forEach((caption) => {
      caption.style.display = 'none';
    });
    await userEvent.click(screen.getByRole('button', { name: '最近文件' }));
    await userEvent.click(await screen.findByRole('button', { name: `打开 ${project.title}` }));
    expect(await screen.findByTitle('抑制等级 = ++')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '上传 PDF' }));
    expect(await screen.findByRole('heading', { name: '上传专利 PDF' })).toBeVisible();
    expect(screen.getByLabelText('原始专利 PDF 文件')).toHaveFocus();
  });

  it('retains the deep-linked original and table without restoring obsolete navigation', async () => {
    window.location.hash = `#/projects/${project.id}?page=4&tab=text&compound=I-7&navWidth=288&nav=0`;
    const transport = contractTransport();
    vi.stubGlobal('fetch', transport);
    render(<App />);
    expect(await screen.findByTitle('抑制等级 = ++')).toBeVisible();
    expect(await screen.findByText('<script>untrusted OCR</script>')).toBeVisible();
    expect(screen.getByLabelText('原始文档页码')).toHaveValue('4');
    expect(screen.getByText(project.title)).toBeVisible();
    expect(document.querySelector('#primary-sidebar')).toBeNull();
    expect(transport.mock.calls.every(([, init]) => init?.credentials === 'same-origin')).toBe(
      true,
    );
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(
      1,
    );
    await userEvent.click(screen.getByRole('link', { name: 'X-PatentSAR · 上传 PDF' }));
    expect(window.location.hash).toBe('#/new-task');
    expect(screen.getByLabelText('原始专利 PDF 文件')).toHaveFocus();
  });

  it('opens a recent file through the existing project API, not a dashboard', async () => {
    window.location.hash = '#/projects';
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    expect(await screen.findByRole('list', { name: '最近专利文件' })).toBeVisible();
    expect(document.querySelector('.project-grid')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: `打开 ${project.title}` }));
    expect(await screen.findByTitle('抑制等级 = ++')).toBeVisible();
    await waitFor(() => expect(window.location.hash).toContain(project.id));
  });

  it('opens job history directly from the persistent topbar and marks the selected route', async () => {
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    await connected();
    expect(screen.getByRole('button', { name: '任务记录' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '任务记录' }));
    await waitFor(() => expect(window.location.hash).toBe('#/jobs'));
    expect(document.querySelector('.shell-menu')).toBeNull();
    expect(screen.getByRole('button', { name: '任务记录' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(await screen.findByRole('heading', { name: '任务记录' })).toBeVisible();
  });

  it('shows a connection failure and disables writes without fallback data', async () => {
    const transport = vi.fn<typeof fetch>(async () =>
      json({ error: { code: 'unavailable', message: '服务尚未启动' } }, 500),
    );
    vi.stubGlobal('fetch', transport);
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('服务尚未启动');
    expect(screen.getByText('重新加载')).toBeVisible();
    expect(screen.queryByText('抑制等级 = ++')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '上传 PDF' })).toBeDisabled();
  });

  it('does not allow the complete PDF task when the ADMET capability is missing', async () => {
    const transport = contractTransport();
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).endsWith('/health') ? json(health) : transport(input, init),
    );
    render(<App />);
    await connected();
    await userEvent.upload(
      screen.getByLabelText('原始专利 PDF 文件'),
      new File(['%PDF-1.7\ncontract'], 'source.pdf', { type: 'application/pdf' }),
    );
    expect(screen.getByRole('button', { name: '开始提取' })).toBeDisabled();
    expect(screen.getByText(/提取或 ADMET 环境尚未就绪/)).toBeVisible();
  });
});
