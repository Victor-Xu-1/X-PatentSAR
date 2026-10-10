import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale, t } from '../src/i18n';
import { StudyRowTable, studyColumns } from '../src/features/sar/study/StudyRowTable';
import { StudyLeads } from '../src/features/sar/study/StudyLeads';
import { studyContext, studyJob, studyReport, studyRow } from './sar-fixtures';

beforeEach(() => setLocale('en'));

it('locks every source action on unvalidated rows and re-enables the unchanged captured row', async () => {
  const row = { ...studyRow, eligible: false, label: 'Example A 原文' };
  const original = JSON.stringify(row);
  const onSource = vi.fn();
  const element = (active: boolean) => (
    <StudyRowTable
      jobId={studyJob.id}
      rows={[row]}
      columns={studyColumns([studyContext], t)}
      hidden={[]}
      active={active}
      onSource={onSource}
    />
  );
  const view = render(element(false));
  for (const button of screen.getAllByRole('button')) {
    expect(button).toBeDisabled();
    await userEvent.click(button);
  }
  expect(onSource).not.toHaveBeenCalled();
  view.rerender(element(true));
  for (const button of screen.getAllByRole('button')) {
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(onSource).toHaveBeenLastCalledWith(row.molecule_id, row);
  }
  expect(JSON.stringify(row)).toBe(original);
});

it('shows a compact captured Lead group, not a fabricated ordinal rank, and leaves non-selected rows passive', () => {
  const rows = [
    { ...studyRow, eligible: false, label: 'A 原文', priority_group: 2, selection_order: 17 },
    {
      ...studyRow,
      eligible: false,
      molecule_id: 'not-selected',
      label: 'B 原文',
      candidate_status: 'not_selected' as const,
      priority_group: 2,
    },
  ];
  const original = JSON.stringify(rows);
  const view = render(
    <StudyRowTable
      jobId={studyJob.id}
      rows={rows}
      columns={studyColumns([studyContext], t)}
      hidden={['source']}
      active
      onSource={vi.fn()}
    />,
  );
  const selected = view.container.querySelector('.sar-lead-mark')!;
  expect(selected).toHaveTextContent('Lead');
  expect(selected).toHaveTextContent('G2');
  expect(selected).not.toHaveTextContent('17');
  expect(selected).toHaveAttribute('title', 'Selected candidate · Priority group 2');
  expect(selected).toHaveAccessibleName(
    'Source details · A 原文 · Selected candidate · Priority group 2',
  );
  const notSelected = screen.getByRole('rowheader', { name: 'B 原文' }).closest('tr')!;
  expect(within(notSelected).getAllByRole('button')).toHaveLength(1);
  expect(notSelected.querySelector('.sar-candidate-none')).toHaveAttribute(
    'title',
    'Not selected · Priority group 2',
  );
  expect(JSON.stringify(rows)).toBe(original);
});

it.each([
  ['unranked', 'Unranked'],
  ['partial', 'Partial evidence'],
  ['ineligible', 'Ineligible'],
] as const)(
  'retains the meaning of %s instead of presenting it as an empty or selected candidate',
  (status, label) => {
    const row = { ...studyRow, eligible: false, candidate_status: status, priority_group: null };
    const view = render(
      <StudyRowTable
        jobId={studyJob.id}
        rows={[row]}
        columns={studyColumns([studyContext], t)}
        hidden={['source']}
        active
        onSource={vi.fn()}
      />,
    );
    const mark = view.container.querySelector('.sar-lead-mark')!;
    expect(mark).toHaveTextContent(label);
    expect(mark).not.toHaveTextContent('Lead');
    expect(mark).not.toHaveTextContent('G0');
  },
);

it('does not authorize a cached candidate card source action when its report is inactive', async () => {
  const onSource = vi.fn();
  render(
    <StudyLeads report={studyReport} jobId={studyJob.id} active={false} onSource={onSource} />,
  );
  const source = screen.getByRole('button', { name: 'Source details' });
  expect(source).toBeDisabled();
  await userEvent.click(source);
  expect(onSource).not.toHaveBeenCalled();
});
