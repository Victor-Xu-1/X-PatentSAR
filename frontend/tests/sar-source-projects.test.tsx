import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { SARImport } from '../src/features/sar/SARImport';
import { setLocale, t } from '../src/i18n';
import { sourceProjectLabels } from '../src/model/projectOptionLabels';
import { acceptanceLabels, dateText } from '../src/model/presentation';
import { project } from './fixtures';
import { sarDataset } from './sar-fixtures';

const first = {
  ...project,
  id: 'same-prefix-source-a',
  title: 'Original label 007B',
  acceptance: { state: 'failed' as const, errors: [] },
};
const second = {
  ...first,
  id: 'same-prefix-source-b',
  created_at: '2026-02-03T04:05:06Z',
  acceptance: { state: 'accepted' as const, errors: [] },
};

beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'projects').mockResolvedValue({ items: [first, second] });
});

it('keeps unique source titles literal and never mutates projects to add UI metadata', () => {
  const before = structuredClone([first, second]);
  expect(sourceProjectLabels([first]).get(first.id)).toBe(first.title);
  const labels = sourceProjectLabels([first, second]);
  expect(labels.get(first.id)).toBe(
    `${dateText(first.created_at)} · ${t(acceptanceLabels.failed)} · ${first.title}`,
  );
  expect(labels.get(second.id)).toBe(
    `${dateText(second.created_at)} · ${t(acceptanceLabels.accepted)} · ${second.title}`,
  );
  expect(labels.get(first.id)).not.toBe(labels.get(second.id));
  expect([first, second]).toEqual(before);
});

it('disambiguates equal title, state and timestamp without exposing IDs or depending on order', () => {
  const same = { ...second, created_at: first.created_at, acceptance: first.acceptance };
  const labels = sourceProjectLabels([first, same]);
  const reordered = sourceProjectLabels([same, first]);
  expect(labels.get(first.id)).toMatch(/^Source 1 · /);
  expect(labels.get(same.id)).toMatch(/^Source 2 · /);
  for (const item of [first, same]) {
    expect(labels.get(item.id)).toBe(reordered.get(item.id));
    expect(labels.get(item.id)).not.toContain(item.id);
  }
  setLocale('zh-CN');
  expect(sourceProjectLabels([same, first]).get(first.id)).toContain('来源 1');
  expect(sourceProjectLabels([same, first]).get(same.id)).toContain(same.title);
  expect(sourceProjectLabels([]).size).toBe(0);
});

it('preserves the chosen source identity and draft across languages without importing on read', async () => {
  const create = vi.spyOn(sarApi, 'createProject').mockResolvedValue(sarDataset);
  const analyse = vi.spyOn(sarApi, 'analyse');
  const extract = vi.spyOn(api, 'createJob');
  render(<SARImport active sourceProjectId={first.id} onCreated={vi.fn()} />);
  await screen.findByRole('option', { name: sourceProjectLabels([first, second]).get(first.id)! });
  await userEvent.selectOptions(screen.getByLabelText('Source project'), second.id);
  await userEvent.click(screen.getByText('Name (optional)'));
  await userEvent.type(screen.getByLabelText('Dataset title'), 'Literal draft 007B');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByLabelText('来源项目')).toHaveValue(second.id);
  expect(screen.getByLabelText('数据集名称')).toHaveValue('Literal draft 007B');
  for (const item of [first, second])
    expect(
      screen.getByRole('option', { name: sourceProjectLabels([first, second]).get(item.id)! }),
    ).toHaveTextContent(item.title);
  expect(create).not.toHaveBeenCalled();
  expect(analyse).not.toHaveBeenCalled();
  expect(extract).not.toHaveBeenCalled();
});

it('submits the explicitly chosen project ID, not its label or the first same-named record', async () => {
  const output = { ...sarDataset, source_project_id: second.id };
  const create = vi.spyOn(sarApi, 'createProject').mockResolvedValue(output);
  const created = vi.fn();
  render(<SARImport active sourceProjectId={first.id} onCreated={created} />);
  await screen.findByRole('option', { name: sourceProjectLabels([first, second]).get(second.id)! });
  await userEvent.selectOptions(screen.getByLabelText('Source project'), second.id);
  expect(create).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await waitFor(() => expect(created).toHaveBeenCalledWith(output));
  expect(create).toHaveBeenCalledExactlyOnceWith({
    project_id: second.id,
    title: null,
    request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
  });
});

it('keeps unreadable sources disabled even when they share a title with a usable source', async () => {
  const unavailable = {
    ...first,
    acceptance: second.acceptance,
    read_error: { code: 'invalid_artifact', message: 'Source proof unreadable' },
  };
  vi.mocked(api.projects).mockResolvedValue({ items: [unavailable, second] });
  const create = vi.spyOn(sarApi, 'createProject');
  render(<SARImport active sourceProjectId={first.id} onCreated={vi.fn()} />);
  const label = sourceProjectLabels([unavailable, second]).get(first.id)!;
  expect(label).toContain(t('结果数据需修复'));
  expect(label).not.toContain(t(acceptanceLabels.accepted));
  expect(await screen.findByRole('option', { name: label })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  expect(create).not.toHaveBeenCalled();
});
