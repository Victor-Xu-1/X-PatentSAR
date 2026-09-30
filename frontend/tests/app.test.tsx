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
      return json({ ...health, product: { ...health.product, version: '9.8.7-test' } });
    if (url.endsWith('/projects')) return json({ items: [project] });
    if (url.endsWith(`/projects/${project.id}`)) return json(project);
    if (url.includes('/results?')) return json(results);
    if (url.includes('/pages/')) return json(page);
    if (url.includes('/jobs')) return json({ items: [] });
    throw new Error(`Unexpected isolated contract request: ${url}`);
  });
}
describe('application bootstrap, routes and failure states', () => {
  it('keeps the upload action named and usable when its visual text is hidden on mobile', async () => {
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    await screen.findByText('v9.8.7-test');
    const caption = document.querySelector<HTMLElement>('.topbar-actions > button > span');
    expect(caption).not.toBeNull();
    caption!.style.display = 'none';
    await userEvent.click(screen.getByRole('button', { name: '上传 PDF' }));
    expect(await screen.findByRole('heading', { name: '新建提取任务' })).toBeVisible();
    expect(screen.getByLabelText('项目名称')).toHaveFocus();
  });
  it('mobile drawer keeps hidden navigation inert and restores the menu focus', async () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    await screen.findByText('v9.8.7-test');
    expect(document.querySelector('#primary-sidebar')).toHaveAttribute('inert');
    const menu = screen.getByLabelText('展开或收起导航');
    await userEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(document.querySelector('main')).toHaveAttribute('inert');
    expect(document.querySelector('.topbar-actions')).toHaveAttribute('inert');
    expect(document.querySelector('.breadcrumb')).toHaveAttribute('inert');
    expect(menu.closest('[inert]')).toBeNull();
    await userEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(document.querySelector('main')).not.toHaveAttribute('inert');
    expect(menu).toHaveFocus();
    await userEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    await userEvent.keyboard('{Escape}');
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(menu).toHaveFocus();
  });
  it('shows the API version and a clean workspace without fabricated first-screen results', async () => {
    const transport = contractTransport();
    vi.stubGlobal('fetch', transport);
    render(<App />);
    expect(await screen.findByText('v9.8.7-test')).toBeVisible();
    expect(screen.getByText('开始探索专利中的结构与活性')).toBeVisible();
    expect(screen.queryByText('抑制等级 = ++')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ADMET/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /证据摘要/ })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: '上传 PDF' }));
    expect(await screen.findByRole('heading', { name: '新建提取任务' })).toBeVisible();
    expect(window.location.hash).toBe('#/new-task');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('项目名称')).toHaveFocus();
  });
  it('bootstraps a fresh deep link and preserves actual source navigation', async () => {
    window.location.hash = `#/projects/${project.id}?page=4&tab=text&compound=I-7`;
    const transport = contractTransport();
    vi.stubGlobal('fetch', transport);
    render(<App />);
    expect(await screen.findByText('抑制等级 = ++')).toBeVisible();
    expect(await screen.findByText('<script>untrusted OCR</script>')).toBeVisible();
    expect(screen.getByLabelText('原始文档页码')).toHaveValue('4');
    expect(transport.mock.calls.every(([, init]) => init?.credentials === 'same-origin')).toBe(
      true,
    );
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(
      1,
    );
  });
  it('opens a real project through the project list, using the same API path', async () => {
    window.location.hash = '#/projects';
    vi.stubGlobal('fetch', contractTransport());
    render(<App />);
    await userEvent.click(await screen.findByText('打开工作台'));
    expect(await screen.findByText('抑制等级 = ++')).toBeVisible();
    await waitFor(() => expect(window.location.hash).toContain(project.id));
  });
  it('shows a connection failure with an explicit reconnect path and no fallback data', async () => {
    const transport = vi.fn<typeof fetch>(async () =>
      json({ error: { code: 'unavailable', message: '服务尚未启动' } }, 500),
    );
    vi.stubGlobal('fetch', transport);
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('服务尚未启动');
    expect(screen.getByText('重新加载')).toBeVisible();
    expect(screen.queryByText('抑制等级 = ++')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '运行提取' })).toBeDisabled();
  });
});
