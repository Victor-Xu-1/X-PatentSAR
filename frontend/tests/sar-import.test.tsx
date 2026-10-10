import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { sarApi } from '../src/api/sarApi';
import { ApiError } from '../src/api/errors';
import { setLocale } from '../src/i18n';
import { SARImport } from '../src/features/sar/SARImport';
import { CSVMappingForm } from '../src/features/sar/CSVMappingForm';
import { csvPreview, sarDataset } from './sar-fixtures';
import { project } from './fixtures';

beforeEach(() => {
  setLocale('en');
  vi.spyOn(api, 'projects').mockResolvedValue({
    items: [{ ...project, id: 'project-control', title: '原文项目' }],
  });
});
describe('two explicit SAR intake choices', () => {
  it('guides the project choice with one next action and keeps the optional name out of the initial form', async () => {
    const create = vi.spyOn(sarApi, 'createProject').mockResolvedValue(sarDataset);
    render(<SARImport active sourceProjectId="project-control" onCreated={vi.fn()} />);
    await screen.findByRole('option', { name: '原文项目' });
    expect(screen.getByLabelText('Dataset title')).not.toBeVisible();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
    expect(create).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Name (optional)'));
    expect(screen.getByLabelText('Dataset title')).toBeVisible();
    expect(create).not.toHaveBeenCalled();
  });
  it('rejects over-limit CSV files before sending bytes to the server', async () => {
    const preview = vi.spyOn(sarApi, 'preview');
    render(<SARImport active sourceProjectId={null} onCreated={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'CSV file' }));
    const file = new File(['id,smiles'], 'large.csv');
    Object.defineProperty(file, 'size', { value: 8 * 1024 * 1024 + 1 });
    await userEvent.upload(screen.getByLabelText('Choose a CSV file'), file);
    await userEvent.click(screen.getByRole('button', { name: 'Preview on server' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('8 MiB');
    expect(preview).not.toHaveBeenCalled();
  });
  it('prefills the passed source project, but never creates or analyses on GET or language change', async () => {
    const create = vi.spyOn(sarApi, 'createProject').mockResolvedValue(sarDataset);
    const analysis = vi.spyOn(sarApi, 'analyse');
    const extraction = vi.spyOn(api, 'createJob');
    render(<SARImport active sourceProjectId="project-control" onCreated={vi.fn()} />);
    expect(await screen.findByRole('option', { name: '原文项目' })).toBeVisible();
    expect(screen.getByLabelText('Source project')).toHaveValue('project-control');
    const title = screen.getByLabelText('Dataset title');
    await userEvent.click(screen.getByText('Name (optional)'));
    await userEvent.type(title, '用户 snapshot draft');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('数据集名称')).toBe(title);
    expect(title).toHaveValue('用户 snapshot draft');
    expect(create).not.toHaveBeenCalled();
    expect(analysis).not.toHaveBeenCalled();
    expect(extraction).not.toHaveBeenCalled();
  });
  it('creates a separate project snapshot only after explicit submit, with crypto identity', async () => {
    const create = vi.spyOn(sarApi, 'createProject').mockResolvedValue(sarDataset);
    const created = vi.fn();
    render(<SARImport active sourceProjectId="project-control" onCreated={created} />);
    await screen.findByRole('option', { name: '原文项目' });
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(created).toHaveBeenCalledWith(sarDataset));
    expect(create.mock.calls[0]?.[0]).toEqual({
      project_id: 'project-control',
      title: null,
      request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
    });
  });
  it('uses the server preview before mapping, with native exported long CSV defaults', async () => {
    const preview = vi.spyOn(sarApi, 'preview').mockResolvedValue(csvPreview);
    const create = vi
      .spyOn(sarApi, 'createCSV')
      .mockResolvedValue({ ...sarDataset, source_kind: 'csv', source_project_id: null });
    const created = vi.fn();
    render(<SARImport active sourceProjectId={null} onCreated={created} />);
    await userEvent.click(screen.getByRole('button', { name: 'CSV file' }));
    const file = new File(
      ['identifier_label,smiles,metric,value\n007B,CCO,IC50,<10'],
      csvPreview.filename,
      { type: 'text/csv' },
    );
    await userEvent.upload(screen.getByLabelText('Choose a CSV file'), file);
    expect(preview).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Preview on server' }));
    expect(await screen.findByLabelText('Metric name column (optional)')).toHaveValue('metric');
    expect(screen.getByLabelText('Source identifier column')).toHaveValue('identifier_label');
    expect(screen.getByLabelText('SMILES column')).toHaveValue('smiles');
    expect(screen.getByRole('checkbox', { name: 'value' })).toBeChecked();
    expect(screen.getByLabelText('Unit column (optional)')).toHaveValue('unit');
    expect(screen.getByText('<10')).toBeVisible();
    expect(create).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Create CSV dataset' }));
    await waitFor(() => expect(created).toHaveBeenCalledOnce());
    expect(preview).toHaveBeenCalledExactlyOnceWith(file);
    expect(create.mock.calls[0]?.[0]).toMatchObject({
      token: csvPreview.token,
      id_column: 'identifier_label',
      activity_columns: ['value'],
      metric_column: 'metric',
      target_column: 'target',
      assay_column: 'assay',
      request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
    });
  });
  it('retains the exact request ID and payload on an uncertain snapshot; retries only by explicit action', async () => {
    const create = vi
      .spyOn(sarApi, 'createProject')
      .mockRejectedValueOnce(
        new ApiError(
          0,
          'network_error',
          'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
          true,
        ),
      )
      .mockResolvedValueOnce(sarDataset);
    const created = vi.fn();
    render(<SARImport active sourceProjectId="project-control" onCreated={created} />);
    await screen.findByRole('option', { name: '原文项目' });
    await userEvent.click(screen.getByText('Name (optional)'));
    await userEvent.type(screen.getByLabelText('Dataset title'), 'frozen draft');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    const retry = await screen.findByRole('button', {
      name: 'I checked server state; retry with the same request identity',
    });
    expect(create).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Dataset title')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    await userEvent.click(retry);
    await waitFor(() => expect(created).toHaveBeenCalledWith(sarDataset));
    expect(create.mock.calls[1]?.[0]).toBe(create.mock.calls[0]?.[0]);
  });
  it('does not replay an uncertain staging upload with no idempotency contract', async () => {
    const preview = vi
      .spyOn(sarApi, 'preview')
      .mockRejectedValue(
        new ApiError(
          0,
          'network_error',
          'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
          true,
        ),
      );
    render(<SARImport active sourceProjectId={null} onCreated={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'CSV file' }));
    await userEvent.upload(
      screen.getByLabelText('Choose a CSV file'),
      new File(['id,smiles'], 'source.csv'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Preview on server' }));
    await screen.findByRole('alert');
    expect(preview).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: /retry with the same/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview on server' })).toBeDisabled();
  });
  it('cleans up only the explicitly discarded staging token', async () => {
    vi.spyOn(sarApi, 'preview').mockResolvedValue(csvPreview);
    const discard = vi.spyOn(sarApi, 'discardPreview').mockResolvedValue(undefined);
    render(<SARImport active sourceProjectId={null} onCreated={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'CSV file' }));
    await userEvent.upload(
      screen.getByLabelText('Choose a CSV file'),
      new File(['id,smiles'], 'source.csv'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Preview on server' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Discard CSV staging' }));
    await waitFor(() => expect(screen.getByLabelText('Choose a CSV file')).toBeVisible());
    expect(discard).toHaveBeenCalledExactlyOnceWith(csvPreview.token);
  });
  it('preserves mapping drafts and raw column names across languages without submitting', async () => {
    const submit = vi.fn();
    render(<CSVMappingForm preview={csvPreview} disabled={false} onSubmit={submit} />);
    const title = screen.getByLabelText('Dataset title');
    await userEvent.clear(title);
    await userEvent.type(title, 'draft 中文');
    await userEvent.selectOptions(screen.getByLabelText('Metric name column (optional)'), '');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('数据集名称')).toBe(title);
    expect(title).toHaveValue('draft 中文');
    expect(screen.getByLabelText('指标名称列（可选）')).toHaveValue('');
    expect(screen.getByRole('checkbox', { name: 'value' })).toBeChecked();
    expect(submit).not.toHaveBeenCalled();
  });
});
