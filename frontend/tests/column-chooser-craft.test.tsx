import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { ColumnChooser } from '../src/features/results/ColumnChooser';
import { setLocale } from '../src/i18n';
import type { ResultColumn } from '../src/model/resultColumns';

const column = (id: string, label: string, context: string): ResultColumn => ({
  id,
  label,
  context,
  className: '',
  width: 120,
  min: 80,
  max: 300,
});

beforeEach(() => setLocale('en'));

it('discloses unique-column context only on request without changing visibility or raw data', async () => {
  const columns = [column('source-a', 'Original α', 'RAW assay / 原始条件 1 nM')];
  const snapshot = JSON.stringify(columns);
  const changed = vi.fn();
  render(<ColumnChooser columns={columns} hidden={[]} onHidden={changed} />);
  expect(screen.queryByText(columns[0]!.context!)).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox')).toHaveAccessibleName(
    'Show column Original α · RAW assay / 原始条件 1 nM',
  );
  const details = screen.getByRole('button', { name: 'Column details' });
  expect(details).toHaveAttribute('aria-expanded', 'false');
  await userEvent.click(details);
  expect(screen.getByText(columns[0]!.context!)).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('button', { name: '列详情' })).toBe(details);
  expect(details).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByText(columns[0]!.context!)).toBeVisible();
  await userEvent.click(details);
  expect(screen.queryByText(columns[0]!.context!)).not.toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
  expect(JSON.stringify(columns)).toBe(snapshot);
});

it('always distinguishes duplicate source headings by their unmodified contexts', async () => {
  const columns = [
    column('assay-a', 'IC50 (nM)', 'Target A · original assay α'),
    column('assay-b', 'IC50 (nM)', 'Target B · original assay β'),
  ];
  const changed = vi.fn();
  render(<ColumnChooser columns={columns} hidden={[]} onHidden={changed} />);
  for (const item of columns) expect(screen.getByText(item.context!)).toBeVisible();
  await userEvent.click(
    screen.getByRole('checkbox', { name: 'Show column IC50 (nM) · ' + columns[1]!.context }),
  );
  expect(changed).toHaveBeenCalledExactlyOnceWith(['assay-b']);
  const details = screen.getByRole('button', { name: 'Column details' });
  await userEvent.click(details);
  await userEvent.click(details);
  for (const item of columns) expect(screen.getByText(item.context!)).toBeVisible();
});

it('searches hidden context and changes exact column IDs while retaining unrelated visibility', async () => {
  const columns = [
    column('metric-a', 'IC50', 'RAW context α'),
    column('metric-b', 'EC50', 'RAW context β'),
  ];
  const changed = vi.fn();
  render(<ColumnChooser columns={columns} hidden={['retained-column']} onHidden={changed} />);
  await userEvent.type(screen.getByRole('textbox', { name: 'Find column' }), 'context β');
  expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  expect(screen.queryByText(columns[1]!.context!)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('checkbox'));
  expect(changed).toHaveBeenCalledExactlyOnceWith(['retained-column', 'metric-b']);
  await userEvent.click(screen.getByRole('button', { name: 'Show all columns' }));
  expect(changed).toHaveBeenLastCalledWith([]);
  expect(screen.getByRole('textbox', { name: 'Find column' })).toHaveValue('context β');
});
