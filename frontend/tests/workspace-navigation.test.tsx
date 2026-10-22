import { useState } from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { Workspace } from '../src/features/workspace/Workspace';
import { defaultLayout } from '../src/model/layout';
import { emptyRoute } from '../src/model/route';
import type { Route } from '../src/model/route';
import { setLocale } from '../src/i18n';
import { page, project, results } from './fixtures';

afterEach(() => vi.restoreAllMocks());

function ReviewWorkspace({ collapsed = false }: { collapsed?: boolean }) {
  const [route, navigate] = useState<Route>({
    ...emptyRoute,
    projectId: project.id,
    page: 4,
    layout: { ...defaultLayout, pdfVisible: !collapsed },
  });
  const [query, onQuery] = useState('');
  return (
    <Workspace
      project={project}
      route={route}
      navigate={navigate}
      query={query}
      onQuery={onQuery}
      ready
      job={null}
      jobVerified
      onJobChange={vi.fn()}
      onProjectReload={vi.fn()}
      onUpload={vi.fn()}
      onAttach={vi.fn()}
    />
  );
}

describe('explicit source review uses the existing panes without scientific writes', () => {
  it('opens a collapsed original, focuses it and returns to the same results', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const read = vi.spyOn(api, 'page').mockResolvedValue(page);
    render(<ReviewWorkspace collapsed />);
    await userEvent.click(screen.getByRole('button', { name: '查看原文' }));
    const source = screen.getByRole('region', { name: '原文区域' });
    expect(source).toHaveFocus();
    expect(source.scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'auto' });
    expect(await screen.findByRole('textbox', { name: '原始文档页码' })).toHaveValue('4');
    await userEvent.click(screen.getByRole('button', { name: '返回结果' }));
    expect(screen.getByRole('region', { name: '结果区域' })).toHaveFocus();
    expect(source).toBeInTheDocument();
    expect(read).toHaveBeenCalledOnce();
  });

  it('reveals an already open PDF without remounting it or discarding a page draft', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const read = vi.spyOn(api, 'page').mockResolvedValue(page);
    render(<ReviewWorkspace />);
    const input = await screen.findByRole('textbox', { name: '原始文档页码' });
    await userEvent.clear(input);
    await userEvent.type(input, '8');
    await userEvent.click(screen.getByRole('button', { name: '查看原文' }));
    expect(screen.getByRole('region', { name: '原文区域' })).toHaveFocus();
    expect(input).toHaveValue('8');
    act(() => setLocale('en'));
    expect(screen.getByRole('textbox', { name: 'Original document page' })).toBe(input);
    expect(screen.getByRole('button', { name: 'View original' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Back to results' }));
    expect(screen.getByRole('region', { name: 'Results pane' })).toHaveFocus();
    expect(input).toHaveValue('8');
    expect(read).toHaveBeenCalledOnce();
  });

  it('does not steal results focus when a slow original finishes loading', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    let finish!: (value: typeof page) => void;
    vi.spyOn(api, 'page').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<ReviewWorkspace collapsed />);
    await userEvent.click(screen.getByRole('button', { name: '查看原文' }));
    await userEvent.click(screen.getByRole('button', { name: '返回结果' }));
    const pane = screen.getByRole('region', { name: '结果区域' });
    expect(pane).toHaveFocus();
    await act(async () => finish(page));
    expect(pane).toHaveFocus();
  });

  it('keeps return navigation available when the actual original read fails', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const read = vi.spyOn(api, 'page').mockRejectedValue(new Error('source-read-unavailable'));
    render(<ReviewWorkspace collapsed />);
    await userEvent.click(screen.getByRole('button', { name: '查看原文' }));
    expect(await screen.findByText('source-read-unavailable')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '返回结果' }));
    expect(screen.getByRole('region', { name: '结果区域' })).toHaveFocus();
    expect(read).toHaveBeenCalledOnce();
  });
});
