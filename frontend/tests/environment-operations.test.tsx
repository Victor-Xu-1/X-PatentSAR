import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { EnvironmentOperations } from '../src/features/environment/EnvironmentOperations';
import { environmentOperation } from './environment-fixtures';

const properties = () => ({
  selected: environmentOperation,
  selectionId: environmentOperation.id,
  loading: false,
  catalogAvailable: true,
  operations: [environmentOperation],
  busy: false,
  readError: false,
  onSelect: vi.fn(),
  onCancel: vi.fn().mockResolvedValue(null),
  onReload: vi.fn(),
});
it('pins cancellation to the originally confirmed operation and refuses a stale target after navigation', async () => {
  const props = properties();
  const view = render(<EnvironmentOperations {...props} />);
  await userEvent.click(screen.getByRole('button', { name: '取消此环境操作' }));
  view.rerender(
    <EnvironmentOperations
      {...props}
      selected={{ ...environmentOperation, id: 'another-owned-operation' }}
      selectionId="another-owned-operation"
    />,
  );
  expect(screen.getByRole('dialog')).toHaveTextContent(environmentOperation.id);
  expect(screen.getByRole('button', { name: '确认取消此环境操作' })).toBeDisabled();
  expect(props.onCancel).not.toHaveBeenCalled();
});
it('distinguishes completed installation from actual applied configuration and never invents progress', () => {
  const props = properties();
  const operation = {
    ...environmentOperation,
    status: 'complete' as const,
    completed_components: environmentOperation.component_ids,
    applied: false,
  };
  const view = render(<EnvironmentOperations {...props} selected={operation} />);
  expect(screen.getByText(/配置尚未应用/)).toBeVisible();
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '2');
  expect(screen.getByRole('progressbar')).toHaveAttribute('max', '2');
  expect(screen.queryByRole('button', { name: '取消此环境操作' })).not.toBeInTheDocument();
  view.rerender(<EnvironmentOperations {...props} selected={{ ...operation, applied: true }} />);
  expect(screen.getByText(/服务端已验证并应用环境配置/)).toBeVisible();
});
