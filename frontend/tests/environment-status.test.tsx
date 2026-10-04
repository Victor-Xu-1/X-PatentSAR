import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { EnvironmentComponent } from '../src/api/environmentTypes';
import { decodeEnvironmentCatalog } from '../src/api/environmentDecoders';
import { ComponentLibrary } from '../src/features/environment/ComponentLibrary';
import { RecommendedBundles } from '../src/features/environment/RecommendedBundles';
import { environmentCatalog } from './environment-fixtures';

function component(overrides: Partial<EnvironmentComponent> = {}): EnvironmentComponent {
  return {
    ...environmentCatalog.components[1]!,
    status: 'ready',
    presence: 'present',
    verification: 'current',
    location: '/srv/wsl/envs/verified-base/bin/python',
    detected_version: 'measured-base',
    checked_at: '2026-10-04T12:00:00Z',
    checks: [{ name: '实测检查', ok: true, message: '实际检查通过' }],
    problem: null,
    last_check: null,
    ...overrides,
  };
}
function library(value: EnvironmentComponent) {
  const handlers = { onInspect: vi.fn(), onInstall: vi.fn() };
  render(<ComponentLibrary components={[value]} disabled={false} {...handlers} />);
  return { ...handlers, row: screen.getByRole('article') };
}

describe('truthful component presence and verification', () => {
  it('shows the binding path, separate target/measured versions and current time before opening details', async () => {
    const value = component();
    const { row, onInstall } = library(value);
    expect(within(row).getByText('已安装·已验证')).toBeVisible();
    expect(row.querySelector('.component-location')).toBeVisible();
    expect(row.querySelector('.component-location')).toHaveAttribute('title', value.location);
    expect(row.querySelector('.component-title')).toHaveTextContent('目标：locked-base');
    expect(row.querySelector('.component-title')).toHaveTextContent('实测：measured-base');
    expect(row.querySelector('time')).toHaveAttribute('datetime', value.checked_at);
    expect(within(row).getByRole('button', { name: '已安装 基础运行环境' })).toBeDisabled();
    await userEvent.click(within(row).getByRole('button', { name: '已安装 基础运行环境' }));
    expect(onInstall).not.toHaveBeenCalled();
  });
  it.each(['unchecked', 'stale'] as const)(
    'does not display old top-level versions/checks as current for %s components',
    async (verification) => {
      const { row, onInstall, onInspect } = library(
        component({
          verification,
          detected_version: 'not-current-version',
          checked_at: '2020-01-01T00:00:00Z',
          checks: [{ name: '不得显示为当前', ok: true, message: '过期内容' }],
          problem: '不是当前错误',
        }),
      );
      expect(row.querySelector('.badge')).toHaveTextContent(
        verification === 'stale' ? '已存在·待复检' : '已存在·待检测',
      );
      expect(row).not.toHaveTextContent('not-current-version');
      expect(row).not.toHaveTextContent('不得显示为当前');
      expect(row).not.toHaveTextContent('不是当前错误');
      expect(row.querySelector('time')).toBeNull();
      expect(within(row).getByRole('button', { name: '先检测 基础运行环境' })).toBeDisabled();
      await userEvent.click(within(row).getByRole('button', { name: '检测 基础运行环境' }));
      expect(onInspect).toHaveBeenCalledWith(['base']);
      expect(onInstall).not.toHaveBeenCalled();
    },
  );
  it('discloses a stale last-check result separately with its own measured version and unknown legacy time', async () => {
    const { row } = library(
      component({
        status: 'unchecked',
        verification: 'stale',
        last_check: {
          status: 'incompatible',
          detected_version: 'previous-version',
          checked_at: null,
          checks: [{ name: '上次版本检查', ok: false, message: '旧版不匹配' }],
          problem: '旧版错误',
        },
      }),
    );
    expect(row.querySelector('.component-title')).not.toHaveTextContent('previous-version');
    await userEvent.click(within(row).getByText('版本、来源与检查'));
    const history = within(row).getByLabelText('上次检测结果');
    expect(history).toHaveTextContent('已过期');
    expect(history).toHaveTextContent('上次实测版本：previous-version');
    expect(history).toHaveTextContent('时间未知');
    expect(history).toHaveTextContent('版本不兼容');
    expect(history).toHaveTextContent('旧版不匹配');
    expect(row.querySelector('.badge')).not.toHaveTextContent('版本不兼容');
  });
  it('does not promote a legacy ready DTO or a path to presence/current evidence', () => {
    const legacy: Record<string, unknown> = { ...component() };
    for (const field of ['presence', 'verification', 'checked_at', 'last_check'])
      delete legacy[field];
    const value = decodeEnvironmentCatalog({
      ...environmentCatalog,
      components: [legacy],
    }).components[0]!;
    const { row } = library(value);
    expect(row.querySelector('.badge')).toHaveTextContent('状态未知·待检测');
    expect(row).not.toHaveTextContent('已安装·已验证');
    expect(row).not.toHaveTextContent('measured-base');
    expect(within(row).getByRole('button', { name: '先检测 基础运行环境' })).toBeDisabled();
  });
  it('uses only the last-check timestamp for stale bindings, never a stale top-level timestamp', () => {
    const { row } = library(
      component({
        status: 'unchecked',
        verification: 'stale',
        checked_at: '2026-10-04T12:00:00Z',
        last_check: {
          status: 'ready',
          detected_version: 'older-measured-version',
          checked_at: '2025-01-01T10:00:00Z',
          checks: [],
          problem: null,
        },
      }),
    );
    expect(row.querySelector('.component-checked-at time')).toHaveAttribute(
      'datetime',
      '2025-01-01T10:00:00Z',
    );
    expect(row.querySelector('.component-title')).not.toHaveTextContent('older-measured-version');
  });
  it('keeps a missing per-component current timestamp unknown rather than implying detection time', () => {
    const { row } = library(component({ checked_at: null }));
    expect(row.querySelector('.component-checked-at')).toHaveTextContent('时间未知');
    expect(row.querySelector('time')).toBeNull();
  });
  it.each([
    ['missing', '缺失'],
    ['unconfigured', '未配置'],
  ] as const)(
    'keeps %s distinct and only offers explicit approved installation',
    async (presence, label) => {
      const { row, onInstall } = library(
        component({
          status: presence,
          presence,
          verification: 'unchecked',
          location: null,
        }),
      );
      expect(row.querySelector('.badge')).toHaveTextContent(label);
      expect(row.querySelector('.component-location')).toHaveTextContent('未配置');
      await userEvent.click(within(row).getByRole('button', { name: '安装 基础运行环境' }));
      expect(onInstall).toHaveBeenCalledWith(['base']);
    },
  );
  it.each([
    ['partial', '不完整'],
    ['incompatible', '版本不兼容'],
    ['error', '检测失败'],
  ] as const)(
    'shows current %s failure without treating existing files as absent',
    async (status, label) => {
      const { row, onInstall } = library(component({ status, problem: '实际失败原因' }));
      expect(row.querySelector('.badge')).toHaveTextContent(label);
      expect(row).not.toHaveTextContent('缺失');
      expect(within(row).getByText('实际失败原因')).toBeVisible();
      await userEvent.click(within(row).getByRole('button', { name: '修复 基础运行环境' }));
      expect(onInstall).toHaveBeenCalledWith(['base']);
    },
  );
  it('does not offer ordinary install for a current detection error even when presence is missing', () => {
    const { row } = library(component({ status: 'error', presence: 'missing' }));
    expect(row.querySelector('.badge')).toHaveTextContent('检测失败');
    expect(within(row).getByRole('button', { name: '先检测 基础运行环境' })).toBeDisabled();
  });
  it.each(['配置路径无效', '配置路径类型错误', '配置路径无法访问'])(
    'shows a real unchecked path error without inventing measured evidence: %s',
    async (problem) => {
      const { row, onInspect, onInstall } = library(
        component({
          presence: 'unknown',
          status: 'error',
          verification: 'unchecked',
          problem,
        }),
      );
      expect(row.querySelector('.badge')).toHaveTextContent('检测失败');
      expect(within(row).getByText(problem)).toBeVisible();
      expect(row).not.toHaveTextContent('measured-base');
      expect(row).not.toHaveTextContent('实际检查通过');
      expect(row.querySelector('time')).toBeNull();
      expect(within(row).getByRole('button', { name: '先检测 基础运行环境' })).toBeDisabled();
      await userEvent.click(within(row).getByRole('button', { name: '检测 基础运行环境' }));
      expect(onInspect).toHaveBeenCalledWith(['base']);
      expect(onInstall).not.toHaveBeenCalled();
    },
  );
  it('shows missing dependencies as a verified failure despite an existing interpreter', async () => {
    const { row, onInstall } = library(
      component({
        status: 'missing',
        presence: 'present',
        verification: 'current',
        problem: '缺少锁定依赖 RDKit',
        checks: [{ name: 'RDKit', ok: false, message: '依赖缺失' }],
      }),
    );
    expect(row.querySelector('.badge')).toHaveTextContent('缺少依赖');
    expect(row).not.toHaveTextContent('已存在·待检测');
    expect(row).not.toHaveTextContent('已安装·已验证');
    expect(within(row).getByText('缺少锁定依赖 RDKit')).toBeVisible();
    await userEvent.click(within(row).getByText('版本、来源与检查'));
    expect(row).toHaveTextContent('未通过 · RDKit：依赖缺失');
    await userEvent.click(within(row).getByRole('button', { name: '修复 基础运行环境' }));
    expect(onInstall).toHaveBeenCalledWith(['base']);
  });
});

describe('recommended bundles use the same dependency closure and evidence', () => {
  function bundles(values: EnvironmentComponent[]) {
    const handlers = { onInstall: vi.fn(), onInspect: vi.fn() };
    render(
      <RecommendedBundles
        presets={[environmentCatalog.presets[0]!]}
        components={values}
        disabled={false}
        {...handlers}
      />,
    );
    return handlers;
  }
  function installer() {
    return {
      ...environmentCatalog.components[0]!,
      presence: 'present' as const,
      verification: 'current' as const,
    };
  }
  it('disables a fully current verified-ready bundle', async () => {
    const handlers = bundles([installer(), component()]);
    const button = screen.getByRole('button', { name: '已就绪 推荐基础组合' });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(handlers.onInstall).not.toHaveBeenCalled();
    expect(handlers.onInspect).not.toHaveBeenCalled();
  });
  it.each(['unchecked', 'stale'] as const)(
    'inspects an existing %s bundle instead of installing it',
    async (verification) => {
      const handlers = bundles([installer(), component({ verification })]);
      await userEvent.click(screen.getByRole('button', { name: '检测组合 推荐基础组合' }));
      expect(handlers.onInspect).toHaveBeenCalledWith(['installer', 'base']);
      expect(handlers.onInstall).not.toHaveBeenCalled();
    },
  );
  it('inspects a missing bundle when a prerequisite has unknown or stale evidence', async () => {
    const handlers = bundles([
      { ...installer(), verification: 'stale' },
      component({ status: 'missing', presence: 'missing', verification: 'unchecked' }),
    ]);
    await userEvent.click(screen.getByRole('button', { name: '检测组合 推荐基础组合' }));
    expect(handlers.onInspect).toHaveBeenCalledWith(['installer', 'base']);
    expect(handlers.onInstall).not.toHaveBeenCalled();
  });
  it('installs a genuinely missing bundle while retaining a ready noninstallable dependency for reuse', async () => {
    const handlers = bundles([
      { ...installer(), installable: false },
      component({ status: 'missing', presence: 'missing', verification: 'unchecked' }),
    ]);
    const button = screen.getByRole('button', { name: '安装组合 推荐基础组合' });
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(handlers.onInstall).toHaveBeenCalledWith(['installer', 'base']);
  });
  it('disables installation when a genuinely missing member is not supported', () => {
    bundles([
      installer(),
      component({
        status: 'missing',
        presence: 'missing',
        verification: 'unchecked',
        installable: false,
      }),
    ]);
    expect(screen.getByRole('button', { name: '安装组合 推荐基础组合' })).toBeDisabled();
  });
});
