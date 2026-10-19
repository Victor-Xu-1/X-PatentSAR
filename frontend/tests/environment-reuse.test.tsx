import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import {
  decodeEnvironmentOperation,
  decodeEnvironmentRequest,
  matchesEnvironmentRequest,
} from '../src/api/environmentDecoders';
import { ReuseTextOCRDialog } from '../src/features/environment/ReuseTextOCRDialog';
import { setLocale } from '../src/i18n';
import { completeEnvironmentCatalog } from './environment-setup-fixtures';
import { environmentOperation } from './environment-fixtures';

beforeEach(() => setLocale('en'));
const source = { python: '/srv/existing/bin/python', models: '/mnt/e/existing/model' };
const request = {
  action: 'reuse' as const,
  component_ids: ['text-ocr', 'text-ocr-models'] as const,
  request_id: 'controlled-reuse-1234',
  expected_revision: 3,
  reuse_source: source,
};

it('retains exact source ownership through decoding and recovery, without changing old request shape', () => {
  const input = { ...request, component_ids: [...request.component_ids] };
  expect(decodeEnvironmentRequest(input)).toEqual(input);
  const operation = {
    ...environmentOperation,
    action: 'reuse' as const,
    component_ids: [...request.component_ids],
    completed_components: [],
    reuse_source: source,
    request_id: request.request_id,
  };
  expect(decodeEnvironmentOperation(operation)).toEqual(operation);
  expect(matchesEnvironmentRequest(operation, input)).toBe(true);
  expect(
    matchesEnvironmentRequest(
      { ...operation, reuse_source: { ...source, models: '/another/model' } },
      input,
    ),
  ).toBe(false);
  const old = {
    action: 'inspect',
    component_ids: ['base'],
    request_id: request.request_id,
    expected_revision: 3,
  };
  expect(decodeEnvironmentRequest(old)).toEqual(old);
  for (const reuse_source of [
    undefined,
    { ...source, python: '/mnt/e/python' },
    { ...source, models: '/source/../model' },
    { ...source, models: 'https://invalid.test' },
  ])
    expect(() => decodeEnvironmentRequest({ ...input, reuse_source })).toThrow();
  expect(() => decodeEnvironmentOperation({ ...operation, reuse_source: undefined })).toThrow();
});

it('requires local-copy consent and preserves literal paths across language switching', async () => {
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  const props = {
    catalog: completeEnvironmentCatalog(),
    busy: false,
    disabled: false,
    error: null,
    recovery: null,
    onClose: vi.fn(),
    onConfirm,
  };
  const view = render(<ReuseTextOCRDialog {...props} />);
  const dialog = screen.getByRole('dialog', { name: 'Reuse existing text OCR' });
  const submit = within(dialog).getByRole('button', { name: 'Verify and reuse' });
  expect(submit).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText('Existing Linux Python interpreter'), {
    target: { value: source.python },
  });
  fireEvent.change(within(dialog).getByLabelText('Existing model directory'), {
    target: { value: source.models },
  });
  expect(submit).toBeDisabled();
  await userEvent.click(within(dialog).getByRole('checkbox'));
  expect(submit).toBeEnabled();
  setLocale('zh-CN');
  view.rerender(<ReuseTextOCRDialog {...props} />);
  expect(screen.getByLabelText('现有 Linux Python 解释器')).toHaveValue(source.python);
  expect(screen.getByLabelText('现有权重目录')).toHaveValue(source.models);
  await userEvent.click(screen.getByRole('button', { name: '验证并复用' }));
  await waitFor(() =>
    expect(onConfirm).toHaveBeenCalledExactlyOnceWith(source, props.catalog.settings.revision),
  );
});

it('refuses a stale revision and leaves user input unchanged', async () => {
  const onConfirm = vi.fn();
  const catalog = completeEnvironmentCatalog();
  const props = {
    catalog,
    busy: false,
    disabled: false,
    error: null,
    recovery: null,
    onClose: vi.fn(),
    onConfirm,
  };
  const view = render(<ReuseTextOCRDialog {...props} />);
  fireEvent.change(screen.getByLabelText('Existing Linux Python interpreter'), {
    target: { value: source.python },
  });
  fireEvent.change(screen.getByLabelText('Existing model directory'), {
    target: { value: source.models },
  });
  await userEvent.click(screen.getByRole('checkbox'));
  view.rerender(
    <ReuseTextOCRDialog
      {...props}
      catalog={{
        ...catalog,
        settings: { ...catalog.settings, revision: catalog.settings.revision + 1 },
      }}
    />,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('Environment settings changed');
  expect(screen.getByRole('button', { name: 'Verify and reuse' })).toBeDisabled();
  expect(screen.getByLabelText('Existing model directory')).toHaveValue(source.models);
  expect(onConfirm).not.toHaveBeenCalled();
});
