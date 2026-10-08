import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Job } from '../src/api/types';
import { JobActions } from '../src/features/jobs/JobActions';
import { JobRecord } from '../src/features/jobs/JobRecord';
import { StageObservation } from '../src/features/jobs/StageObservation';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { llmReason, llmTestReason } from '../src/features/llm/llmMessages';
import { job, project } from './fixtures';
import { recoveryJob, recoverySettings } from './llm-recovery-fixtures';

describe('source-backed LLM recovery details only', () => {
  it('shows no fabricated recovery or repair zeroes for an old DTO', () => {
    render(<JobRecord job={job} expanded />);
    expect(screen.queryByRole('region', { name: 'LLM 局部修复' })).not.toBeInTheDocument();
    expect(screen.queryByText(/剩余调用|来源区域|待修复/)).not.toBeInTheDocument();
  });

  it('keeps real failure/budget and settings link inside on-demand task details', async () => {
    render(<JobRecord job={recoveryJob} />);
    const region = screen.getByRole('region', { name: 'LLM 局部修复', hidden: true });
    expect(region).not.toBeVisible();
    await userEvent.click(screen.getByText('任务详情', { selector: 'summary' }));
    expect(region).toBeVisible();
    expect(region).toHaveTextContent('认证失败');
    expect(region).toHaveTextContent('剩余调用 3 次');
    expect(within(region).getByRole('link', { name: '配置 LLM API' })).toHaveAttribute(
      'href',
      '#/settings',
    );
    expect(within(region).queryByRole('button')).not.toBeInTheDocument();
  });

  it('labels null budgets and missing retry duration as unknown rather than zero', () => {
    render(
      <JobRecord
        expanded
        job={{
          ...recoveryJob,
          llm_recovery: {
            ...recoveryJob.llm_recovery!,
            status: 'cooldown',
            reason: 'rate_limited',
            remaining_calls: null,
            retry_after_seconds: null,
          },
        }}
      />,
    );
    const region = screen.getByRole('region', { name: 'LLM 局部修复' });
    expect(region).toHaveTextContent('剩余调用次数未知');
    expect(region).toHaveTextContent('重试等待时间未知');
    expect(region).not.toHaveTextContent('0 次');
    expect(region).not.toHaveTextContent('0 秒');
  });

  it('shows actual exhaustion and bounded server wait without inventing progress/accuracy', () => {
    render(
      <JobRecord
        expanded
        job={{
          ...recoveryJob,
          llm_recovery: {
            ...recoveryJob.llm_recovery!,
            status: 'exhausted',
            reason: 'budget_exhausted',
            remaining_calls: 0,
            retry_after_seconds: 45,
          },
        }}
      />,
    );
    const region = screen.getByRole('region', { name: 'LLM 局部修复' });
    expect(region).toHaveTextContent('预算耗尽');
    expect(region).toHaveTextContent('剩余调用 0 次');
    expect(region).toHaveTextContent('本次重试等待 45 秒（服务端观察）');
    expect(region).toHaveTextContent('不会重置配额');
    expect(region).not.toHaveTextContent(/已修复|准确率|100%/);
  });

  it('does not echo an unknown provider reason or infer provider verification from ready', () => {
    render(
      <JobRecord
        expanded
        job={{
          ...recoveryJob,
          llm_recovery: {
            ...recoveryJob.llm_recovery!,
            status: 'ready',
            reason: 'synthetic-sensitive-provider-error',
          },
        }}
      />,
    );
    const region = screen.getByRole('region', { name: 'LLM 局部修复' });
    expect(region).toHaveTextContent('可尝试局部修复');
    expect(region).not.toHaveTextContent('synthetic-sensitive-provider-error');
    expect(region).not.toHaveTextContent(/已修复|已验收|模型可用|模型验证通过/);
  });

  it.each([
    { ...recoveryJob, llm_recovery: undefined },
    { ...recoveryJob, llm_recovery: { ...recoveryJob.llm_recovery!, can_reauthorize: false } },
    { ...recoveryJob, can_resume: false },
    { ...recoveryJob, status: 'running' },
    { ...recoveryJob, status: 'queued' },
    { ...recoveryJob, status: 'complete' },
    { ...recoveryJob, project_id: 'foreign-project' },
  ])('does not offer reauthorization without every server/job capability %#', (current) => {
    const { llm_recovery, ...rest } = current;
    const value: Job =
      llm_recovery === undefined ? (rest as Job) : ({ ...rest, llm_recovery } as Job);
    const transport = vi.fn();
    vi.stubGlobal('fetch', transport);
    render(<JobActions project={project} job={value} ready onChange={vi.fn()} />);
    expect(
      screen.queryByRole('button', { name: '更新 API 授权', hidden: true }),
    ).not.toBeInTheDocument();
    expect(transport).not.toHaveBeenCalled();
  });

  it.each(['failed', 'cancelled', 'interrupted'] as const)(
    'offers exactly one small action for a resumable %s job without requiring model startup',
    (status) => {
      render(
        <JobActions
          project={project}
          job={{ ...recoveryJob, status }}
          ready={false}
          onChange={vi.fn()}
        />,
      );
      expect(screen.getAllByRole('button', { name: '更新 API 授权', hidden: true })).toHaveLength(
        1,
      );
      expect(screen.getByRole('button', { name: '更新 API 授权', hidden: true })).toBeEnabled();
      expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    },
  );

  it('shows region/unresolved counters only from actual repair evidence', () => {
    const stage = { ...job.stages[0]!, repair: { regions: 7, unresolved: 2 } };
    const { rerender } = render(<StageObservation job={job} name={stage.name} stage={stage} />);
    const count = screen.getByText('来源区域 7 · 待修复 2');
    expect(count).not.toBeVisible();
    fireEvent.click(screen.getByText('文档解析', { selector: 'strong' }));
    expect(count).toBeVisible();
    rerender(<StageObservation job={job} name={stage.name} stage={job.stages[0]} />);
    expect(screen.queryByText(/来源区域|待修复/)).not.toBeInTheDocument();
    rerender(
      <StageObservation
        job={job}
        name={stage.name}
        stage={{ ...stage, repair: { regions: 0, unresolved: 0 } }}
      />,
    );
    expect(screen.getByText('来源区域 0 · 待修复 0')).toBeVisible();
  });
});

describe('actionable credential-free nonce test failures', () => {
  it.each([
    ['invalid_response', /随机验证样本.*协议.*JSON/],
    ['transport_unavailable', /地址.*网络.*服务状态/],
    ['settings_changed', /配置或授权已改变.*刷新/],
    ['input_budget', /输入预算.*维护者/],
    ['authentication_failed', /认证失败.*密钥.*权限/],
    ['rate_limited', /限流.*额度/],
    ['provider_unavailable', /服务暂不可用.*服务商/],
    ['timeout', /超时.*网络/],
    ['cancelled', /已取消/],
    ['cache_unavailable', /缓存不可用.*存储.*权限/],
    ['unsafe_cache', /安全检查.*不要删除缓存/],
  ])(
    'renders current synthetic %s failure with a Chinese corrective action',
    async (reason, message) => {
      const current = {
        ...recoverySettings,
        last_test: {
          status: 'failed' as const,
          reason: reason as string,
          settings_revision: recoverySettings.revision,
          checked_at: '2026-10-08T00:00:00Z',
        },
      };
      const testApi = {
        settings: vi.fn().mockResolvedValue(current),
        save: vi.fn(),
        test: vi.fn(),
      };
      render(<LLMApiPanel api={testApi} />);
      await userEvent.click(await screen.findByRole('button', { name: '配置' }));
      expect(screen.getByText(/接口测试失败/)).toHaveTextContent(message as RegExp);
      expect(screen.getByText(/已配置不等于模型可用/)).toBeVisible();
      expect(testApi.test).not.toHaveBeenCalled();
    },
  );

  it('never treats a job invalid_response as a synthetic nonce test or echoes unknown text', () => {
    expect(llmReason('invalid_response')).not.toContain('随机验证样本');
    expect(llmTestReason('invalid_response')).toContain('随机验证样本');
    expect(llmTestReason('synthetic-sensitive-message')).not.toContain(
      'synthetic-sensitive-message',
    );
  });

  it.each([
    ['invalid_evidence_selection', /证据回答不合法.*未采用/],
    ['authorization_revoked', /授权已撤回/],
    ['control_unavailable', /控制状态不可用.*不会绕过/],
    ['carrier_error', /启动或清理失败.*不会自动重试/],
    ['configuration_unavailable', /配置不可用.*环境管理/],
    ['redirect_rejected', /重定向.*拒绝.*不会跟随/],
    ['http_error', /HTTP 错误.*服务地址/],
    ['call_budget', /预算已耗尽.*不会重置配额/],
  ])('uses the approved control-state message for %s', (reason, message) => {
    expect(llmReason(reason as string)).toMatch(message as RegExp);
  });

  it.each([
    { state: 'ready', hint: false, can_reauthorize: false },
    { state: 'disabled', hint: false, can_reauthorize: false },
    { state: 'cooldown', hint: false, can_reauthorize: false },
    { state: 'exhausted', hint: false, can_reauthorize: false },
    { state: 'unavailable', hint: false, can_reauthorize: false },
    { state: 'blocked', hint: true, can_reauthorize: false },
    { state: 'ready', hint: true, can_reauthorize: true },
  ])(
    'keeps the compact workbench free of persistent quotas: $state / $can_reauthorize',
    ({ state, hint, can_reauthorize }) => {
      render(
        <JobActions
          project={project}
          job={{
            ...recoveryJob,
            llm_recovery: {
              ...recoveryJob.llm_recovery!,
              status: state as NonNullable<Job['llm_recovery']>['status'],
              can_reauthorize,
            },
          }}
          ready
          onChange={vi.fn()}
          compact
        />,
      );
      expect(screen.queryByText('API 待核对') !== null).toBe(hint);
      expect(screen.queryByText(/剩余调用|本次重试等待|局部修复预算/)).not.toBeInTheDocument();
    },
  );
});
