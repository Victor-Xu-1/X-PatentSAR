import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudyActivityTable } from '../src/features/sar/study/StudyActivityTable';
import { StudySource } from '../src/features/sar/study/StudySource';
import {
  sarDataset,
  sarDrawing,
  sarMolecule,
  studyContext,
  studyJob,
  studyReport,
  studyRow,
} from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'molecule').mockResolvedValue(sarMolecule);
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({
    id: studyRow.molecule_id,
    svg: sarDrawing.svg,
  });
  vi.spyOn(sarStudyApi, 'rows').mockResolvedValue({
    job: studyJob,
    items: [studyRow],
    total: 1,
    page: 1,
    page_size: 50,
  });
});

it('opens source detail from the original ID and keeps the optional source column recoverable without another row query', async () => {
  const source = vi.fn();
  render(
    <StudyActivityTable
      jobId={studyJob.id}
      report={studyReport}
      active
      filter={{ query: '', scope: 'all', scaffold_id: '', region_id: '', fragment_id: '' }}
      onFilter={vi.fn()}
      onSource={source}
    />,
  );
  const table = await screen.findByRole('table');
  expect(
    within(table).queryByRole('columnheader', { name: 'Source details' }),
  ).not.toBeInTheDocument();
  await userEvent.click(within(table).getByRole('button', { name: studyRow.label }));
  expect(source).toHaveBeenCalledExactlyOnceWith(studyRow.molecule_id, studyRow);
  const columns = screen.getByRole('button', { name: 'Column settings' });
  await userEvent.click(columns);
  const chooser = screen.getByRole('dialog', { name: 'Column settings' });
  const choice = within(chooser).getByRole('checkbox', { name: /Show column Source details/ });
  expect(choice).not.toBeChecked();
  await userEvent.click(choice);
  await userEvent.keyboard('{Escape}');
  expect(within(table).getByRole('columnheader', { name: 'Source details' })).toBeVisible();
  expect(sarStudyApi.rows).toHaveBeenCalledOnce();
  expect(within(table).getByRole('rowheader', { name: studyRow.label })).toBeVisible();
});

it('shows requested details in the shared modal rather than an off-screen panel and preserves source data across locales', async () => {
  render(
    <StudySource
      dataset={sarDataset}
      id={studyRow.molecule_id}
      row={studyRow}
      contexts={[studyContext]}
      active
      onClose={vi.fn()}
    />,
  );
  const dialog = screen.getByRole('dialog', { name: 'Source details' });
  expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  await userEvent.click(await within(dialog).findByText('Original records', { exact: true }));
  await within(dialog).findByText(sarMolecule.label);
  const label = within(dialog).getByText(sarMolecule.label);
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('dialog', { name: '来源详情' })).toBe(dialog);
  expect(label).toHaveTextContent(sarMolecule.label);
  expect(sarApi.molecule).toHaveBeenCalledOnce();
});
