import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { SARPage } from '../src/features/sar/SARPage';
import { emptyRoute } from '../src/model/route';
import { setLocale } from '../src/i18n';
import { project } from './fixtures';
import { sarDataset } from './sar-fixtures';

// This regression concerns the persistent intake page. Dataset execution has
// independent real-stack coverage; do not create a job in this rendering test.
vi.mock('../src/features/sar/DatasetWorkbench', () => ({
  DatasetWorkbench: () => <div>Existing study result</div>,
}));
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'datasets').mockResolvedValue({ items: [sarDataset], total: 1 });
  vi.spyOn(api, 'projects').mockResolvedValue({ items: [project] });
});

it('defaults a later result route to collapsed intake and preserves explicit import drafts and locale', async () => {
  const props = { navigate: vi.fn() };
  const { rerender } = render(<SARPage {...props} active={false} route={emptyRoute} />);
  expect(sarApi.datasets).not.toHaveBeenCalled();
  const route = { ...emptyRoute, view: 'sar' as const, sarDatasetId: sarDataset.id };
  rerender(<SARPage {...props} active route={route} />);
  await screen.findByText('Existing study result');
  expect(screen.getByRole('button', { name: 'Import data' })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  expect(screen.queryByRole('heading', { name: 'Import data' })).not.toBeInTheDocument();
  expect(api.projects).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Import data' }));
  const title = await screen.findByLabelText('Dataset title');
  expect(title).not.toBeVisible();
  await userEvent.click(screen.getByText('Name (optional)'));
  await userEvent.type(title, 'source-owned title');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByLabelText('数据集名称')).toBe(title);
  expect(title).toHaveValue('source-owned title');
  rerender(<SARPage {...props} active route={{ ...route, sarJobId: 'current-study' }} />);
  expect(title).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '导入数据' }));
  rerender(<SARPage {...props} active={false} route={emptyRoute} />);
  rerender(<SARPage {...props} active route={route} />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '导入数据' })).toHaveAttribute(
      'aria-expanded',
      'false',
    ),
  );
  expect(props.navigate).not.toHaveBeenCalled();
});
