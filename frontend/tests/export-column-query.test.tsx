import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Filters } from '../src/api/types';
import { ExportDialog } from '../src/features/results/ExportDialog';
import * as uploads from '../src/model/uploads';
import { project } from './fixtures';

const filters: Filters = {
  q: '',
  target: '',
  confidence: '',
  review: '',
  page: 4,
  page_size: 25,
  column_filters: [{ column: 'compound', op: 'not_in', values: ['A'], include_empty: false }],
  sort_column: `activity:${'a'.repeat(64)}`,
  sort_direction: 'desc',
  sort_band: 'none',
};
beforeEach(() => {
  vi.spyOn(api, 'export').mockResolvedValue(new Blob(['controlled export']));
  vi.spyOn(uploads, 'saveBlob').mockImplementation(() => {});
});
describe('export scope follows the complete table query', () => {
  it('defaults a column-only query to filtered and preserves color-sort/blank selectors', async () => {
    render(<ExportDialog project={project} selected={[]} filters={filters} onClose={vi.fn()} />);
    expect(screen.getByLabelText('导出范围')).toHaveValue('filtered');
    expect(screen.getByText('按当前表格查询导出 · 1 列筛选 · 保留排序')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '生成并下载' }));
    await waitFor(() =>
      expect(api.export).toHaveBeenCalledExactlyOnceWith(project.id, 'csv', [], filters),
    );
  });
  it('defaults sort-only queries to filtered, including color sort', () => {
    render(
      <ExportDialog
        project={project}
        selected={[]}
        filters={{ ...filters, column_filters: [] }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('导出范围')).toHaveValue('filtered');
  });
  it('passes current query and sort for selected IDs', async () => {
    render(
      <ExportDialog project={project} selected={['I-7']} filters={filters} onClose={vi.fn()} />,
    );
    expect(screen.getByLabelText('导出范围')).toHaveValue('selected');
    await userEvent.selectOptions(screen.getByLabelText('文件格式'), 'json');
    await userEvent.click(screen.getByRole('button', { name: '生成并下载' }));
    await waitFor(() =>
      expect(api.export).toHaveBeenCalledExactlyOnceWith(project.id, 'json', ['I-7'], filters),
    );
  });
  it('explicit all really omits all current query selectors', async () => {
    render(<ExportDialog project={project} selected={[]} filters={filters} onClose={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText('导出范围'), 'all');
    expect(screen.queryByText(/按当前表格查询导出/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '生成并下载' }));
    await waitFor(() => expect(api.export).toHaveBeenCalledExactlyOnceWith(project.id, 'csv', []));
  });
});
