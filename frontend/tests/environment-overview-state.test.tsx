import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { setLocale } from '../src/i18n';
import { EnvironmentOverview } from '../src/features/environment/EnvironmentOverview';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';

beforeEach(() => setLocale('en'));
const actions = () => ({
  disabled: false,
  onSetup: vi.fn(),
  onInspect: vi.fn(),
  onDetails: vi.fn(),
});

it('distinguishes unverified present paths from missing or verified environments', () => {
  const catalog = readyEnvironmentCatalog();
  catalog.components = catalog.components.map((component) => ({
    ...component,
    verification: 'unchecked',
    status: 'unchecked',
    installable: false,
  }));
  render(<EnvironmentOverview catalog={catalog} {...actions()} />);
  expect(screen.getByRole('status', { name: 'Environment readiness' })).toHaveTextContent(
    'Check required · 8 components',
  );
  expect(screen.getByRole('button', { name: 'Check all components' })).toHaveClass('primary');
  expect(screen.getByRole('button', { name: 'Set up complete environment' })).toBeDisabled();
  expect(screen.queryByText('Ready 0/8')).not.toBeInTheDocument();
});

it('keeps current ready counts and the remaining recheck need separate', () => {
  const catalog = readyEnvironmentCatalog();
  catalog.components[0] = { ...catalog.components[0]!, status: 'unchecked', verification: 'stale' };
  render(<EnvironmentOverview catalog={catalog} {...actions()} />);
  expect(screen.getByRole('status', { name: 'Environment readiness' })).toHaveTextContent(
    'Ready 7/8 · 1 awaiting check',
  );
  expect(screen.queryByRole('button', { name: 'Environment ready' })).not.toBeInTheDocument();
});

it('does not describe known missing paths as unknown checks or change the full setup action', () => {
  render(<EnvironmentOverview catalog={completeEnvironmentCatalog()} {...actions()} />);
  expect(screen.getByRole('status', { name: 'Environment readiness' })).toHaveTextContent(
    'Ready 0/8',
  );
  expect(screen.getByRole('button', { name: 'Set up complete environment' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Set up complete environment' })).toHaveClass(
    'primary',
  );
});
