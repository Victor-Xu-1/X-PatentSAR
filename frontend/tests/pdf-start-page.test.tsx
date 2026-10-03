import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { PdfPane } from '../src/features/pdf/PdfPane';
import { PageControls } from '../src/features/pdf/PageControls';
import { parseRoute, routeHash, emptyRoute } from '../src/model/route';
import { page, project } from './fixtures';

const paneProps = {
  project,
  page: null,
  tab: 'original' as const,
  selectedId: null,
  onPage: vi.fn(),
  onTab: vi.fn(),
  onSelect: vi.fn(),
  onAttach: vi.fn(),
};
describe('source-first opening without an implicit cover page', () => {
  it('preserves absence of a requested page in defaults, links and refresh', () => {
    expect(emptyRoute.page).toBeNull();
    const route = { ...emptyRoute, projectId: project.id };
    expect(routeHash(route)).toBe(`#/projects/${project.id}?tab=original`);
    expect(parseRoute(routeHash(route))).toEqual(route);
    expect(parseRoute(`#/projects/${project.id}`).page).toBeNull();
    for (const value of ['0', '-1', '1.5', 'Infinity', 'NaN', '', 'null'])
      expect(parseRoute(`#/projects/${project.id}?page=${value}`).page).toBeNull();
  });
  it('preserves a deliberate page 1, deep-link pages and annotation selection', () => {
    for (const value of [1, 4, 79]) {
      const route = parseRoute(`#/projects/p?page=${value}&tab=annotations&compound=Compound+11`);
      expect(route.page).toBe(value);
      expect(parseRoute(routeHash(route))).toEqual(route);
    }
  });
  it('maps the retired ADMET page to the table rather than a competing prediction view', () => {
    const route = parseRoute('#/projects/p?result=admet');
    expect(route.resultTab).toBe('results');
    expect(routeHash(route)).not.toContain('admet');
    expect(parseRoute('#/projects/p?result=summary').resultTab).toBe('summary');
  });
  it('waits for structure location without loading page 1 or inventing an image', async () => {
    const read = vi.spyOn(api, 'page').mockResolvedValue(page);
    render(<PdfPane {...paneProps} />);
    expect(screen.getByRole('heading', { name: '等待结构来源页' })).toBeVisible();
    expect(screen.getByLabelText('原始文档页码')).toHaveValue('');
    expect(screen.getByLabelText('原始文档页码')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.getByRole('button', { name: '上一页原始文档' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '下一页原始文档' })).toBeDisabled();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    await waitFor(() => expect(read).not.toHaveBeenCalled());
  });
  it('loads the cover only after explicit browse-original, and leaves that choice to the route owner', async () => {
    const onPage = vi.fn();
    const read = vi.spyOn(api, 'page').mockResolvedValue({ ...page, page: 1 });
    const { rerender } = render(<PdfPane {...paneProps} onPage={onPage} />);
    await userEvent.click(screen.getByRole('button', { name: '浏览原文' }));
    expect(onPage).toHaveBeenCalledExactlyOnceWith(1);
    expect(read).not.toHaveBeenCalled();
    rerender(<PdfPane {...paneProps} page={1} onPage={onPage} />);
    await waitFor(() =>
      expect(read).toHaveBeenCalledExactlyOnceWith(project.id, 1, expect.any(AbortSignal)),
    );
    expect(screen.getByLabelText('原始文档页码')).toHaveValue('1');
  });
  it('starts directly at the supplied resolved structure page, not at the cover first', async () => {
    const read = vi.spyOn(api, 'page').mockResolvedValue(page);
    render(<PdfPane {...paneProps} page={4} project={{ ...project, first_structure_page: 4 }} />);
    await waitFor(() =>
      expect(read).toHaveBeenCalledExactlyOnceWith(project.id, 4, expect.any(AbortSignal)),
    );
    expect(screen.getByLabelText('原始文档页码')).toHaveValue('4');
  });
  it('does not override an explicit deep link with the backend first structure page', async () => {
    const read = vi.spyOn(api, 'page').mockResolvedValue({ ...page, page: 8 });
    render(<PdfPane {...paneProps} page={8} project={{ ...project, first_structure_page: 4 }} />);
    await waitFor(() =>
      expect(read).toHaveBeenCalledExactlyOnceWith(project.id, 8, expect.any(AbortSignal)),
    );
  });
  it('permits deliberate page entry while the first structure page is still unknown', () => {
    const onPage = vi.fn();
    render(
      <PageControls
        page={null}
        total={12}
        zoom={1}
        disabled={false}
        onPage={onPage}
        onZoom={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('原始文档页码');
    fireEvent.change(input, { target: { value: '8' } });
    fireEvent.submit(input.closest('form')!);
    expect(onPage).toHaveBeenCalledExactlyOnceWith(8);
    expect(screen.getByRole('button', { name: '文档工具' })).toBeDisabled();
  });
});
