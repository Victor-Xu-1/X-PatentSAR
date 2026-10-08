import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { llmApi } from '../src/api/llmApi';
import type { LLMApi } from '../src/api/llmApi';
import type { Job, Stage } from '../src/api/types';
import { combineCatalogs } from '../src/i18n/catalog';
import { common } from '../src/i18n/catalogs/common';
import { operations } from '../src/i18n/catalogs/operations';
import { errorText, setLocale, t, UiError } from '../src/i18n';
import { ComponentLibrary } from '../src/features/environment/ComponentLibrary';
import { EnvironmentPage } from '../src/features/environment/EnvironmentPage';
import { EnvironmentProgress } from '../src/features/environment/EnvironmentProgress';
import { InstallConfirmation } from '../src/features/environment/InstallConfirmation';
import { StorageLocations } from '../src/features/environment/StorageLocations';
import { storageLocationFields } from '../src/features/environment/storageLocations';
import { DeletionDialog } from '../src/features/history/DeletionDialog';
import { HistoryDialog } from '../src/features/history/HistoryDialog';
import { JobRecord } from '../src/features/jobs/JobRecord';
import { LLMRecovery } from '../src/features/jobs/LLMRecovery';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { StageObservation } from '../src/features/jobs/StageObservation';
import { LLMApiPanel } from '../src/features/llm/LLMApiPanel';
import { llmStatusLabels } from '../src/features/llm/llmMessages';
import { acceptanceIssueCount, acceptanceIssueGroups } from '../src/model/acceptanceIssues';
import { pendingEnvironmentKey } from '../src/model/environmentRecovery';
import { jobStageProgressText } from '../src/model/jobPresentation';
import { stageProgressText } from '../src/model/extraction';
import { activityText, stageLabels } from '../src/model/presentation';
import { environmentOperation } from './environment-fixtures';
import { completeEnvironmentCatalog, readyEnvironmentCatalog } from './environment-setup-fixtures';
import { health, job } from './fixtures';
import { historyEntry, historyList, trashed } from './history-fixtures';
import { recoveryJob, recoverySettings } from './llm-recovery-fixtures';

const switchTo = (locale: 'en' | 'zh-CN') => act(() => setLocale(locale));
const syntheticKey = 'synthetic-unit-key-not-a-provider-credential';
const controlledLLM = (): LLMApi => ({
  settings: vi.fn().mockResolvedValue(recoverySettings),
  save: vi.fn().mockResolvedValue(recoverySettings),
  test: vi.fn(),
});
async function openLLM(client = controlledLLM()) {
  render(<LLMApiPanel api={client} />);
  const opener = await screen.findByRole('button', { name: 'Configure' });
  await waitFor(() => expect(opener).toBeEnabled());
  await userEvent.click(opener);
  return client;
}
const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const progress: NonNullable<Stage['progress']> = {
  completed: 10,
  total: 10,
  cache_hits: 4,
  failures: 2,
  device: 'cpu',
  peak_rss_mb: 512,
};
function rejectedJob(): Job {
  return {
    ...job,
    status: 'failed',
    error: { code: 'core_not_accepted', message: '设置已保存。' },
    task_note: '保存',
    stages: job.stages.map((stage) => ({
      ...stage,
      status: ['smiles', 'final', 'qa'].includes(stage.name) ? 'failed' : 'ok',
      ...(stage.name === 'smiles' ? { count: 10, progress } : {}),
    })),
  };
}
beforeEach(() => {
  switchTo('en');
  sessionStorage.removeItem(pendingEnvironmentKey);
});
afterEach(() => {
  switchTo('en');
  sessionStorage.removeItem(pendingEnvironmentKey);
});

describe('operations locale: live presentation without state or data mutation', () => {
  it('keeps catalog placeholders exact and exported source labels locale-independent', () => {
    expect(() => combineCatalogs(common, operations)).not.toThrow();
    const placeholders = (value: string) =>
      [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    for (const [source, english] of Object.entries(operations)) {
      expect(english, source).not.toMatch(/[\u3400-\u9fff]/u);
      expect(placeholders(english), source).toEqual(placeholders(source));
    }
    switchTo('en');
    expect(stageLabels.classify).toBe('文档解析');
    expect(llmStatusLabels.ready).toBe('已配置');
    expect(storageLocationFields[0].label).toBe('集成环境安装目录');
    expect(t(stageLabels.classify)).toBe('Document parsing');
  });

  it('switches an open LLM draft and accessible names without remounting or requests', async () => {
    const client = await openLLM();
    change('Model', '设置已保存。');
    change('API key', syntheticKey);
    const model = screen.getByLabelText('Model');
    const dialog = screen.getByRole('dialog', { name: 'LLM API settings' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: 'LLM API 设置' })).toBe(dialog);
    expect(screen.getByLabelText('模型')).toBe(model);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'LLM API settings' })).toBe(dialog);
    expect(screen.getByLabelText('Model')).toBe(model);
    expect(model).toHaveValue('设置已保存。');
    expect(screen.getByLabelText('API key')).toHaveValue(syntheticKey);
    expect(screen.getByLabelText('API protocol')).toHaveValue('openai-compatible');
    expect(screen.getByLabelText('JSON format')).toHaveValue('json-schema');
    expect(screen.getByLabelText('Review mode')).toHaveValue('on-error');
    expect(screen.getByRole('checkbox', { name: /I consent to sending/ })).toBeChecked();
    expect(screen.getByText(/Up to 8 calls per task/)).toHaveTextContent('12000/16000 characters');
    switchTo('zh-CN');
    expect(screen.getByLabelText('模型')).toBe(model);
    expect(model).toHaveValue('设置已保存。');
    expect(client.settings).toHaveBeenCalledTimes(1);
    expect(client.save).not.toHaveBeenCalled();
    expect(client.test).not.toHaveBeenCalled();
  });

  it('relocalizes a stored LLM write error without resubmitting or exposing provider text', async () => {
    const client = controlledLLM();
    vi.mocked(client.save).mockRejectedValue(
      new ApiError(422, 'invalid', 'synthetic-private-provider-body'),
    );
    await openLLM(client);
    change('Model', 'changed-model');
    change('API key', syntheticKey);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings were not accepted.');
    switchTo('zh-CN');
    expect(await screen.findByRole('alert')).toHaveTextContent('配置未被接受');
    switchTo('en');
    expect(screen.getByRole('alert')).toHaveTextContent('Settings were not accepted.');
    expect(screen.queryByText(/synthetic-private-provider-body/)).not.toBeInTheDocument();
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toHaveTextContent('配置未被接受');
    expect(client.save).toHaveBeenCalledTimes(1);
    expect(client.test).not.toHaveBeenCalled();
  });

  it('preserves the explicit API test confirmation without sending a test on language changes', async () => {
    const client = await openLLM();
    await userEvent.click(screen.getByRole('button', { name: 'Test API' }));
    const confirmation = screen.getByRole('dialog', { name: 'Confirm API test' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认接口测试' })).toBe(confirmation);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Confirm API test' })).toBe(confirmation);
    expect(within(confirmation).getByText(/API charges may apply/)).toBeVisible();
    expect(
      within(confirmation).getByRole('button', { name: 'Confirm test request' }),
    ).toBeEnabled();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认接口测试' })).toBe(confirmation);
    expect(client.test).not.toHaveBeenCalled();
  });

  it('updates recovery reasons, quotas and an open authorization confirmation without renewing', async () => {
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    const renew = vi.spyOn(api, 'reauthorizeJobLLM');
    const controls = {
      eligible: true,
      disabled: false,
      acquire: vi.fn(() => true),
      release: vi.fn(),
      awaitRefresh: vi.fn(),
      onChange: vi.fn(),
    };
    render(<LLMRecovery job={recoveryJob} controls={controls} />);
    await userEvent.click(screen.getByRole('button', { name: 'Renew API authorization' }));
    await screen.findByText(recoverySettings.endpoint);
    const dialog = screen.getByRole('dialog', { name: 'Renew this task’s API authorization?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '更新此任务的 API 授权？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Renew this task’s API authorization?' })).toBe(
      dialog,
    );
    expect(screen.getByRole('region', { name: 'LLM local repair' })).toHaveTextContent(
      'Remaining calls: 3',
    );
    expect(screen.getByText(/API authentication failed/)).toBeVisible();
    expect(within(dialog).getByText('openai-compatible')).toBeVisible();
    expect(within(dialog).getByText(/Quota is not reset/)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '更新此任务的 API 授权？' })).toBe(dialog);
    expect(llmApi.settings).toHaveBeenCalledTimes(1);
    expect(renew).not.toHaveBeenCalled();
  });

  it('renders the English environment page and retains details without installing or reloading on a flip', async () => {
    switchTo('en');
    const read = vi.spyOn(api, 'environments').mockResolvedValue(completeEnvironmentCatalog());
    const install = vi.spyOn(api, 'createEnvironmentOperation');
    vi.spyOn(llmApi, 'settings').mockResolvedValue(recoverySettings);
    render(<EnvironmentPage product={health.product} operationId={null} onOperation={vi.fn()} />);
    expect(await screen.findByText('Ready 0/8')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Storage locations' }));
    const dialog = screen.getByRole('dialog', { name: 'Storage locations' });
    await userEvent.click(within(dialog).getByText('Environment details', { selector: 'summary' }));
    expect(
      within(dialog).getByRole('heading', { name: 'Local stereo-rescue runtime' }),
    ).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '存储位置' })).toBe(dialog);
    expect(
      within(dialog).getByText('环境详情', { selector: 'summary' }).closest('details'),
    ).toHaveAttribute('open');
    expect(read).toHaveBeenCalledTimes(1);
    expect(install).not.toHaveBeenCalled();
  });

  it('retains a storage draft and named validation error across English and Chinese', async () => {
    const settings = completeEnvironmentCatalog().settings;
    const save = vi.fn();
    render(
      <StorageLocations
        settings={settings}
        disabled={false}
        busy={false}
        requestError={null}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    change('Upload directory', '../专利');
    const input = screen.getByLabelText('Upload directory');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The upload directory must be within',
    );
    switchTo('zh-CN');
    expect(await screen.findByRole('alert')).toHaveTextContent('上传文件目录须位于');
    switchTo('en');
    expect(screen.getByLabelText('Upload directory')).toBe(input);
    expect(input).toHaveValue('../专利');
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The upload directory must be within the server-approved root ' + settings.allowed_data_root,
    );
    switchTo('zh-CN');
    expect(screen.getByRole('alert')).toHaveTextContent('上传文件目录须位于');
    expect(save).not.toHaveBeenCalled();
  });

  it('preserves download/license consent and the exact component plan without installing', async () => {
    const catalog = completeEnvironmentCatalog();
    const confirm = vi.fn();
    render(
      <InstallConfirmation
        plan={{
          scope: 'complete',
          components: catalog.components,
          settings: catalog.settings,
          requested: catalog.setup_component_ids,
        }}
        currentRevision={catalog.settings.revision}
        planCurrent
        busy={false}
        onClose={vi.fn()}
        onConfirm={confirm}
      />,
    );
    const dialog = screen.getByRole('dialog');
    const consent = within(dialog).getByRole('checkbox');
    expect(screen.getByRole('button', { name: 'Confirm download & installation' })).toBeDisabled();
    await userEvent.click(consent);
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '确认完整环境部署' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Confirm complete environment setup' })).toBe(dialog);
    expect(within(dialog).getByRole('checkbox')).toBe(consent);
    expect(consent).toBeChecked();
    expect(screen.getByRole('button', { name: 'Confirm download & installation' })).toBeEnabled();
    const ids = Array.from(dialog.querySelectorAll('[data-install-component]')).map((node) =>
      node.getAttribute('data-install-component'),
    );
    expect(ids).toEqual(catalog.setup_component_ids);
    for (const component of catalog.components) expect(dialog).toHaveTextContent(component.version);
    switchTo('zh-CN');
    expect(consent).toBeChecked();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('localizes reviewed component IDs while retaining paths, versions, licenses and diagnostics', () => {
    switchTo('en');
    const catalog = readyEnvironmentCatalog();
    const component = {
      ...catalog.components[0]!,
      version: '版本原文',
      detected_version: '实测原文',
      location: '/srv/wsl/envs/基础提取环境',
      license: '模型许可',
      problem: '设置已保存。',
      checks: [{ name: '模型', ok: true, message: '设置已保存。' }],
    };
    render(
      <ComponentLibrary
        components={[component]}
        disabled={false}
        onInspect={vi.fn()}
        onInstall={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Managed installer' })).toBeVisible();
    expect(screen.getByText('Target: 版本原文')).toBeVisible();
    expect(screen.getByText('Detected: 实测原文')).toBeVisible();
    expect(screen.getByText('Location: /srv/wsl/envs/基础提取环境')).toBeVisible();
    expect(screen.getByText('License: 模型许可')).toBeInTheDocument();
    expect(screen.getByText('Passed · 模型：设置已保存。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Installed Managed installer' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check Managed installer' })).toBeEnabled();
  });

  it('updates environment progress and cancel confirmation but keeps raw failures verbatim', async () => {
    const cancel = vi.fn();
    render(
      <EnvironmentProgress
        selected={{ ...environmentOperation, error: { code: 'raw', message: '设置已保存。' } }}
        selectionId={environmentOperation.id}
        loading={false}
        busy={false}
        readError={false}
        onCancel={cancel}
        onReload={vi.fn()}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: 'Cancel this environment operation' }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Cancel environment setup?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '取消环境配置？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Cancel environment setup?' })).toBe(dialog);
    expect(
      screen.getByRole('progressbar', { name: 'Completed environment components' }),
    ).toHaveAttribute('value', '1');
    expect(screen.getByText('设置已保存。')).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '取消环境配置？' })).toBe(dialog);
    expect(cancel).not.toHaveBeenCalled();
  });

  it('updates detailed and compact job observations without relabeling raw errors, notes or IDs', () => {
    const rejected = rejectedJob();
    render(
      <>
        <JobRecord job={rejected} expanded />
        <StageStrip job={rejected} compact />
      </>,
    );
    const disclosure = screen.getByLabelText('Extraction stage details').closest('details')!;
    disclosure.open = true;
    switchTo('en');
    expect(screen.getByLabelText('Extraction stage details').closest('details')).toBe(disclosure);
    expect(disclosure.open).toBe(true);
    expect(
      screen.getByText('Core validation failed. Structures requiring review: 2.'),
    ).toBeVisible();
    expect(disclosure).toHaveTextContent('Needs review');
    expect(disclosure).toHaveTextContent('Structures: 2');
    expect(screen.getByRole('region', { name: 'Failure details' })).toHaveTextContent(
      'core_not_accepted：设置已保存。',
    );
    expect(screen.getByRole('region', { name: 'Saved task parameters' })).toHaveTextContent('保存');
    expect(screen.getByText('Task ' + rejected.id)).toBeVisible();
    switchTo('zh-CN');
    expect(screen.getByText('核心校验未通过，2 条结构需复核。')).toBeVisible();
    expect(disclosure.open).toBe(true);
  });

  it('keeps history titles, record IDs, page size and server read count stable on a language switch', async () => {
    const entry = trashed(historyEntry({ kind: 'job', title: '设置已保存。' }));
    const read = vi.spyOn(api, 'history').mockResolvedValue(historyList([entry]));
    render(
      <HistoryDialog
        title="回收站"
        initialKind="job"
        deleted
        filters
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    await screen.findByText(entry.title);
    await userEvent.selectOptions(screen.getByLabelText('History records per page'), '100');
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    const dialog = screen.getByRole('dialog', { name: 'Trash' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '回收站' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Trash' })).toBe(dialog);
    expect(screen.getByLabelText('History records per page')).toHaveValue('100');
    expect(within(dialog).getByRole('button', { name: 'Restore 设置已保存。' })).toBeEnabled();
    expect(within(dialog).getByText('Records: 1 · Page 1')).toBeVisible();
    expect(within(dialog).getByText(entry.title).closest('li')).toHaveAttribute(
      'data-history-id',
      entry.id,
    );
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '回收站' })).toBe(dialog);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it('switches a blocked deletion confirmation without translating user titles or raw server reasons', async () => {
    const entry = historyEntry({
      title: '保存',
      can_delete: false,
      blocked_reason: '设置已保存。',
    });
    const read = vi.spyOn(api, 'historyEntry').mockResolvedValue(entry);
    const remove = vi.spyOn(api, 'deleteHistory');
    render(<DeletionDialog target={entry} action="delete" onClose={vi.fn()} onChanged={vi.fn()} />);
    await screen.findByText(entry.blocked_reason!);
    const dialog = screen.getByRole('dialog', { name: 'Delete Project?' });
    switchTo('zh-CN');
    expect(screen.getByRole('dialog', { name: '删除项目？' })).toBe(dialog);
    switchTo('en');
    expect(screen.getByRole('dialog', { name: 'Delete Project?' })).toBe(dialog);
    expect(within(dialog).getByText('保存')).toBeVisible();
    expect(within(dialog).getByText('设置已保存。')).toBeVisible();
    expect(within(dialog).getByText(/No disk space is reclaimed/)).toBeVisible();
    expect(within(dialog).getByRole('button', { name: 'Confirm move to Trash' })).toBeDisabled();
    switchTo('zh-CN');
    expect(read).toHaveBeenCalledTimes(1);
    expect(remove).not.toHaveBeenCalled();
  });

  it('localizes fresh acceptance captions and retained errors, never measurements or source messages', () => {
    const stored = new UiError('组件依赖 {id} 未在服务端目录中声明，不能确认安装。', {
      id: '依赖原文',
    });
    const raw = 'qa: Compound I-7: 设置已保存。';
    const activity = {
      name: '保存',
      value: '中文原值',
      unit: 'nM',
      target: null,
      assay: null,
      page: null,
    };
    switchTo('en');
    const groups = acceptanceIssueGroups([raw, 'smiles: Compound I-7: 设置已保存。']);
    expect(groups[0]?.subject).toBe('Compound I-7');
    expect(groups[0]?.issues[0]).toEqual({
      message: '设置已保存。',
      stages: ['Core validation', 'SMILES recognition'],
    });
    expect(acceptanceIssueCount(groups)).toBe('Structures: 1');
    expect(activityText(activity)).toBe('保存 = 中文原值 nM');
    expect(errorText(stored)).toBe(
      'Dependency 依赖原文 is absent from the server catalog. Installation cannot be confirmed.',
    );
    switchTo('zh-CN');
    expect(errorText(stored)).toBe('组件依赖 依赖原文 未在服务端目录中声明，不能确认安装。');
    expect(stored.message).toBe('组件依赖 依赖原文 未在服务端目录中声明，不能确认安装。');
  });

  it.each([
    ['recognition', 'Structure completion'],
    ['properties', 'Property calculation'],
    ['lead', 'Lead prioritization'],
  ] as const)('updates expanded %s observation and resource captions in place', (phase, label) => {
    const stage: Stage = {
      ...job.stages[0]!,
      name: 'admet',
      progress: { ...progress, phase },
      resource_wait: { reason: 'memory', required_mb: 3072, available_mb: 1024, waited_seconds: 7 },
      repair: { regions: 2, unresolved: 1 },
      skipped: 1,
    };
    const view = render(
      <StageObservation job={{ ...job, admet_only: true }} stage={stage} name="admet" />,
    );
    const detail = view.container.querySelector('details')!;
    detail.open = true;
    switchTo('en');
    expect(screen.getByText(label, { selector: 'strong' })).toBeVisible();
    expect(screen.getByText('Memory required 3072 MB · Available 1024 MB')).toBeVisible();
    expect(screen.getByText('Waited 7 seconds')).toBeVisible();
    expect(screen.getByText('Source regions 2 · Unresolved 1')).toBeVisible();
    expect(screen.getByText('Not calculated: 1 (no valid SMILES)')).toBeVisible();
    expect(detail.querySelector('summary')).toHaveAttribute(
      'title',
      expect.stringContaining('LogS is an ADMET prediction'),
    );
    switchTo('zh-CN');
    expect(screen.getByText('已等待 7 秒')).toBeVisible();
    expect(view.container.querySelector('details')).toBe(detail);
    expect(detail.open).toBe(true);
  });

  it('preserves every original Chinese progress caption and translates only its presentation', () => {
    for (const name of ['structures', 'smiles'] as const) {
      for (const status of ['running', 'failed'] as const) {
        const stage: Stage = { ...job.stages[0]!, name, status, progress };
        switchTo('zh-CN');
        expect(jobStageProgressText(stage)).toBe(stageProgressText(stage));
        switchTo('en');
        const expected =
          (status === 'failed' ? 'Processed ' : '') +
          '10 / 10' +
          (name === 'structures' ? ' pages' : '');
        expect(jobStageProgressText(stage)).toBe(expected);
        expect(stage.progress).toEqual(progress);
      }
    }
  });
});
